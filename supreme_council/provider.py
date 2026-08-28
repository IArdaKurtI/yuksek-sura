"""Provider abstraction and LiteLLM implementation."""

from __future__ import annotations

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

try:
    import litellm
    from litellm import (
        acompletion,
        get_supported_openai_params,
        supports_response_schema,
    )
except ModuleNotFoundError:  # Allows unit tests with injected providers.
    litellm = None  # type: ignore[assignment]
    acompletion = None  # type: ignore[assignment]
    get_supported_openai_params = None  # type: ignore[assignment]
    supports_response_schema = None  # type: ignore[assignment]
from pydantic import BaseModel, ValidationError

from .schemas import ModelCall, TokenUsage

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """Raised when all configured models fail."""

    def __init__(
        self,
        message: str,
        *,
        attempts: tuple[ModelCall, ...] = (),
        latency_ms: int = 0,
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.latency_ms = latency_ms
        self.usage = _sum_usage(attempt.usage for attempt in attempts)


class StructuredOutputError(ValueError):
    """Raised when a provider response violates the output contract."""


@dataclass(frozen=True, slots=True)
class ModelEndpoint:
    """One independently authenticated model connection."""

    model: str
    label: str = ""
    api_key: str | None = field(default=None, repr=False, compare=False)
    api_base: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ModelSpec:
    primary: str
    fallbacks: tuple[str, ...] = ()
    temperature: float = 0.2
    max_tokens: int = 4_000
    timeout_seconds: float = 90.0
    attempts_per_model: int = 3
    extra: dict[str, Any] = field(default_factory=dict)
    endpoints: tuple[ModelEndpoint, ...] = ()

    @property
    def candidates(self) -> tuple[str, ...]:
        ordered = (self.primary, *self.fallbacks)
        return tuple(dict.fromkeys(model for model in ordered if model))

    @property
    def candidate_endpoints(self) -> tuple[ModelEndpoint, ...]:
        if self.endpoints:
            return tuple(endpoint for endpoint in self.endpoints if endpoint.model)
        return tuple(ModelEndpoint(model=model) for model in self.candidates)


@dataclass(slots=True)
class _AttemptBudget:
    """A shared request budget across all response modes for one model."""

    limit: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self) -> None:
        if self.remaining <= 0:
            raise ProviderError("Model attempt budget exhausted")
        self.used += 1


@dataclass(slots=True)
class LLMResult(Generic[T]):
    value: T
    model_used: str
    usage: TokenUsage
    latency_ms: int
    raw_content: str
    attempts: tuple[ModelCall, ...] = ()


def _sum_usage(usages: Iterable[TokenUsage]) -> TokenUsage:
    total = TokenUsage()
    for usage in usages:
        total = total + usage
    return total


class StructuredLLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[T],
        model_spec: ModelSpec,
    ) -> LLMResult[T]:
        """Return a response validated against ``response_model``."""


class LiteLLMProvider(StructuredLLMProvider):
    """Multi-provider adapter with retries, schema repair, and model failover."""

    _NON_RETRYABLE_NAMES = (
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
    )

    def __init__(self) -> None:
        if litellm is None or acompletion is None:
            raise RuntimeError("LiteLLM is not installed. Run: pip install -e .")
        # Enables LiteLLM's optional client-side JSON schema validation where supported.
        litellm.enable_json_schema_validation = True

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[T],
        model_spec: ModelSpec,
    ) -> LLMResult[T]:
        failures: list[str] = []
        attempts: list[ModelCall] = []
        started = time.perf_counter()

        for endpoint in model_spec.candidate_endpoints:
            model = endpoint.model
            budget = _AttemptBudget(model_spec.attempts_per_model)
            for mode in self._response_modes(model):
                if budget.remaining <= 0:
                    break
                try:
                    result = await self._complete_with_retries(
                        model=model,
                        mode=mode,
                        messages=messages,
                        response_model=response_model,
                        model_spec=model_spec,
                        endpoint=endpoint,
                        budget=budget,
                        attempts=attempts,
                    )
                    result.usage = _sum_usage(
                        attempt.usage for attempt in attempts
                    )
                    result.latency_ms = int(
                        (time.perf_counter() - started) * 1000
                    )
                    result.attempts = tuple(attempts)
                    return result
                except Exception as exc:  # noqa: BLE001 - aggregated failover boundary
                    safe_error = self._safe_error(exc, endpoint.api_key)
                    failures.append(f"{model}[{mode}]: {safe_error}")
                    logger.warning("Model attempt failed: %s", failures[-1])

                    # Only response-contract incompatibilities benefit from trying a weaker
                    # response mode on the same model. Provider outages/auth failures should
                    # move directly to the next model instead of multiplying failed calls.
                    if budget.remaining > 0 and self._should_try_next_mode(exc):
                        continue
                    break

        joined = " | ".join(failures[-12:])
        raise ProviderError(
            f"All models and response modes failed. {joined}",
            attempts=tuple(attempts),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def _complete_with_retries(
        self,
        *,
        model: str,
        mode: str,
        messages: list[dict[str, str]],
        response_model: type[T],
        model_spec: ModelSpec,
        endpoint: ModelEndpoint,
        budget: _AttemptBudget,
        attempts: list[ModelCall],
    ) -> LLMResult[T]:
        from tenacity import (
            AsyncRetrying,
            retry_if_exception,
            stop_after_attempt,
            wait_random_exponential,
        )

        working_messages = list(messages)
        last_invalid_content: str | None = None

        attempts_for_mode = budget.remaining
        exponential_wait = wait_random_exponential(multiplier=1, min=1, max=20)

        def retry_wait(retry_state: Any) -> float:
            exc = retry_state.outcome.exception() if retry_state.outcome else None
            if isinstance(exc, StructuredOutputError):
                return 0.0
            return float(exponential_wait(retry_state))

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts_for_mode),
            wait=retry_wait,
            retry=retry_if_exception(self._is_retryable),
            reraise=True,
            before_sleep=self._before_sleep,
        ):
            with attempt:
                if last_invalid_content is not None:
                    working_messages = self._repair_messages(
                        base_messages=messages,
                        invalid_content=last_invalid_content,
                        response_model=response_model,
                    )

                budget.consume()
                call_started = time.perf_counter()
                request: dict[str, Any] = {
                    "model": model,
                    "messages": working_messages,
                    "temperature": model_spec.temperature,
                    "max_tokens": model_spec.max_tokens,
                    "timeout": model_spec.timeout_seconds,
                    "num_retries": 0,
                    **model_spec.extra,
                    **endpoint.extra,
                }
                if endpoint.api_key:
                    request["api_key"] = endpoint.api_key
                if endpoint.api_base:
                    request["api_base"] = endpoint.api_base
                response_format = self._response_format(mode, response_model)
                if response_format is not None:
                    request["response_format"] = response_format

                try:
                    response = await acompletion(**request)
                except Exception as exc:
                    attempts.append(
                        ModelCall(
                            model=model,
                            connection=endpoint.label or None,
                            response_mode=mode,
                            status="failure",
                            duration_ms=int(
                                (time.perf_counter() - call_started) * 1000
                            ),
                            usage=self._extract_exception_usage(exc),
                            error=self._safe_error(exc, endpoint.api_key),
                        )
                    )
                    raise

                latency_ms = int((time.perf_counter() - call_started) * 1000)
                usage = self._extract_usage(response)

                try:
                    raw_content = self._extract_content(response)
                    parsed = self._parse(raw_content, response_model)
                except Exception as exc:
                    if isinstance(exc, StructuredOutputError):
                        last_invalid_content = raw_content
                    attempts.append(
                        ModelCall(
                            model=model,
                            connection=endpoint.label or None,
                            response_mode=mode,
                            status="failure",
                            duration_ms=latency_ms,
                            usage=usage,
                            error=self._safe_error(exc, endpoint.api_key),
                        )
                    )
                    raise

                attempts.append(
                    ModelCall(
                        model=model,
                        connection=endpoint.label or None,
                        response_mode=mode,
                        status="success",
                        duration_ms=latency_ms,
                        usage=usage,
                    )
                )

                return LLMResult(
                    value=parsed,
                    model_used=model,
                    usage=usage,
                    latency_ms=latency_ms,
                    raw_content=raw_content,
                )

        raise ProviderError(f"Retry loop ended unexpectedly for model={model}")

    @staticmethod
    def _response_modes(model: str) -> tuple[str, ...]:
        """Prefer provider-enforced JSON Schema, then JSON mode, then prompt-only JSON."""
        modes: list[str] = []
        try:
            if supports_response_schema is not None and supports_response_schema(
                model=model
            ):
                modes.append("schema")
        except Exception as exc:  # noqa: BLE001 - model registry can be incomplete
            logger.debug(
                "Response-schema capability lookup failed for %s: %s", model, exc
            )

        try:
            supported = (
                get_supported_openai_params(model=model)
                if get_supported_openai_params
                else []
            ) or []
            if "response_format" in supported:
                modes.append("json")
        except Exception as exc:  # noqa: BLE001 - model registry can be incomplete
            logger.debug(
                "Response-format capability lookup failed for %s: %s", model, exc
            )

        modes.append("prompt")
        return tuple(dict.fromkeys(modes))

    @staticmethod
    def _response_format(mode: str, response_model: type[BaseModel]) -> Any:
        if mode == "schema":
            return response_model
        if mode == "json":
            return {"type": "json_object"}
        # LiteLLM drops None for providers without response_format support.
        return None

    @classmethod
    def _is_retryable(cls, exc: BaseException) -> bool:
        if isinstance(exc, StructuredOutputError):
            return True

        non_retryable = tuple(
            error_type
            for name in cls._NON_RETRYABLE_NAMES
            if litellm is not None
            and isinstance((error_type := getattr(litellm, name, None)), type)
        )
        if non_retryable and isinstance(exc, non_retryable):
            return False

        # BadRequest may be caused by response_format incompatibility; switch mode instead
        # of repeatedly sending the same invalid request.
        bad_request = (
            getattr(litellm, "BadRequestError", None) if litellm is not None else None
        )
        if isinstance(bad_request, type) and isinstance(exc, bad_request):
            return False

        retryable_names = (
            "RateLimitError",
            "Timeout",
            "APIConnectionError",
            "APIError",
            "InternalServerError",
            "ServiceUnavailableError",
        )
        retryable = tuple(
            error_type
            for name in retryable_names
            if litellm is not None
            and isinstance((error_type := getattr(litellm, name, None)), type)
        )
        return isinstance(exc, (TimeoutError, ConnectionError)) or (
            bool(retryable) and isinstance(exc, retryable)
        )

    @staticmethod
    def _should_try_next_mode(exc: BaseException) -> bool:
        if isinstance(exc, StructuredOutputError):
            return True
        bad_request = (
            getattr(litellm, "BadRequestError", None) if litellm is not None else None
        )
        return isinstance(bad_request, type) and isinstance(exc, bad_request)

    @staticmethod
    def _before_sleep(retry_state: Any) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "Retrying LLM call; attempt=%s error=%s",
            retry_state.attempt_number,
            exc,
        )

    @staticmethod
    def _repair_messages(
        *,
        base_messages: list[dict[str, str]],
        invalid_content: str,
        response_model: type[BaseModel],
    ) -> list[dict[str, str]]:
        schema = json.dumps(response_model.model_json_schema(), ensure_ascii=False)
        clipped = invalid_content[:6_000]
        return [
            *base_messages,
            {"role": "assistant", "content": clipped},
            {
                "role": "user",
                "content": (
                    "Önceki yanıt çıktı sözleşmesini ihlal etti. Yalnızca geçerli JSON döndür; "
                    "açıklama, Markdown veya kod çiti ekleme. Şema: " + schema
                ),
            },
        ]

    @staticmethod
    def _extract_content(response: Any) -> str:
        try:
            message = response.choices[0].message
            content = message.content
        except (AttributeError, IndexError, KeyError, TypeError) as exc:
            raise ProviderError("Provider response has no message content") from exc

        if content is None:
            parsed = getattr(message, "parsed", None)
            if isinstance(parsed, BaseModel):
                return parsed.model_dump_json()
            if isinstance(parsed, dict):
                return json.dumps(parsed, ensure_ascii=False)
            raise ProviderError("Provider response has no message content")
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    chunks.append(
                        str(item.get("text", json.dumps(item, ensure_ascii=False)))
                    )
                else:
                    chunks.append(str(item))
            return "".join(chunks)
        return str(content)

    @staticmethod
    def _parse(raw_content: str, response_model: type[T]) -> T:
        cleaned = raw_content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as first_error:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start >= 0 and end > start:
                candidate = cleaned[start : end + 1]
                try:
                    return response_model.model_validate_json(candidate)
                except ValidationError:
                    pass
            raise StructuredOutputError(
                f"Invalid structured output for {response_model.__name__}: {first_error}"
            ) from first_error

    @staticmethod
    def _extract_usage(response: Any) -> TokenUsage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return TokenUsage()

        def read(name: str) -> int:
            value = getattr(usage, name, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(name)
            return int(value or 0)

        prompt_tokens = read("prompt_tokens")
        completion_tokens = read("completion_tokens")
        total_tokens = read("total_tokens") or prompt_tokens + completion_tokens
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    @classmethod
    def _extract_exception_usage(cls, exc: BaseException) -> TokenUsage:
        """Best-effort accounting for providers that attach a response to errors."""
        response = getattr(exc, "response", None)
        if response is None:
            return TokenUsage()
        return cls._extract_usage(response)

    @staticmethod
    def _safe_error(exc: BaseException, api_key: str | None = None) -> str:
        message = f"{type(exc).__name__}: {exc}"
        if api_key:
            message = message.replace(api_key, "[REDACTED]")
        return message
