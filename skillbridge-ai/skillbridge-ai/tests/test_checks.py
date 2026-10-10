"""Deterministic checks: the 'code decides' half of the system."""
from app import pipeline
from app import textcheck as tc
from app.schemas import Claim, Project


# ---------------- quote verification ----------------
def test_quote_exact_case_and_whitespace():
    src = "I used a random 80/20 split.\nThe model reached 92% accuracy."
    assert tc.quote_in_source("the model   reached 92% ACCURACY", src)


def test_quote_curly_quotes_and_dashes():
    src = 'He said "it\'s fine" - then left.'
    assert tc.quote_in_source("“it’s fine” — then left", src)


def test_quote_with_ellipsis_fragments_in_order():
    src = "Cleaned the data in pandas, filled missing quiz marks with the column mean, and trained a forest."
    assert tc.quote_in_source("Cleaned the data in pandas ... trained a forest", src)
    assert not tc.quote_in_source("trained a forest ... Cleaned the data in pandas", src)


def test_quote_rejects_fabrication_and_trivial():
    src = "Built a model with pandas."
    assert not tc.quote_in_source("Built a deep transformer", src)
    assert not tc.quote_in_source("a", src)
    assert not tc.quote_in_source("", src)


# ---------------- banned words ----------------
def test_banned_words_detected_and_sanitized():
    text = "This answer lacks detail. Weak reasoning. You should have used recall."
    assert set(tc.find_banned(text)) >= {"lacks", "weak", "you should have"}
    clean = tc.sanitize(text)
    assert tc.find_banned(clean) == []
    assert clean.startswith("This answer doesn't yet show detail. Thin reasoning.")


# ---------------- grounding ----------------
def test_grounding_by_tool_or_shared_words():
    assert tc.is_grounded("In your project you used scikit-learn to ...", ["scikit-learn"], [])
    assert tc.is_grounded("Your dropout early-warning random forest reported accuracy",
                          [], ["Student Dropout Early-Warning Model", "random forest accuracy"])
    assert not tc.is_grounded("Explain overfitting in general.", ["pandas"], ["Student dropout model"])


def test_tool_match_is_word_bounded():
    assert not tc.is_grounded("Explain gradient descent", ["R"], [])


# ---------------- grounding gate ----------------
def _p(words: int, pot: str = "high") -> Project:
    return Project(project_id="p1", title="T", description_span=" ".join(["word"] * words),
                   task_grounding_potential=pot)


def test_gate_requires_detail_and_potential():
    assert pipeline.project_ok(_p(20, "high"))
    assert pipeline.project_ok(_p(15, "medium"))
    assert not pipeline.project_ok(_p(14, "high"))      # too thin, whatever the AI says
    assert not pipeline.project_ok(_p(40, "low"))


def test_eligibility_prefers_least_backed_claim_with_project():
    projects = [_p(30, "high")]
    claims = [
        Claim(claim_id="c1", skill="python_fundamentals", strength="substantiated", evidence_span="x", linked_project_id="p1"),
        Claim(claim_id="c2", skill="classical_ml", strength="asserted", evidence_span="x", linked_project_id="p1"),
        Claim(claim_id="c3", skill="sql", strength="asserted", evidence_span="x", linked_project_id=None),
    ]
    rows, default = pipeline._eligibility(claims, projects)
    assert default == "c2"
    assert [r["eligible"] for r in rows] == [True, True, False]


def test_gate_fails_when_no_project_supports_a_task():
    rows, default = pipeline._eligibility(
        [Claim(claim_id="c1", skill="python_fundamentals", evidence_span="x", linked_project_id="p1")],
        [_p(9, "medium")])
    assert default is None and not rows[0]["eligible"]


# ---------------- index, status, calibration ----------------
def test_evidence_index_renormalises_over_four_dimensions():
    assert pipeline.evidence_index({k: 4 for k in pipeline.base_dims()}) == 100
    assert pipeline.evidence_index({k: 0 for k in pipeline.base_dims()}) == 0
    s = {"claim_substantiation": 2, "technical_correctness": 2, "reasoning_transparency": 2, "communication": 3}
    # (0.30*2 + 0.25*2 + 0.20*2 + 0.15*3) / 4 / 0.90 * 100 = 54.17
    assert pipeline.evidence_index(s) == 54


def test_verification_rules():
    assert pipeline.verification_status(3, 3)["status"] == "verified"
    assert pipeline.verification_status(4, 2)["status"] == "partial"
    assert pipeline.verification_status(2, 2)["status"] == "partial"
    assert pipeline.verification_status(1, 4)["status"] == "not_yet"
    assert "1 task" in pipeline.verification_status(3, 3)["caveat"]


def test_calibration_framing_is_never_error_language():
    for pred, shown in [(3, 3.0), (4, 1.5), (0, 3.0)]:
        c = pipeline.calibration(pred, shown)
        assert tc.find_banned(c["framing"]) == []
        assert "wrong" not in c["framing"].lower()
    assert pipeline.calibration(None, 2.0) is None


def test_truncate_words_keeps_sentences():
    text = "One two three. Four five six. Seven eight nine."
    assert pipeline.truncate_words(text, 6) == "One two three. Four five six."


def test_rubric_integrity():
    r = pipeline.rubric()
    assert abs(sum(d["weight"] for d in r["dimensions"]) - 1.0) < 1e-9
    for d in r["dimensions"]:
        assert set(d["anchors"]) == {"0", "1", "2", "3", "4"}
    assert set(r["index"]["dimensions"]) <= {d["id"] for d in r["dimensions"]}
