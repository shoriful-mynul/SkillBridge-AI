from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Confidence = Literal['high', 'medium', 'low']
class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Claim(Strict):
    claim_id: str
    skill: str
    raw_label: str
    strength: Literal['asserted', 'contextual', 'substantiated']
    claimed_level: Literal['beginner', 'intermediate', 'advanced', 'unstated'] = 'unstated'
    evidence_span: str
    linked_project_id: str | None = None

class Project(Strict):
    project_id: str
    title: str
    description_span: str
    tools_named: list[str]
    stated_approach: str
    task_grounding_potential: Literal['high','medium','low']

class Extraction(Strict):
    claims: list[Claim] = Field(max_length=40)
    projects: list[Project] = Field(max_length=8)
    extraction_warnings: list[str]

class Task(Strict):
    task_id: str
    targets_claim_id: str
    grounded_in_project_id: str
    grounding_quotes: list[str] = Field(min_length=2, max_length=4)
    task_prompt: str
    communication_subtask: str
    complication: str
    issue_source: Literal['hypothetical','explicitly_described']
    accessible_entry_point: str

class Span(Strict):
    quote: str
    why_it_supports: str

class Score(Strict):
    dimension_id: str
    score: int | None = Field(default=None, ge=0, le=4)
    anchor_matched: str
    evidence_spans: list[Span]
    missing_for_next_level: str
    confidence: Confidence
    guard_applied: bool = False

class Choice(Strict):
    choice_id: str
    title: str
    instruction: str
    dimension_id: str
    target_level: int = Field(ge=0,le=4)

class Feedback(Strict):
    opening_quote: str
    strength_statement: str
    strategy_feedback: str
    next_step_choices: list[Choice] = Field(min_length=2,max_length=2)

class Probe(Strict):
    probe_id: str
    type: Literal['choice','boundary']
    anchored_quote: str
    question: str

class Probes(Strict):
    probes: list[Probe] = Field(min_length=2,max_length=2)

class ProbeAnswer(Strict):
    probe_id: str
    text: str = Field(min_length=5,max_length=2000)

class Ownership(Strict):
    ownership_score: int = Field(ge=0,le=3)
    evidence_spans: list[Span]
    reasoning: str

class Integrity(Strict):
    ownership_score: int | None = Field(default=None,ge=0,le=3)
    confidence: Confidence | None = None
    evidence_spans: list[Span] = []
    advisory_note: str = 'Ownership confidence is pending your two follow-up answers. This is not an AI-use detector.'

class Calibration(Strict):
    self_predicted: float = Field(ge=0,le=4)
    demonstrated: float
    gap: float
    framing: str

class Attempt(Strict):
    attempt: int = Field(ge=1,le=2)
    text: str
    self_predicted_score: float = Field(ge=0,le=4)
    scores: list[Score]
    feedback: Feedback
    probes: list[Probe]
    probe_answers: list[ProbeAnswer] = []
    integrity: Integrity = Field(default_factory=Integrity)
    calibration: Calibration
    task_evidence_index: float
    weighted_score: float

class Verification(Strict):
    claim_id: str
    status: Literal['verified','partial','not_yet']
    display_label: str
    assessed: bool
    caveat: str

class Delta(Strict):
    before: float
    after: float
    change: float
    label: str = 'Change in evidence on the same task; not an employability score.'

class Assessment(Strict):
    schema_version: Literal['2.0.0'] = '2.0.0'
    assessment_id: str
    role_id: str
    rubric_version: str
    created_at: str
    state: Literal['claims_ready','needs_detail','task_ready','first_review','revised_review']
    source_text: str
    claims: list[Claim]
    projects: list[Project]
    warnings: list[str] = []
    task: Task | None = None
    attempts: list[Attempt] = Field(default=[],max_length=2)
    verification: list[Verification] = []
    delta: Delta | None = None
    engine: Literal['live_gemini','synthetic_rehearsal'] = 'live_gemini'
    receipt: str = ''

class CreateRequest(Strict):
    role_id: str = 'ai-ml-intern'
    text: str = Field(min_length=40,max_length=16000)

class TaskRequest(Strict):
    assessment: Assessment
    claim_id: str

class SubmitRequest(Strict):
    assessment: Assessment
    text: str = Field(min_length=40,max_length=8000)
    self_predicted_score: float = Field(ge=0,le=4)
    chosen_next_step_id: str | None = None

class ProbeRequest(Strict):
    assessment: Assessment
    answers: list[ProbeAnswer] = Field(min_length=2,max_length=2)
