"""Composition root for the application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .agents import ContextPolicy, CriticAgent, StrategistAgent, SynthesizerAgent
from .config import CouncilSettings
from .council import Council, HumanApprovalGate, QualityGate
from .provider import (
    LiteLLMProvider,
    ModelEndpoint,
    ModelSpec,
    StructuredLLMProvider,
)


def build_council(
    settings: CouncilSettings,
    *,
    provider: StructuredLLMProvider | None = None,
    approval_gate: HumanApprovalGate | None = None,
) -> Council:
    provider = provider or LiteLLMProvider()
    context = ContextPolicy(max_chars=settings.max_context_chars)

    common = {
        "timeout_seconds": settings.request_timeout_seconds,
        "attempts_per_model": settings.max_attempts_per_model,
    }

    strategist = StrategistAgent(
        provider=provider,
        context_policy=context,
        model_spec=ModelSpec(
            primary=settings.strategist_model,
            fallbacks=settings.model_list(settings.strategist_fallbacks),
            temperature=0.15,
            max_tokens=4_000,
            **common,
        ),
    )
    critic = CriticAgent(
        provider=provider,
        context_policy=context,
        model_spec=ModelSpec(
            primary=settings.critic_model,
            fallbacks=settings.model_list(settings.critic_fallbacks),
            temperature=0.35,
            max_tokens=4_500,
            **common,
        ),
    )
    synthesizer = SynthesizerAgent(
        provider=provider,
        context_policy=context,
        model_spec=ModelSpec(
            primary=settings.synthesizer_model,
            fallbacks=settings.model_list(settings.synthesizer_fallbacks),
            temperature=0.20,
            max_tokens=5_000,
            **common,
        ),
    )

    kwargs = {}
    if approval_gate is not None:
        kwargs["approval_gate"] = approval_gate

    return Council(
        strategist=strategist,
        critic=critic,
        synthesizer=synthesizer,
        quality_gate=QualityGate(
            min_confidence=settings.min_verdict_confidence,
            max_unresolved_questions=settings.max_unresolved_questions,
            max_contradictions=settings.max_critic_contradictions,
        ),
        max_revision_rounds=settings.max_revision_rounds,
        **kwargs,
    )


def build_council_from_endpoints(
    settings: CouncilSettings,
    role_endpoints: Mapping[str, Sequence[ModelEndpoint]],
    *,
    provider: StructuredLLMProvider | None = None,
    approval_gate: HumanApprovalGate | None = None,
) -> Council:
    """Build a council from GUI-managed, independently authenticated endpoints."""
    required_roles = ("strategist", "critic", "synthesizer")
    resolved: dict[str, tuple[ModelEndpoint, ...]] = {
        role: tuple(role_endpoints.get(role, ())) for role in required_roles
    }
    missing = [role for role, endpoints in resolved.items() if not endpoints]
    if missing:
        raise ValueError(
            "Her rol için en az bir aktif API gerekir: " + ", ".join(missing)
        )

    provider = provider or LiteLLMProvider()
    context = ContextPolicy(max_chars=settings.max_context_chars)
    common = {
        "timeout_seconds": settings.request_timeout_seconds,
        "attempts_per_model": settings.max_attempts_per_model,
    }

    def spec_for(
        role: str,
        *,
        temperature: float,
        max_tokens: int,
    ) -> ModelSpec:
        endpoints = resolved[role]
        return ModelSpec(
            primary=endpoints[0].model,
            fallbacks=tuple(endpoint.model for endpoint in endpoints[1:]),
            endpoints=endpoints,
            temperature=temperature,
            max_tokens=max_tokens,
            **common,
        )

    strategist = StrategistAgent(
        provider=provider,
        context_policy=context,
        model_spec=spec_for("strategist", temperature=0.15, max_tokens=4_000),
    )
    critic = CriticAgent(
        provider=provider,
        context_policy=context,
        model_spec=spec_for("critic", temperature=0.35, max_tokens=4_500),
    )
    synthesizer = SynthesizerAgent(
        provider=provider,
        context_policy=context,
        model_spec=spec_for("synthesizer", temperature=0.20, max_tokens=5_000),
    )

    kwargs = {}
    if approval_gate is not None:
        kwargs["approval_gate"] = approval_gate

    return Council(
        strategist=strategist,
        critic=critic,
        synthesizer=synthesizer,
        quality_gate=QualityGate(
            min_confidence=settings.min_verdict_confidence,
            max_unresolved_questions=settings.max_unresolved_questions,
            max_contradictions=settings.max_critic_contradictions,
        ),
        max_revision_rounds=settings.max_revision_rounds,
        **kwargs,
    )
