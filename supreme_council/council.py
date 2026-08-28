"""Pipeline orchestration, quality gate, and extension hooks."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from .agents import CriticAgent, StrategistAgent, SynthesizerAgent
from .schemas import (
    AuditEvent,
    CouncilState,
    CritiqueReport,
    SupremeVerdict,
    TokenUsage,
)

logger = logging.getLogger(__name__)


class HumanApprovalGate(Protocol):
    """Replace with a UI/API-backed approval implementation when needed."""

    async def approve(self, *, stage: str, state: CouncilState) -> bool: ...


class AutoApproveGate:
    async def approve(self, *, stage: str, state: CouncilState) -> bool:
        return True


class HumanApprovalRequired(RuntimeError):
    def __init__(self, stage: str, state: CouncilState) -> None:
        super().__init__(f"Human approval required at stage={stage}")
        self.stage = stage
        self.state = state


class QualityGateFailed(RuntimeError):
    """Raised when the last allowed verdict still violates deterministic policy."""

    def __init__(self, state: CouncilState, reasons: tuple[str, ...]) -> None:
        details = "; ".join(reasons) or "unspecified quality policy violation"
        super().__init__(f"Quality gate failed: {details}")
        self.state = state
        self.reasons = reasons


@dataclass(frozen=True, slots=True)
class QualityGate:
    min_confidence: float = 0.78
    max_unresolved_questions: int = 3
    max_contradictions: int = 0
    blocking_risk_severities: frozenset[str] = frozenset({"high", "critical"})

    def rejection_reasons(
        self,
        verdict: SupremeVerdict,
        critique: CritiqueReport | None = None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if verdict.confidence < self.min_confidence:
            reasons.append(
                f"confidence {verdict.confidence:.3f} is below "
                f"{self.min_confidence:.3f}"
            )
        if verdict.needs_revision:
            reasons.append("verdict requests revision")
        if len(verdict.unresolved_questions) > self.max_unresolved_questions:
            reasons.append(
                f"unresolved questions {len(verdict.unresolved_questions)} exceed "
                f"{self.max_unresolved_questions}"
            )

        if critique is not None:
            if len(critique.contradictions) > self.max_contradictions:
                reasons.append(
                    f"critic contradictions {len(critique.contradictions)} exceed "
                    f"{self.max_contradictions}"
                )
            blocking_risks = [
                risk
                for risk in critique.critical_risks
                if risk.severity in self.blocking_risk_severities
            ]
            if blocking_risks:
                titles = ", ".join(risk.title for risk in blocking_risks[:3])
                reasons.append(
                    f"critic reported {len(blocking_risks)} blocking risk(s): {titles}"
                )

        return tuple(reasons)

    def accepts(
        self,
        verdict: SupremeVerdict,
        critique: CritiqueReport | None = None,
    ) -> bool:
        return not self.rejection_reasons(verdict, critique)


@dataclass(slots=True)
class Council:
    strategist: StrategistAgent
    critic: CriticAgent
    synthesizer: SynthesizerAgent
    quality_gate: QualityGate
    max_revision_rounds: int = 1
    approval_gate: HumanApprovalGate = field(default_factory=AutoApproveGate)

    async def run(
        self,
        user_prompt: str,
        *,
        metadata: dict[str, object] | None = None,
    ) -> CouncilState:
        """Execute strategist -> critic -> synthesizer with bounded feedback loops."""
        state = CouncilState(user_prompt=user_prompt, metadata=metadata or {})

        base_result = await self._execute_stage("base_draft", self.strategist, state)
        state.base_draft = base_result.value
        self._record_success(state, "base_draft", self.strategist, base_result)
        await self._require_approval("after_base_draft", state)

        # First synthesis plus at most ``max_revision_rounds`` feedback revisions.
        for round_index in range(self.max_revision_rounds + 1):
            critique_result = await self._execute_stage("critique", self.critic, state)
            state.critiques.append(critique_result.value)
            self._record_success(state, "critique", self.critic, critique_result)

            verdict_result = await self._execute_stage(
                "verdict", self.synthesizer, state
            )
            state.verdicts.append(verdict_result.value)
            self._record_success(state, "verdict", self.synthesizer, verdict_result)

            rejection_reasons = self.quality_gate.rejection_reasons(
                verdict_result.value,
                critique_result.value,
            )
            if not rejection_reasons:
                state.status = "quality_passed"
                state.audit_log.append(
                    AuditEvent(
                        stage="quality_gate",
                        agent="QualityGate",
                        model="deterministic",
                        status="success",
                    )
                )
                break

            if round_index < self.max_revision_rounds:
                logger.info(
                    "Quality gate requested revision run_id=%s round=%s reasons=%s",
                    state.run_id,
                    round_index + 1,
                    "; ".join(rejection_reasons),
                )
                continue

            state.status = "quality_failed"
            state.audit_log.append(
                AuditEvent(
                    stage="quality_gate",
                    agent="QualityGate",
                    model="deterministic",
                    status="failure",
                    error="; ".join(rejection_reasons),
                )
            )
            raise QualityGateFailed(state, rejection_reasons)

        await self._require_approval("before_final_release", state)
        return state

    async def _execute_stage(self, stage: str, agent: object, state: CouncilState):
        try:
            return await agent.execute(state)  # type: ignore[attr-defined]
        except Exception as exc:
            usage = getattr(exc, "usage", TokenUsage())
            latency_ms = getattr(exc, "latency_ms", 0)
            state.total_usage = state.total_usage + usage
            state.total_latency_ms += latency_ms
            state.audit_log.append(
                AuditEvent(
                    stage=stage,
                    agent=getattr(agent, "name", type(agent).__name__),
                    model=getattr(
                        getattr(agent, "model_spec", None), "primary", "unknown"
                    ),
                    status="failure",
                    duration_ms=latency_ms,
                    usage=usage,
                    model_calls=list(getattr(exc, "attempts", ())),
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            raise

    @staticmethod
    def _record_success(
        state: CouncilState, stage: str, agent: object, result: object
    ) -> None:
        usage = result.usage  # type: ignore[attr-defined]
        state.total_usage = state.total_usage + usage
        state.total_latency_ms += result.latency_ms  # type: ignore[attr-defined]
        state.audit_log.append(
            AuditEvent(
                stage=stage,
                agent=getattr(agent, "name", type(agent).__name__),
                model=result.model_used,  # type: ignore[attr-defined]
                status="success",
                duration_ms=result.latency_ms,  # type: ignore[attr-defined]
                usage=usage,
                model_calls=list(getattr(result, "attempts", ())),
            )
        )

    async def _require_approval(self, stage: str, state: CouncilState) -> None:
        if not await self.approval_gate.approve(stage=stage, state=state):
            raise HumanApprovalRequired(stage, state)
