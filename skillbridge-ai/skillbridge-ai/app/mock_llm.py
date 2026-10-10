"""Deterministic test doubles for LLM_PROVIDER=mock.

FOR AUTOMATED TESTS AND OFFLINE CLICK-THROUGHS ONLY. These are canned
heuristics, not AI. The UI shows a red TEST MODE banner whenever this
provider is active. Never present mock output as AI output.

The doubles build their answers from the real inputs, so every quote they
return genuinely exists in the source text and passes the code-side checks.
"""
from __future__ import annotations

import re
from typing import Any

SKILL_KEYWORDS = [
    ("python", "python_fundamentals"), ("pandas", "data_wrangling"),
    ("scikit-learn", "classical_ml"), ("random forest", "classical_ml"),
    ("sql", "sql"), ("tensorflow", "deep_learning"), ("pytorch", "deep_learning"),
    ("precision", "model_evaluation"), ("git", "experiment_hygiene"),
]
TECH_TERMS = ["imbalance", "recall", "precision", "f1", "stratif", "leak", "baseline",
              "auc", "minority", "class weight", "threshold", "cross-validation"]


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _sentences(text: str) -> list[str]:
    body = re.sub(r"^(MAIN ANSWER:|COMMUNICATION ANSWER:)\s*", "", text or "", flags=re.M)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", body) if len(s.strip()) >= 12]


def _section(submission: str, name: str) -> str:
    m = re.search(name + r":\n(.*?)(?:\n\n[A-Z ]+:\n|\Z)", submission or "", flags=re.S)
    return m.group(1).strip() if m else ""


def respond(purpose: str, ctx: dict) -> Any:
    if purpose == "ping":
        return {"ok": True, "message": "mock test double ready"}
    if purpose == "extract":
        return _extract(ctx.get("cv_text", ""))
    if purpose == "task":
        return _task(ctx.get("claim", {}), ctx.get("project", {}))
    if purpose.startswith("score:"):
        return _score(purpose.split(":", 1)[1], ctx)
    if purpose == "probe_generate":
        return _probes(ctx.get("submission", ""))
    if purpose == "probe_evaluate":
        words = sum(len(a.split()) for a in ctx.get("answers", []))
        own = 3 if words >= 40 else 2 if words >= 15 else 1
        return {"ownership_score": own,
                "reasoning": "Test double: ownership estimated from answer length only.",
                "advisory_note": "Test double note: this is not an AI evaluation."}
    if purpose == "feedback":
        return _feedback(ctx.get("submission", ""), ctx.get("scores", []))
    if purpose == "roadmap":
        return _roadmap(ctx)
    raise ValueError(f"mock has no handler for purpose '{purpose}'")


def _extract(cv: str) -> dict:
    lines = _lines(cv)
    projects, title_for = [], None
    for i, ln in enumerate(lines):
        if len(ln.split()) >= 15:
            title = lines[i - 1] if i > 0 and len(lines[i - 1].split()) <= 10 else f"Project {len(projects) + 1}"
            words = len(ln.split())
            tools = [kw for kw, _ in SKILL_KEYWORDS if kw in ln.lower()]
            projects.append({
                "project_id": f"p{len(projects) + 1}", "title": title, "description_span": ln,
                "tools_named": tools, "stated_outcome": None,
                "task_grounding_potential": "high" if words >= 25 else "medium",
                "grounding_note": "Test double note.",
            })
        elif len(ln.split()) >= 3 and title_for is None:
            title_for = ln
    claims, seen = [], set()
    for kw, skill in SKILL_KEYWORDS:
        for ln in lines:
            if kw in ln.lower() and skill not in seen:
                seen.add(skill)
                linked = next((p["project_id"] for p in projects if p["description_span"] == ln), None)
                strength = "substantiated" if linked and re.search(r"\d", ln) else "contextual" if linked else "asserted"
                claims.append({"claim_id": f"c{len(claims) + 1}", "skill": skill, "raw_label": kw,
                               "strength": strength, "claimed_level": "unstated",
                               "evidence_span": ln, "linked_project_id": linked})
                break
    return {"profile": {"degree": None}, "claims": claims, "projects": projects,
            "extraction_warnings": ["Test double: heuristic extraction, not AI."]}


def _task(claim: dict, project: dict) -> dict:
    tools = project.get("tools_named") or ["your tools"]
    title = project.get("title", "your project")
    return {
        "task_prompt": (f"In your project \"{title}\" you used {tools[0]}. Suppose the outcome you are "
                        f"predicting is rare (under 10% of cases). Explain whether your reported metric "
                        f"still tells you the model is useful, what you would measure instead, and one "
                        f"change you would make to how you split the data."),
        "grounding_justification": f"Test double: references {title} and {tools[0]}.",
        "embedded_complication": "Class imbalance makes accuracy misleading.",
        "accessible_entry_point": "Notice that most cases belong to one class.",
        "communication_subtask": "In under 120 words, explain why accuracy can mislead here to a non-technical project manager.",
        "probe_seeds": ["Why that metric?", "What if the rare class shrinks further?"],
        "expected_strong_answer": "Accuracy is inflated by the majority class; report recall, precision, F1 or PR-AUC and use a stratified split.",
    }


def _score(dim: str, ctx: dict) -> dict:
    sub = ctx.get("submission", "")
    main = _section(sub, "MAIN ANSWER") or sub
    comm = _section(sub, "COMMUNICATION ANSWER")
    sents = _sentences(comm if dim == "communication" and comm else main)
    hits = sum(1 for t in TECH_TERMS if t in main.lower())
    if dim == "communication":
        score = 0 if not comm else 3 if len(comm.split()) <= 120 else 2
    elif dim == "coachability_delta":
        prev = ctx.get("previous", "")
        prev_hits = sum(1 for t in TECH_TERMS if t in prev.lower())
        score = 3 if hits > prev_hits else 1
    else:
        score = min(4, hits)
    quote = sents[0] if sents else ""
    return {"score": score, "anchor_matched": "", "confidence": "low",
            "evidence_spans": [{"quote": quote, "why_it_supports": "Test double heuristic."}] if quote else [],
            "missing_for_next_level": "Test double: name a metric suited to rare outcomes.",
            "confidence_reason": "Test double, not AI.", "anomaly_flag": None}


def _probes(sub: str) -> dict:
    sents = _sentences(sub) or ["your answer"]
    a, b = sents[0], sents[min(1, len(sents) - 1)]
    return {"probes": [
        {"probe_id": "q1", "type": "choice", "anchored_quote": a,
         "question": "Why did you choose this approach over the most obvious alternative?"},
        {"probe_id": "q2", "type": "boundary", "anchored_quote": b,
         "question": "What would break if the rare class became even rarer?"},
    ]}


def _feedback(sub: str, scores: list[dict]) -> dict:
    sents = _sentences(sub)
    quote = sents[0] if sents else ""
    low = min(scores, key=lambda s: s.get("score", 0)) if scores else {"dimension_id": "technical_correctness"}
    return {
        "opening_strength": {"quote": quote, "statement": "Test double: this line is where your answer starts doing real work."},
        "highest_leverage_gap": {"dimension_id": low.get("dimension_id", ""),
                                 "what_happened": "Test double: the approach relied on a single overall metric.",
                                 "concrete_fix": "Report recall and F1 for the rare class and use a stratified split.",
                                 "why_it_matters": "It shows whether the model finds the cases that matter."},
        "next_step_choice": {"option_a": "Revise this answer using the fix above.",
                             "option_b": "Practise computing precision and recall by hand on a small table."},
        "full_prose": ("TEST MODE - this feedback is a canned test double, not AI output. "
                       "Your answer opens with a clear statement of what you did. The one change that would move "
                       "the result most is to judge the model with a metric that respects how rare the outcome is."),
    }


def _roadmap(ctx: dict) -> dict:
    verified = ctx["branch"] == "verified"
    steps = [
        ("Choose one next-level check on this task.", "One check recorded."),
        ("Write the decision and its reason.", "Two sentences recorded."),
        ("Construct a small input for the check.", "Input and expected output saved."),
        ("Try the check and record the result.", "Actual output or untested note saved."),
        ("Compare the expected and observed output.", "One comparison recorded."),
        ("Describe a boundary case.", "One constraint recorded."),
        ("Optionally revise using that evidence.", "A decision and result in writing."),
    ]
    return {
        "branch": ctx["branch"],
        "opening_strength": {"quote": ctx["quote"] if verified else "",
            "statement": "TEST MODE: well done documenting this decision on this task; this quote supports the gating evidence." if verified else ""},
        "growth_areas": [{"dimension_id": s["dimension_id"],
            "action": s.get("missing_for_next_level") or "Repeat the check on one boundary case."}
            for s in ctx["growth"]] if verified else [],
        "habits": ["Write the decision and its reason before implementing it.",
                   "Save the check alongside its observed result."] if verified else [],
        "days": [{"day": i, "action": a, "outcome": o} for i, (a, o) in enumerate(steps, 1)] if not verified else [],
        "next_claim_reason": "This adjacent option has project grounding to explore on this task." if ctx["candidate"] else
            "Add a project, tool, decision and result to unlock another CV claim.",
        "choice": "Choose this 10-minute practice option or consolidate the same decision first.",
    }

