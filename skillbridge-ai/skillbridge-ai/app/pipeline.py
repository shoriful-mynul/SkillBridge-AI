"""Assessment pipeline.

The AI does four jobs: (1) read the CV into structured claims, (2) write a
task grounded in the candidate's own project, (3) score one rubric dimension
per call with quoted evidence, (4) ask and evaluate two follow-up probes.
It also writes the growth-mindset feedback.

Everything that can be a rule is done in plain Python here:
quote verification, the grounding gate, claim ranking, score caps, weights,
the evidence index, verification status, calibration, ownership confidence
and the banned-word filter.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import time
import uuid
from collections import OrderedDict
from functools import lru_cache
from contextvars import ContextVar
from typing import Any, Optional

from . import textcheck as tc
from .config import ROOT
from .llm import complete_json
from .schemas import (Claim, ExtractionOut, FeedbackOut, ProbeEvalOut, ProbeGenOut,
                      Project, ScoreOut, TaskOut, RoadmapOut)

RUBRIC_PATH = ROOT / "rubrics" / "ai-ml-intern.json"
ACTIVE_ROLE = ContextVar("assessment_role", default="ai-ml-intern")
ROLE_IDS = ("ai-ml-intern", "data-analyst-intern", "frontend-developer-intern")
PROMPT_DIR = ROOT / "prompts"

STRENGTH_ORDER = {"asserted": 0, "contextual": 1, "substantiated": 2}
POTENTIAL_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_COMM_SUBTASK = ("In under 120 words, explain the key tradeoff in this task to a "
                        "non-technical project manager.")


class SessionExpired(Exception):
    pass


class GateError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------------
# Static resources
# --------------------------------------------------------------------------
@lru_cache(maxsize=3)
def _load_rubric(role_id: str) -> dict:
    return json.loads((ROOT / "rubrics" / (role_id + ".json")).read_text(encoding="utf-8"))

def rubric() -> dict:
    return _load_rubric(ACTIVE_ROLE.get())


@lru_cache(maxsize=8)
def prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def dims() -> dict[str, dict]:
    return {d["id"]: d for d in rubric()["dimensions"]}


def base_dims() -> list[str]:
    return list(rubric()["index"]["dimensions"])


def min_project_words() -> int:
    return int(rubric().get("grounding_gate", {}).get("min_project_words", 15))


# --------------------------------------------------------------------------
# Server-side task store: hidden fields never reach the browser until the end
# --------------------------------------------------------------------------
class TaskStore:
    def __init__(self, cap: int = 500):
        self._d: "OrderedDict[str, dict]" = OrderedDict()
        self.cap = cap

    def put(self, record: dict) -> str:
        tid = uuid.uuid4().hex[:12]
        self._d[tid] = {**record, "created": time.time()}
        while len(self._d) > self.cap:
            self._d.popitem(last=False)
        return tid

    def get(self, tid: str) -> dict:
        rec = self._d.get(tid)
        if rec is None:
            raise SessionExpired(tid)
        return rec


STORE = TaskStore()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def combine(answer: str, communication: str) -> str:
    text = "MAIN ANSWER:\n" + (answer or "").strip()
    if (communication or "").strip():
        text += "\n\nCOMMUNICATION ANSWER:\n" + communication.strip()
    return text


def _fenced(label: str, text: str) -> str:
    return f"<<<{label}\n{text}\n{label}>>>"


def _boundary_re(term: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])")


def project_ok(p: Project) -> bool:
    return (p.task_grounding_potential in ("high", "medium")
            and tc.word_count(p.description_span) >= min_project_words())


def truncate_words(text: str, limit: int) -> str:
    if tc.word_count(text) <= limit:
        return text
    out, count = [], 0
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        n = tc.word_count(sentence)
        if count + n > limit:
            break
        out.append(sentence)
        count += n
    return " ".join(out) if out else " ".join(text.split()[:limit])


def evidence_index(scores: dict[str, int]) -> int:
    d = dims()
    weights = {k: d[k]["weight"] for k in base_dims()}
    total = sum(weights.values())
    return round(sum(weights[k] * scores[k] / 4 for k in weights) / total * 100)


def verification_status(claim_sub: int, tech: int) -> dict:
    rules = {r["status"]: r for r in rubric()["verification_status"]["rules"]}
    if claim_sub >= 3 and tech >= 3:
        r = rules["verified"]
    elif claim_sub >= 2 and tech >= 2:
        r = rules["partial"]
    else:
        r = rules["not_yet"]
    return {"status": r["status"], "label": r["label"],
            "caveat": r["display_caveat"].replace("{{task_count}}", "1")}


def calibration(self_prediction: Optional[float], demonstrated: float) -> Optional[dict]:
    if self_prediction is None:
        return None
    pred = max(0.0, min(4.0, float(self_prediction)))
    gap = round(pred - demonstrated, 1)
    if abs(gap) <= 0.5:
        framing = ("You rated yourself close to what this attempt showed. Accurate "
                   "self-assessment is a skill in its own right.")
    elif gap > 0.5:
        framing = ("You expected a little more than this attempt showed. That gap is useful: "
                   "it points at exactly what to practise next.")
    else:
        framing = ("This attempt showed more than you expected. Your skills may be ahead "
                   "of your confidence.")
    return {"self_predicted": pred, "demonstrated": round(demonstrated, 2),
            "gap": gap, "framing": framing}


# --------------------------------------------------------------------------
# 1. Claim extraction
# --------------------------------------------------------------------------
def _eligibility(claims: list[Claim], projects: list[Project]) -> tuple[list[dict], Optional[str]]:
    by_id = {p.project_id: p for p in projects}
    rows, ranked = [], []
    for i, c in enumerate(claims):
        p = by_id.get(c.linked_project_id or "")
        if p is None:
            ok, reason = False, "Not tied to any project in your CV, so a task only you could answer can't be built from it."
        elif not project_ok(p):
            ok, reason = False, "The linked project is described too briefly to build a fair, specific task."
        else:
            ok, reason = True, ""
        row = {**c.model_dump(), "eligible": ok, "ineligible_reason": reason}
        rows.append(row)
        if ok:
            ranked.append((POTENTIAL_ORDER[p.task_grounding_potential],
                           STRENGTH_ORDER[c.strength],
                           0 if c.skill != "other" else 1, i, c.claim_id))
    ranked.sort()
    return rows, (ranked[0][-1] if ranked else None)


async def extract_claims(cv_text: str) -> dict:
    r = rubric()
    taxonomy = r["skill_taxonomy"]
    user = (f"Role: {r['role_title']}\n"
            f"Role skill taxonomy ids: {', '.join(taxonomy)}\n\n"
            f"CV TEXT:\n{_fenced('CV', cv_text)}")
    out, meta = await complete_json(prompt("01_extract_claims.md"), user, purpose="extract",
                                    context={"cv_text": cv_text, "taxonomy": taxonomy},
                                    validate=ExtractionOut.model_validate)

    removed: list[dict] = []
    projects: list[Project] = []
    seen_p: set[str] = set()
    for i, p in enumerate(out.projects, start=1):
        if not p.project_id or p.project_id in seen_p:
            p.project_id = f"p{i}"
        if not tc.quote_in_source(p.description_span, cv_text):
            removed.append({"type": "project", "label": p.title or p.project_id, "span": p.description_span})
            continue
        seen_p.add(p.project_id)
        projects.append(p)

    claims: list[Claim] = []
    seen_c: set[str] = set()
    for i, c in enumerate(out.claims, start=1):
        if not c.claim_id or c.claim_id in seen_c:
            c.claim_id = f"c{i}"
        if not tc.quote_in_source(c.evidence_span, cv_text):
            removed.append({"type": "claim", "label": c.raw_label or c.skill, "span": c.evidence_span})
            continue
        if c.skill not in taxonomy:
            c.skill = "other"
        seen_c.add(c.claim_id)
        claims.append(c)

    # Code-side linking: if the model left a claim unlinked (or linked to a
    # removed project) but a project names that skill, link it.
    valid_ids = {p.project_id for p in projects}
    for c in claims:
        if c.linked_project_id not in valid_ids:
            c.linked_project_id = None
        label = tc.normalize(c.raw_label)
        if c.linked_project_id is None and len(label) >= 2:
            pattern = _boundary_re(label)
            for p in projects:
                hay = tc.normalize(" ".join([p.title, p.description_span, " ".join(p.tools_named)]))
                if pattern.search(hay):
                    c.linked_project_id = p.project_id
                    break

    claim_rows, default_id = _eligibility(claims, projects)
    n = len(claims)
    counts = {k: sum(1 for c in claims if c.strength == k) for k in STRENGTH_ORDER}
    stats = {
        "claims": n,
        "by_strength": counts,
        "asserted_only_rate": round(counts["asserted"] / n, 3) if n else None,
        "evidence_strength_index": round((counts["substantiated"] + 0.5 * counts["contextual"]) / n, 3) if n else None,
    }
    gate_passed = default_id is not None
    return {
        "role_id": ACTIVE_ROLE.get(),
        "profile": out.profile.model_dump(),
        "claims": claim_rows,
        "projects": [{**p.model_dump(), "word_count": tc.word_count(p.description_span),
                      "can_ground_task": project_ok(p)} for p in projects],
        "warnings": [tc.sanitize(w) for w in out.extraction_warnings][:6],
        "quote_check": {"removed_count": len(removed), "removed": removed},
        "stats": stats,
        "default_claim_id": default_id,
        "gate": {
            "passed": gate_passed,
            "message": "" if gate_passed else (
                "We can't build a fair task from this CV yet. Every claim is either not tied to a "
                "project, or the project is described in a single line. Add one project with what "
                "you built, the tools you used and one decision you made, then try again."),
        },
        "meta": meta.to_dict(),
    }


# --------------------------------------------------------------------------
# 2. Grounded task generation
# --------------------------------------------------------------------------
async def generate_task(extraction: dict, claim_id: str) -> dict:
    try:
        claims = [Claim.model_validate(c) for c in extraction.get("claims", [])]
        projects = [Project.model_validate(p) for p in extraction.get("projects", [])]
    except ValueError:
        raise GateError("The claim list is malformed.", "Run 'Read my CV' again.")
    claim = next((c for c in claims if c.claim_id == claim_id), None)
    if claim is None:
        raise GateError("That claim was not found.", "Pick a claim from the list.")
    project = next((p for p in projects if p.project_id == claim.linked_project_id), None)
    # Re-check the gate server-side: never trust the browser's copy.
    if project is None or not project_ok(project):
        raise GateError("A fair task can't be built from this claim.",
                        "Choose a claim tied to a project with more detail.")

    base_user = (
        f"Role: {rubric()['role_title']}\n\n"
        f"TARGET CLAIM:\n{json.dumps(claim.model_dump(), ensure_ascii=False)}\n\n"
        f"THEIR PROJECT (ground the task in this):\n{json.dumps(project.model_dump(), ensure_ascii=False)}\n\n"
        f"PROFILE:\n{json.dumps(extraction.get('profile', {}), ensure_ascii=False)}"
    )
    project_texts = [project.title, project.description_span]
    user, grounded, task, meta = base_user, False, None, None
    for attempt in (1, 2):
        task, meta = await complete_json(prompt("02_generate_task.md"), user, purpose="task",
                                         context={"claim": claim.model_dump(), "project": project.model_dump()},
                                         validate=TaskOut.model_validate)
        grounded = tc.is_grounded(task.task_prompt, project.tools_named, project_texts)
        if grounded:
            break
        user = base_user + (
            f"\n\nREVISION NEEDED: your previous task did not reference the candidate's own work. "
            f"Rewrite it so it explicitly names their project \"{project.title}\" and at least one of "
            f"these tools: {', '.join(project.tools_named) or 'the tools in their description'}.")

    comm = task.communication_subtask.strip() or DEFAULT_COMM_SUBTASK
    record = {
        "role_id": ACTIVE_ROLE.get(),
        "task_prompt": task.task_prompt,
        "communication_subtask": comm,
        "embedded_complication": task.embedded_complication,
        "accessible_entry_point": task.accessible_entry_point,
        "expected_strong_answer": task.expected_strong_answer,
        "probe_seeds": task.probe_seeds[:4],
        "claim": claim.model_dump(),
        "project": project.model_dump(),
        "roadmap_claims": copy.deepcopy([c for c in extraction.get("claims", [])
                                        if c.get("eligible") is True]),
        "roadmap_projects": [p.model_dump() for p in projects],
    }
    task_id = STORE.put(record)
    return {
        "task_id": task_id,
        "task_prompt": task.task_prompt,
        "communication_subtask": comm,
        "grounding_justification": task.grounding_justification,
        "grounding_check": "passed" if grounded else "weak",
        "claim": claim.model_dump(),
        "project": {"project_id": project.project_id, "title": project.title,
                    "tools_named": project.tools_named},
        "meta": meta.to_dict(),
    }


def reveal(task_id: str) -> dict:
    """What the task was testing. Shown only after the final score."""
    rec = STORE.get(task_id)
    return {"embedded_complication": rec["embedded_complication"],
            "accessible_entry_point": rec["accessible_entry_point"],
            "expected_strong_answer": rec["expected_strong_answer"]}


# --------------------------------------------------------------------------
# 3. Adaptive probes
# --------------------------------------------------------------------------
async def generate_probes(task_id: str, answer: str, communication: str) -> dict:
    rec = STORE.get(task_id)
    submission = combine(answer, communication)
    base_user = (f"MODE: generate\n\nTASK GIVEN:\n{rec['task_prompt']}\n\n"
                 f"PROBE SEEDS (ideas only; adapt them to what they actually wrote):\n"
                 f"{json.dumps(rec['probe_seeds'], ensure_ascii=False)}\n\n"
                 f"THEIR SUBMISSION:\n{_fenced('SUBMISSION', submission)}")
    user, out, meta = base_user, None, None
    for attempt in (1, 2):
        out, meta = await complete_json(prompt("05_probe.md"), user, purpose="probe_generate",
                                        context={"submission": submission},
                                        validate=ProbeGenOut.model_validate)
        if all(tc.quote_in_source(p.anchored_quote, submission) for p in out.probes):
            break
        user = base_user + ("\n\nREVISION NEEDED: each anchored_quote must be copied verbatim "
                            "from THEIR SUBMISSION.")
    probes = []
    for i, p in enumerate(out.probes[:2]):
        probes.append({
            "probe_id": f"q{i + 1}",
            "type": "choice" if i == 0 else "boundary",
            "anchored_quote": p.anchored_quote if tc.quote_in_source(p.anchored_quote, submission) else "",
            "question": p.question,
        })
    return {"probes": probes, "meta": meta.to_dict()}


async def evaluate_probes(task_id: str, answer: str, communication: str,
                          probes: list[dict], probe_answers: list[str]) -> dict:
    STORE.get(task_id)
    submission = combine(answer, communication)
    answers = [(a or "").strip() for a in probe_answers][:2]
    innocent = (" Short or general answers here often come from nerves, time pressure or working "
                "in a second language. Treat this as a prompt to talk through your reasoning, "
                "not as a judgement.")
    if not any(answers):
        return {"ownership_score": 0, "integrity_confidence": "low",
                "reasoning": "No answers were given to the follow-up questions.",
                "advisory_note": "The follow-up questions were left blank." + innocent,
                "meta": None}
    qa = []
    for i, p in enumerate(probes[:2]):
        qa.append(f"Q{i + 1} (about: \"{p.get('anchored_quote', '')}\"): {p.get('question', '')}\n"
                  f"A{i + 1}: {answers[i] if i < len(answers) else ''}")
    user = (f"MODE: evaluate\n\nTHEIR SUBMISSION:\n{_fenced('SUBMISSION', submission)}\n\n"
            f"QUESTIONS AND THEIR ANSWERS:\n" + "\n\n".join(qa))
    out, meta = await complete_json(prompt("05_probe.md"), user, purpose="probe_evaluate",
                                    context={"answers": answers, "submission": submission},
                                    validate=ProbeEvalOut.model_validate)
    own = out.ownership_score
    note = tc.sanitize(out.advisory_note.strip())
    if any(w in note.lower() for w in ("cheat", "plagiar", "ai-generated", "ai generated", "copied")):
        note = "Your answers were reviewed for how well they explain your own submission."
    if own <= 1 and not any(w in note.lower() for w in ("nerv", "time", "language", "pressure", "vocabulary")):
        note = (note + innocent).strip()
    return {"ownership_score": own,
            "integrity_confidence": {3: "high", 2: "medium"}.get(own, "low"),
            "reasoning": tc.sanitize(out.reasoning),
            "advisory_note": note,
            "meta": meta.to_dict()}


# --------------------------------------------------------------------------
# 4. Single-dimension scoring
# --------------------------------------------------------------------------
async def _score_dimension(rec: dict, dim_id: str, submission: str, attempt: int,
                           previous: Optional[str], critique: Optional[dict],
                           sem: asyncio.Semaphore) -> dict:
    d = dims()[dim_id]
    if dim_id == "communication":
        focus = "Score primarily the COMMUNICATION ANSWER section."
    elif dim_id == "coachability_delta":
        focus = ("Compare ATTEMPT 1 with ATTEMPT 2 in light of the CRITIQUE. "
                 "Quote ONLY from ATTEMPT 2 (the candidate submission).")
    else:
        focus = ("Score primarily the MAIN ANSWER section; the communication answer may add "
                 "supporting reasoning.")
    parts = [
        f"DIMENSION: {d['label']} (id: {dim_id})",
        f"QUESTION: {d['question']}",
        f"ANCHORS (0-4):\n{json.dumps(d['anchors'], indent=1, ensure_ascii=False)}",
        f"FOCUS: {focus}",
        f"TASK GIVEN TO THE CANDIDATE:\n{rec['task_prompt']}",
        f"COMMUNICATION SUB-TASK:\n{rec['communication_subtask']}",
        f"EMBEDDED COMPLICATION (scorer reference only):\n{rec['embedded_complication']}",
        f"REFERENCE STRONG ANSWER (scorer reference only; do not require its wording):\n{rec['expected_strong_answer']}",
    ]
    if dim_id == "coachability_delta":
        parts.append(f"ATTEMPT 1:\n{_fenced('ATTEMPT1', previous or '')}")
        parts.append(f"CRITIQUE GIVEN AFTER ATTEMPT 1:\n{json.dumps(critique or {}, ensure_ascii=False)}")
        parts.append(f"ATTEMPT 2 (the candidate submission):\n{_fenced('SUBMISSION', submission)}")
    else:
        parts.append(f"CANDIDATE SUBMISSION:\n{_fenced('SUBMISSION', submission)}")
    user = "\n\n".join(parts)

    async with sem:
        out, meta = await complete_json(prompt("03_score_evidence.md"), user, purpose=f"score:{dim_id}",
                                        context={"dimension": dim_id, "submission": submission,
                                                 "attempt": attempt, "previous": previous or ""},
                                        validate=ScoreOut.model_validate)

    valid = [e for e in out.evidence_spans if tc.quote_in_source(e.quote, submission)]
    score, capped = out.score, False
    if score > 1 and not valid:
        score, capped = 1, True
    return {
        "dimension_id": dim_id,
        "label": d["label"],
        "weight": d["weight"],
        "score": score,
        "model_score": out.score,
        "capped": capped,
        "anchor": d["anchors"][str(score)],
        "evidence_spans": [{"quote": e.quote, "why_it_supports": tc.sanitize(e.why_it_supports)} for e in valid],
        "quotes_removed": len(out.evidence_spans) - len(valid),
        "missing_for_next_level": tc.sanitize(out.missing_for_next_level) if score < 4 else "",
        "confidence": out.confidence,
        "confidence_reason": tc.sanitize(out.confidence_reason),
        "anomaly_flag": out.anomaly_flag,
        "meta": meta.to_dict(),
    }


async def score_attempt(task_id: str, attempt: int, answer: str, communication: str,
                        previous_answer: Optional[str], previous_communication: Optional[str],
                        critique: Optional[dict], self_prediction: Optional[float]) -> dict:
    rec = STORE.get(task_id)
    submission = combine(answer, communication)
    previous = None
    dim_ids = base_dims()
    if attempt == 2:
        if not (previous_answer or "").strip():
            raise GateError("A revision needs the first attempt for comparison.", "Start the revision again.")
        previous = combine(previous_answer or "", previous_communication or "")
        dim_ids = dim_ids + ["coachability_delta"]

    sem = asyncio.Semaphore(4)
    results = await asyncio.gather(*[
        _score_dimension(rec, d, submission, attempt, previous, critique, sem) for d in dim_ids
    ])
    by = {r["dimension_id"]: r for r in results}
    base_scores = {k: by[k]["score"] for k in base_dims()}
    demonstrated = sum(base_scores.values()) / len(base_scores)
    payload = {
        "attempt": attempt,
        "scores": results,
        "evidence_index": evidence_index(base_scores),
        "verification": verification_status(base_scores["claim_substantiation"],
                                            base_scores["technical_correctness"]),
        "demonstrated_mean": round(demonstrated, 2),
        "calibration": calibration(self_prediction, demonstrated) if attempt == 1 else None,
        "models_used": sorted({r["meta"]["model"] for r in results}),
    }
    if attempt == 2:
        payload["reveal"] = reveal(task_id)
        rec["scored_revision"] = {"submission": submission, "scores": copy.deepcopy(results)}
    return payload


# --------------------------------------------------------------------------
# 5. Growth-mindset feedback
# --------------------------------------------------------------------------
async def write_feedback(task_id: str, attempt: int, answer: str, communication: str,
                         scores: list[dict], self_prediction: Optional[float]) -> dict:
    rec = STORE.get(task_id)
    submission = combine(answer, communication)
    summary = [{"dimension_id": s.get("dimension_id"), "label": s.get("label"),
                "score": s.get("score"), "anchor": s.get("anchor"),
                "evidence": [e.get("quote") for e in s.get("evidence_spans", [])],
                "missing_for_next_level": s.get("missing_for_next_level", "")} for s in scores]
    base_user = (f"TASK:\n{rec['task_prompt']}\n\n"
                 f"RUBRIC SCORES (each from a separate scoring call):\n{json.dumps(summary, ensure_ascii=False)}\n\n"
                 f"SELF-PREDICTION made before scoring (0-4): {self_prediction if self_prediction is not None else 'not given'}\n\n"
                 f"ATTEMPT: {attempt}{' (a revision after earlier feedback)' if attempt == 2 else ''}\n\n"
                 f"CANDIDATE SUBMISSION:\n{_fenced('SUBMISSION', submission)}")
    user, out, meta = base_user, None, None
    for i in (1, 2):
        out, meta = await complete_json(prompt("04_feedback.md"), user, purpose="feedback",
                                        context={"submission": submission, "scores": summary},
                                        validate=FeedbackOut.model_validate)
        problems = []
        if tc.find_banned(out.full_prose):
            problems.append(f"remove these words: {', '.join(tc.find_banned(out.full_prose))}")
        if tc.word_count(out.full_prose) > 180:
            problems.append("full_prose must be under 180 words")
        if not tc.quote_in_source(out.opening_strength.quote, submission):
            problems.append("opening_strength.quote must be copied verbatim from the submission")
        if not problems:
            break
        user = base_user + "\n\nREVISION NEEDED: " + "; ".join(problems) + "."

    quote_ok = tc.quote_in_source(out.opening_strength.quote, submission)
    quote = out.opening_strength.quote
    if not quote_ok:
        best = sorted((s for s in scores if s.get("evidence_spans")), key=lambda s: -int(s.get("score", 0)))
        quote = best[0]["evidence_spans"][0]["quote"] if best else ""
    prose = truncate_words(tc.sanitize(out.full_prose), 180)
    return {
        "opening_strength": {"quote": quote, "statement": tc.sanitize(out.opening_strength.statement)},
        "highest_leverage_gap": {k: tc.sanitize(v) for k, v in out.highest_leverage_gap.model_dump().items()},
        "next_step_choice": {k: tc.sanitize(v) for k, v in out.next_step_choice.model_dump().items()},
        "full_prose": prose,
        "checks": {"opening_quote_verified": bool(quote) and tc.quote_in_source(quote, submission),
                   "banned_words_present": bool(tc.find_banned(prose)),
                   "word_count": tc.word_count(prose)},
        "meta": meta.to_dict(),
    }



# --------------------------------------------------------------------------
# 6. Revision roadmap: branch and source facts are code-owned.
# --------------------------------------------------------------------------
_ROADMAP_UNSAFE = re.compile(
    r"\b(employ\w*|hire\w*|hiring|job[ -]?ready\w*|certif\w*|talented|gifted|"
    r"smart|genius|naturally|ranked|ranking)\b|job[ -]?readiness|ready for (work|a job)|"
    r"qualified for|better than|other (people|students|candidates)|"
    r"you (?:are|[’\']re) (?:brilliant|intelligent|capable|a natural)", re.I)


def _roadmap_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in {"dimension_id", "claim_id", "branch"}:
                yield from _roadmap_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _roadmap_strings(item)


def _roadmap_clean(value):
    if isinstance(value, str):
        return tc.sanitize(value)
    if isinstance(value, dict):
        return {k: _roadmap_clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_roadmap_clean(v) for v in value]
    return value


def _roadmap_safe_quote(scores, submission):
    for score in scores:
        for evidence in score.get("evidence_spans", []):
            quote = evidence.get("quote", "")
            # A short, contiguous excerpt stays verifiable and leaves room for the plan.
            quote = " ".join(quote.split()[:18])
            if (tc.quote_in_source(quote, submission) and not tc.find_banned(quote)
                    and not _ROADMAP_UNSAFE.search(quote)):
                return quote
    return ""


def _roadmap_fallback(branch, growth, gates, quote, candidate):
    target = gates[0] if gates else growth[0]
    evidence = truncate_words(tc.sanitize(target.get("missing_for_next_level", "")), 18)
    evidence = evidence if evidence and not _ROADMAP_UNSAFE.search(evidence) else "a written decision, check and result"
    return RoadmapOut.model_validate({
        "branch": branch,
        "opening_strength": {"quote": quote if branch == "verified" else "",
            "statement": "Well done documenting this decision on this task; the quoted reasoning supports the gating evidence." if branch == "verified" else ""},
        "growth_areas": [{"dimension_id": s["dimension_id"],
            "action": truncate_words(tc.sanitize(s.get("missing_for_next_level", "")), 18) or
                      "Repeat this documented check on one boundary case."} for s in growth] if branch == "verified" else [],
        "habits": ["Record the decision and its reason before implementing it.",
                   "Keep a reproducible check beside each reported result."] if branch == "verified" else [],
        "days": [{"day": i, "action": action, "outcome": outcome} for i, (action, outcome) in enumerate([
            ("Choose one next-level check on this task.", evidence),
            ("Write the decision and its reason.", "Two explanatory sentences."),
            ("Construct one small input for that check.", "Saved input and expected output."),
            ("Try the check; record what actually happens.", "Observed output or an explicit untested note."),
            ("Compare expected and observed results.", "One discrepancy or matching result documented."),
            ("Explain one constraint on that result.", "A written boundary case."),
            ("Optionally revise with the recorded evidence.", "A submission quoting the decision and check.")], 1)] if branch == "practice" else [],
        "next_claim_reason": "This adjacent option has project grounding to explore on this task." if candidate else
            "Add a project, tool, decision and observable result to unlock another CV claim.",
        "choice": "Choose this roadmap in 10-minute sessions, or consolidate the same decision first.",
    })


async def write_roadmap(task_id: str, answer: str, communication: str) -> dict:
    rec = STORE.get(task_id)
    submission = combine(answer, communication)
    scored = rec.get("scored_revision")
    if not scored or scored["submission"] != submission:
        raise GateError("Score this revision before requesting its roadmap.", "Use the same scored revision.")
    scores = scored["scores"]
    by = {s["dimension_id"]: s for s in scores}
    gating = [by[k] for k in ("claim_substantiation", "technical_correctness")]
    gates = [s for s in gating if s["score"] < 3]
    branch = "practice" if gates else "verified"
    growth = sorted(scores, key=lambda s: s["score"])[:2]
    projects = {p["project_id"]: p for p in rec.get("roadmap_projects", [])}
    candidates = [c for c in rec.get("roadmap_claims", [])
                  if c.get("eligible") is True and c.get("claim_id") != rec["claim"]["claim_id"]
                  and c.get("linked_project_id") in projects
                  and project_ok(Project.model_validate(projects[c["linked_project_id"]]))]
    candidates.sort(key=lambda c: (POTENTIAL_ORDER.get(projects[c["linked_project_id"]].get(
        "task_grounding_potential"), 3), STRENGTH_ORDER.get(c.get("strength"), 0)))
    candidate = candidates[0] if candidates else None
    quote = _roadmap_safe_quote(gating, submission)
    if branch == "verified" and not quote:
        raise GateError("No safe source quote is available for this roadmap.", "Keep the scored report and review the evidence spans.")
    context = {"branch": branch, "submission": submission, "growth": growth,
               "gates": gates, "quote": quote, "candidate": candidate}
    base_user = (f"TASK:\n{rec['task_prompt']}\n\nCODE-DECIDED CONTEXT:\n"
                 f"{json.dumps({k: v for k, v in context.items() if k != 'submission'}, ensure_ascii=False)}\n\n"
                 f"REVISION:\n{_fenced('SUBMISSION', submission)}")
    user, meta, fallback = base_user, None, False

    def assemble(out):
        data = _roadmap_clean(out.model_dump())
        data["branch"] = branch
        if branch == "verified":
            data["growth_areas"] = [{"dimension_id": s["dimension_id"], "label": tc.sanitize(s["label"]),
                "action": item["action"], "next_level_evidence": tc.sanitize(s["missing_for_next_level"])}
                for s, item in zip(growth, data["growth_areas"])]
        data["gating_dimensions"] = [{"dimension_id": s["dimension_id"], "score": s["score"], "needed": 3,
            "explanation": f"{tc.sanitize(s['label'])} is at {s['score']}; Evidenced needs 3."} for s in gates]
        data["what_would_flip"] = ({"dimension_id": gates[0]["dimension_id"],
            "evidence": tc.sanitize(gates[0]["missing_for_next_level"]),
            "framing": "This is the next-level evidence to try on this task; reaching 3 in both gates needs rescoring."} if gates else None)
        data["next_claim"] = {"claim_id": candidate["claim_id"] if candidate else None,
            "label": tc.sanitize(candidate.get("raw_label") or candidate["skill"]) if candidate else "Add CV project evidence",
            "why": data.pop("next_claim_reason")}
        data["cap_note"] = ("The scorer's quote could not be found in your answer, so the score was capped. Writing your reasoning explicitly makes it available to check on this task."
            if any(s.get("capped") for s in scores) else "")
        data["caveat"] = "Options for evidence on this task only; completion needs a new assessment, not an automatic status change."
        return data

    def problems(out, data):
        issues = []
        if out.branch != branch:
            issues.append("use the code-decided branch")
        if branch == "verified":
            if [g.dimension_id for g in out.growth_areas] != [s["dimension_id"] for s in growth]:
                issues.append("use exactly the two supplied growth dimensions in order")
            if not 2 <= len(out.habits) <= 3 or out.days:
                issues.append("verified needs 2-3 habits and no days")
            if not tc.quote_in_source(data["opening_strength"]["quote"], submission):
                issues.append("copy the opening quote verbatim from the revision")
            if not any(tc.quote_in_source(data["opening_strength"]["quote"], e.get("quote", ""))
                       for s in gating for e in s.get("evidence_spans", [])):
                issues.append("quote a line that supports a gating score")
        elif out.opening_strength.quote or out.opening_strength.statement or out.growth_areas or out.habits:
            issues.append("practice needs no congratulation, quote, growth list or habits")
        elif [d.day for d in out.days] != list(range(1, 8)):
            issues.append("supply exactly days 1-7")
        texts = list(_roadmap_strings(data))
        for text in texts:
            for embedded_quote in re.findall(r'["“]([^"”]+)["”]', text):
                if not tc.quote_in_source(embedded_quote, submission):
                    issues.append("remove any embedded quotation not found in the revision")
        if any(tc.find_banned(t) or _ROADMAP_UNSAFE.search(t) for t in texts):
            issues.append("remove banned, trait, employment or comparison language")
        if sum(tc.word_count(t) for t in texts) >= 320:
            issues.append("all roadmap prose including source facts must be under 320 words")
        return issues

    for _ in (1, 2):
        out, meta = await complete_json(prompt("06_roadmap.md"), user, purpose="roadmap",
                                       context=context, validate=RoadmapOut.model_validate)
        data = assemble(out)
        issues = problems(out, data)
        if not issues:
            break
        user = base_user + "\n\nREVISION NEEDED: " + "; ".join(issues) + "."
    if issues:
        fallback = True
        out = _roadmap_fallback(branch, growth, gates, quote, candidate)
        data = assemble(out)
        # Source rubric explanations can be long. Keep a literal prefix, rather than inventing evidence.
        for item in data["growth_areas"]:
            item["next_level_evidence"] = truncate_words(item["next_level_evidence"], 18)
        if data["what_would_flip"]:
            data["what_would_flip"]["evidence"] = truncate_words(data["what_would_flip"]["evidence"], 20)
        if problems(out, data):
            raise GateError("The roadmap could not pass its source and language checks.", "Your scored report is preserved; retry the roadmap separately.")
    texts = list(_roadmap_strings(data))
    assert not any(tc.find_banned(t) for t in texts)
    data["checks"] = {"banned_words_present": False, "word_count": sum(tc.word_count(t) for t in texts),
        "opening_quote_verified": bool(data["opening_strength"]["quote"]) and tc.quote_in_source(data["opening_strength"]["quote"], submission),
        "fallback_used": fallback}
    data["meta"] = meta.to_dict()
    return data
