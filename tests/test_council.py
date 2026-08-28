from __future__ import annotations

import json
from collections import deque
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from supreme_council.agents import (
    ContextPolicy,
    CriticAgent,
    StrategistAgent,
    SynthesizerAgent,
)
from supreme_council.cli import parse_args
from supreme_council.council import Council, QualityGate, QualityGateFailed
import supreme_council.provider as provider_module
from supreme_council.provider import (
    LiteLLMProvider,
    LLMResult,
    ModelEndpoint,
    ModelSpec,
    StructuredLLMProvider,
)
from supreme_council.schemas import (
    BaseDraft,
    CritiqueReport,
    RiskItem,
    SupremeVerdict,
    TokenUsage,
)


class FakeProvider(StructuredLLMProvider):
    def __init__(self, outputs: list[BaseModel]) -> None:
        self.outputs = deque(outputs)

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        model_spec: ModelSpec,
    ) -> LLMResult[Any]:
        value = self.outputs.popleft()
        assert isinstance(value, response_model)
        return LLMResult(
            value=value,
            model_used=model_spec.primary,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            latency_ms=1,
            raw_content=value.model_dump_json(),
        )


@pytest.mark.asyncio
async def test_pipeline_runs_one_revision() -> None:
    base = BaseDraft(
        executive_summary="Initial plan",
        assumptions=[],
        standard_strategy=["A"],
        implementation_steps=["B"],
        risks=[],
        base_answer="Draft",
    )
    critique_1 = CritiqueReport(
        target="base_draft",
        critique_summary="Needs work",
        confidence=0.9,
    )
    verdict_1 = SupremeVerdict(
        decision_summary="First",
        final_answer="First verdict",
        confidence=0.60,
        needs_revision=True,
    )
    critique_2 = CritiqueReport(
        target="supreme_verdict",
        critique_summary="Fixed direction",
        confidence=0.9,
    )
    verdict_2 = SupremeVerdict(
        decision_summary="Final",
        final_answer="Accepted verdict",
        confidence=0.91,
        needs_revision=False,
    )

    provider = FakeProvider([base, critique_1, verdict_1, critique_2, verdict_2])
    spec = ModelSpec(primary="fake/model", attempts_per_model=1)
    context = ContextPolicy(max_chars=10_000)

    council = Council(
        strategist=StrategistAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        critic=CriticAgent(provider=provider, model_spec=spec, context_policy=context),
        synthesizer=SynthesizerAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        quality_gate=QualityGate(min_confidence=0.8),
        max_revision_rounds=1,
    )

    state = await council.run("Build something")

    assert state.latest_verdict is not None
    assert state.latest_verdict.final_answer == "Accepted verdict"
    assert len(state.verdicts) == 2
    assert state.total_usage.total_tokens == 75
    assert state.total_latency_ms == 5


@pytest.mark.asyncio
async def test_pipeline_stops_when_first_verdict_passes_quality_gate() -> None:
    base = BaseDraft(
        executive_summary="Plan",
        standard_strategy=["A"],
        implementation_steps=["B"],
        base_answer="Draft",
    )
    critique = CritiqueReport(
        target="base_draft",
        critique_summary="Looks sound",
        confidence=0.9,
    )
    verdict = SupremeVerdict(
        decision_summary="Accepted",
        final_answer="Final answer",
        confidence=0.95,
    )
    provider = FakeProvider([base, critique, verdict])
    spec = ModelSpec(primary="fake/model", attempts_per_model=1)
    context = ContextPolicy(max_chars=10_000)
    council = Council(
        strategist=StrategistAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        critic=CriticAgent(provider=provider, model_spec=spec, context_policy=context),
        synthesizer=SynthesizerAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        quality_gate=QualityGate(min_confidence=0.8),
        max_revision_rounds=3,
    )

    state = await council.run("Build something")

    assert len(state.verdicts) == 1
    assert not provider.outputs
    assert state.total_usage.total_tokens == 45
    assert state.total_latency_ms == 3
    assert state.status == "quality_passed"


@pytest.mark.asyncio
async def test_last_rejected_verdict_raises_and_is_not_released() -> None:
    class RecordingApprovalGate:
        def __init__(self) -> None:
            self.stages: list[str] = []

        async def approve(self, *, stage: str, state: Any) -> bool:
            self.stages.append(stage)
            return True

    base = BaseDraft(
        executive_summary="Plan",
        standard_strategy=["A"],
        implementation_steps=["B"],
        base_answer="Draft",
    )
    critique = CritiqueReport(
        target="base_draft",
        critique_summary="Blocking risk remains",
        critical_risks=[
            RiskItem(
                title="Data loss",
                severity="critical",
                explanation="Writes are not recoverable",
                mitigation="Add transactional recovery",
            )
        ],
        confidence=0.95,
    )
    verdict = SupremeVerdict(
        decision_summary="Unsafe",
        final_answer="Do it anyway",
        confidence=0.95,
        needs_revision=False,
    )
    provider = FakeProvider([base, critique, verdict])
    spec = ModelSpec(primary="fake/model", attempts_per_model=1)
    context = ContextPolicy(max_chars=10_000)
    approval = RecordingApprovalGate()
    council = Council(
        strategist=StrategistAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        critic=CriticAgent(provider=provider, model_spec=spec, context_policy=context),
        synthesizer=SynthesizerAgent(
            provider=provider, model_spec=spec, context_policy=context
        ),
        quality_gate=QualityGate(min_confidence=0.8),
        max_revision_rounds=0,
        approval_gate=approval,
    )

    with pytest.raises(QualityGateFailed) as raised:
        await council.run("Build something")

    assert raised.value.state.status == "quality_failed"
    assert "blocking risk" in str(raised.value)
    assert approval.stages == ["after_base_draft"]
    assert raised.value.state.total_usage.total_tokens == 45
    assert raised.value.state.audit_log[-1].stage == "quality_gate"
    assert raised.value.state.audit_log[-1].status == "failure"


def test_quality_gate_uses_critic_contradictions() -> None:
    verdict = SupremeVerdict(
        decision_summary="Looks complete",
        final_answer="Answer",
        confidence=0.95,
    )
    critique = CritiqueReport(
        target="supreme_verdict",
        contradictions=["The timeline conflicts with the dependency order"],
        critique_summary="Contradiction remains",
        confidence=0.9,
    )

    reasons = QualityGate().rejection_reasons(verdict, critique)

    assert any("contradictions" in reason for reason in reasons)


@pytest.mark.asyncio
async def test_provider_accumulates_usage_from_invalid_and_successful_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = SupremeVerdict(
        decision_summary="Accepted",
        final_answer="Answer",
        confidence=0.9,
    ).model_dump_json()
    responses = deque(
        [
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))],
                usage=SimpleNamespace(
                    prompt_tokens=7, completion_tokens=4, total_tokens=11
                ),
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=valid))],
                usage=SimpleNamespace(
                    prompt_tokens=13, completion_tokens=9, total_tokens=22
                ),
            ),
        ]
    )

    async def fake_completion(**request: Any) -> Any:
        return responses.popleft()

    monkeypatch.setattr(provider_module, "acompletion", fake_completion)
    monkeypatch.setattr(
        LiteLLMProvider,
        "_response_modes",
        staticmethod(lambda model: ("prompt",)),
    )
    provider = object.__new__(LiteLLMProvider)

    result = await provider.complete(
        messages=[{"role": "user", "content": "test"}],
        response_model=SupremeVerdict,
        model_spec=ModelSpec(primary="fake/model", attempts_per_model=2),
    )

    assert result.usage.total_tokens == 33
    assert [attempt.status for attempt in result.attempts] == ["failure", "success"]
    assert result.latency_ms >= sum(attempt.duration_ms for attempt in result.attempts)


@pytest.mark.asyncio
async def test_attempt_budget_is_global_across_response_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeBadRequestError(Exception):
        pass

    calls: list[tuple[str, str | None]] = []
    valid = SupremeVerdict(
        decision_summary="Fallback",
        final_answer="Answer",
        confidence=0.9,
    ).model_dump_json()

    async def fake_completion(**request: Any) -> Any:
        calls.append((request["model"], request.get("api_key")))
        if request["model"] == "primary/model":
            raise FakeBadRequestError(
                f"unsupported response mode for {request.get('api_key')}"
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=valid))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    monkeypatch.setattr(
        provider_module,
        "litellm",
        SimpleNamespace(BadRequestError=FakeBadRequestError),
    )
    monkeypatch.setattr(provider_module, "acompletion", fake_completion)
    monkeypatch.setattr(
        LiteLLMProvider,
        "_response_modes",
        staticmethod(lambda model: ("schema", "json", "prompt")),
    )
    provider = object.__new__(LiteLLMProvider)

    result = await provider.complete(
        messages=[{"role": "user", "content": "test"}],
        response_model=SupremeVerdict,
        model_spec=ModelSpec(
            primary="primary/model",
            fallbacks=("fallback/model",),
            attempts_per_model=2,
            endpoints=(
                ModelEndpoint(
                    model="primary/model",
                    label="Primary key",
                    api_key="PRIMARY-SECRET",
                ),
                ModelEndpoint(
                    model="fallback/model",
                    label="Fallback key",
                    api_key="FALLBACK-SECRET",
                ),
            ),
        ),
    )

    assert [model for model, _ in calls].count("primary/model") == 2
    assert calls[-1] == ("fallback/model", "FALLBACK-SECRET")
    assert result.model_used == "fallback/model"
    assert len(result.attempts) == 3
    assert all("PRIMARY-SECRET" not in (attempt.error or "") for attempt in result.attempts)


def test_context_compaction_keeps_valid_json_and_budget() -> None:
    policy = ContextPolicy(max_chars=300)
    compacted = policy.json({"first": "a" * 1_000, "last": "z" * 1_000})

    payload = json.loads(compacted)

    assert len(compacted) <= 300
    assert payload["context_compacted"] is True
    assert "CONTEXT COMPACTED" in payload["content"]


def test_usage_total_is_derived_when_provider_omits_it() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=None)
    )

    usage = LiteLLMProvider._extract_usage(response)

    assert usage.total_tokens == 20


def test_parsed_response_is_used_when_content_is_none() -> None:
    parsed = SupremeVerdict(
        decision_summary="Accepted",
        final_answer="Final answer",
        confidence=0.9,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, parsed=parsed))]
    )

    raw = LiteLLMProvider._extract_content(response)

    assert SupremeVerdict.model_validate_json(raw) == parsed


def test_prompt_and_prompt_file_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        parse_args(["task", "--prompt-file", "task.txt"])
