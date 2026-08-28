"""Pydantic contracts shared by all council stages."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Strict-enough base model for LLM-facing contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class RiskItem(ContractModel):
    title: str = Field(min_length=1, max_length=180)
    severity: Literal["low", "medium", "high", "critical"]
    explanation: str = Field(min_length=1)
    mitigation: str = Field(min_length=1)


class EdgeIdea(ContractModel):
    idea: str = Field(min_length=1)
    why_usually_rejected: str = Field(min_length=1)
    hidden_value: str = Field(min_length=1)
    activation_conditions: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class BaseDraft(ContractModel):
    executive_summary: str = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    standard_strategy: list[str] = Field(min_length=1)
    implementation_steps: list[str] = Field(min_length=1)
    risks: list[RiskItem] = Field(default_factory=list)
    base_answer: str = Field(min_length=1)


class CritiqueReport(ContractModel):
    target: Literal["base_draft", "supreme_verdict"]
    strengths: list[str] = Field(default_factory=list)
    conventional_traps: list[str] = Field(default_factory=list)
    hidden_edge_ideas: list[EdgeIdea] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    recommended_changes: list[str] = Field(default_factory=list)
    critical_risks: list[RiskItem] = Field(default_factory=list)
    critique_summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class SupremeVerdict(ContractModel):
    decision_summary: str = Field(min_length=1)
    final_answer: str = Field(min_length=1)
    adopted_edge_ideas: list[str] = Field(default_factory=list)
    rejected_edge_ideas: list[str] = Field(default_factory=list)
    safeguards: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_revision: bool = False


class TokenUsage(ContractModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class ModelCall(ContractModel):
    """Accounting record for one physical provider request."""

    model: str
    connection: str | None = None
    response_mode: Literal["schema", "json", "prompt"]
    status: Literal["success", "failure"]
    duration_ms: int = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    error: str | None = None


class AuditEvent(ContractModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stage: str
    agent: str
    model: str
    status: Literal["success", "failure", "skipped"]
    duration_ms: int = Field(default=0, ge=0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model_calls: list[ModelCall] = Field(default_factory=list)
    error: str | None = None


class CouncilState(ContractModel):
    """Serializable state passed between agents."""

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: Literal["running", "quality_passed", "quality_failed"] = "running"
    user_prompt: str = Field(min_length=1)
    base_draft: BaseDraft | None = None
    critiques: list[CritiqueReport] = Field(default_factory=list)
    verdicts: list[SupremeVerdict] = Field(default_factory=list)
    audit_log: list[AuditEvent] = Field(default_factory=list)
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_latency_ms: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def latest_critique(self) -> CritiqueReport | None:
        return self.critiques[-1] if self.critiques else None

    @property
    def latest_verdict(self) -> SupremeVerdict | None:
        return self.verdicts[-1] if self.verdicts else None
