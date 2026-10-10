"""Pydantic models.

LLM-output models are deliberately lenient (coerce types, normalise enum
values, supply defaults) so a minor formatting slip from the model never
crashes the demo. Hard guarantees are enforced afterwards in pipeline.py.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Strength = Literal["asserted", "contextual", "substantiated"]
Level = Literal["beginner", "intermediate", "advanced", "unstated"]
Potential = Literal["high", "medium", "low"]
Confidence = Literal["high", "medium", "low"]


def _enum(value: Any, allowed: tuple[str, ...], default: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def _to_int(value: Any, lo: int, hi: int) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        n = lo
    return max(lo, min(hi, n))


# ---------------------------------------------------------------- extraction
class Profile(BaseModel):
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    institution: Optional[str] = None
    cgpa: Optional[str] = None
    graduation_year: Optional[str] = None
    years_experience: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def _str(cls, v: Any) -> Optional[str]:
        return None if v in (None, "", "null") else str(v)


class Claim(BaseModel):
    claim_id: str
    skill: str = "other"
    raw_label: str = ""
    strength: Strength = "asserted"
    claimed_level: Level = "unstated"
    evidence_span: str = ""
    linked_project_id: Optional[str] = None

    @field_validator("strength", mode="before")
    @classmethod
    def _s(cls, v: Any) -> str:
        return _enum(v, ("asserted", "contextual", "substantiated"), "asserted")

    @field_validator("claimed_level", mode="before")
    @classmethod
    def _l(cls, v: Any) -> str:
        return _enum(v, ("beginner", "intermediate", "advanced", "unstated"), "unstated")

    @field_validator("claim_id", "skill", "raw_label", "evidence_span", mode="before")
    @classmethod
    def _txt(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("linked_project_id", mode="before")
    @classmethod
    def _pid(cls, v: Any) -> Optional[str]:
        return None if v in (None, "", "null") else str(v)


class Project(BaseModel):
    project_id: str
    title: str = ""
    description_span: str = ""
    tools_named: list[str] = Field(default_factory=list)
    stated_outcome: Optional[str] = None
    task_grounding_potential: Potential = "low"
    grounding_note: str = ""

    @field_validator("task_grounding_potential", mode="before")
    @classmethod
    def _p(cls, v: Any) -> str:
        return _enum(v, ("high", "medium", "low"), "low")

    @field_validator("tools_named", mode="before")
    @classmethod
    def _tools(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return [str(t) for t in (v or []) if str(t).strip()]

    @field_validator("stated_outcome", mode="before")
    @classmethod
    def _out(cls, v: Any) -> Optional[str]:
        return None if v in (None, "", "null") else str(v)


class ExtractionOut(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    claims: list[Claim] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    extraction_warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- task
class TaskOut(BaseModel):
    task_prompt: str
    grounding_justification: str = ""
    embedded_complication: str = ""
    accessible_entry_point: str = ""
    communication_subtask: str = ""
    probe_seeds: list[str] = Field(default_factory=list)
    expected_strong_answer: str = ""

    @field_validator("task_prompt")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("task_prompt too short")
        return v.strip()


# ---------------------------------------------------------------- scoring
class EvidenceSpan(BaseModel):
    quote: str = ""
    why_it_supports: str = ""


class ScoreOut(BaseModel):
    score: int = 0
    anchor_matched: str = ""
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    missing_for_next_level: str = ""
    confidence: Confidence = "medium"
    confidence_reason: str = ""
    anomaly_flag: Optional[str] = None

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> int:
        return _to_int(v, 0, 4)

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v: Any) -> str:
        return _enum(v, ("high", "medium", "low"), "medium")

    @field_validator("anomaly_flag", mode="before")
    @classmethod
    def _a(cls, v: Any) -> Optional[str]:
        return None if v in (None, "", "null", False) else str(v)

    @field_validator("evidence_spans", mode="before")
    @classmethod
    def _spans(cls, v: Any) -> list:
        if isinstance(v, dict):
            return [v]
        if isinstance(v, str):
            return [{"quote": v}]
        return v or []


# ---------------------------------------------------------------- probes
class Probe(BaseModel):
    probe_id: str = ""
    type: str = "choice"
    anchored_quote: str = ""
    question: str

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        if len(v.strip()) < 8:
            raise ValueError("question too short")
        return v.strip()


class ProbeGenOut(BaseModel):
    probes: list[Probe]

    @field_validator("probes")
    @classmethod
    def _two(cls, v: list[Probe]) -> list[Probe]:
        if len(v) < 2:
            raise ValueError("need two probes")
        return v[:2]


class ProbeEvalOut(BaseModel):
    ownership_score: int = 0
    reasoning: str = ""
    advisory_note: str = ""

    @field_validator("ownership_score", mode="before")
    @classmethod
    def _o(cls, v: Any) -> int:
        return _to_int(v, 0, 3)


# ---------------------------------------------------------------- feedback
class OpeningStrength(BaseModel):
    quote: str = ""
    statement: str = ""


class Gap(BaseModel):
    dimension_id: str = ""
    what_happened: str = ""
    concrete_fix: str = ""
    why_it_matters: str = ""


class NextStep(BaseModel):
    option_a: str = ""
    option_b: str = ""


class FeedbackOut(BaseModel):
    opening_strength: OpeningStrength = Field(default_factory=OpeningStrength)
    highest_leverage_gap: Gap = Field(default_factory=Gap)
    next_step_choice: NextStep = Field(default_factory=NextStep)
    full_prose: str

    @field_validator("full_prose")
    @classmethod
    def _prose(cls, v: str) -> str:
        if len(v.strip()) < 30:
            raise ValueError("feedback too short")
        return v.strip()


# ---------------------------------------------------------------- API requests
class ExtractRequest(BaseModel):
    cv_text: str = Field(min_length=80, max_length=20000)


class TaskRequest(BaseModel):
    extraction: dict
    claim_id: str


class Submission(BaseModel):
    task_id: str
    answer: str = Field(min_length=1, max_length=8000)
    communication: str = Field(default="", max_length=3000)


class ScoreRequest(Submission):
    attempt: Literal[1, 2] = 1
    previous_answer: Optional[str] = Field(default=None, max_length=8000)
    previous_communication: Optional[str] = Field(default=None, max_length=3000)
    critique: Optional[dict] = None
    self_prediction: Optional[float] = Field(default=None, ge=0, le=4)


class ProbeEvalRequest(Submission):
    probes: list[dict]
    probe_answers: list[str]


class FeedbackRequest(Submission):
    attempt: Literal[1, 2] = 1
    scores: list[dict]
    self_prediction: Optional[float] = None
