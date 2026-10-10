"""End-to-end API flow with the mock provider (no network, no key)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

ANSWER = ("Accuracy is misleading because only 7% of students dropped out, so predicting that nobody "
          "drops out already scores 93%. I would report recall and F1 for the dropout class.")
COMM = "Think of a smoke alarm that never rings: right most days, useless when it matters."


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    return TestClient(app)


def test_health_and_index(client):
    h = client.get("/api/health").json()
    assert h["test_mode"] is True and h["role"] == "AI/ML Intern"
    page = client.get("/")
    assert page.status_code == 200 and "SkillBridge AI" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_full_flow(client):
    cv = client.get("/api/demo-cv").json()["text"]
    ex = client.post("/api/extract", json={"cv_text": cv}).json()
    assert ex["gate"]["passed"] and ex["default_claim_id"]
    for c in ex["claims"]:
        assert c["evidence_span"] in cv  # every surviving quote is real

    t = client.post("/api/task", json={"extraction": ex, "claim_id": ex["default_claim_id"]}).json()
    for hidden in ("embedded_complication", "expected_strong_answer", "probe_seeds", "accessible_entry_point"):
        assert hidden not in t, f"{hidden} leaked to the browser"
    assert t["grounding_check"] == "passed"

    base = {"task_id": t["task_id"], "answer": ANSWER, "communication": COMM}
    probes = client.post("/api/probes", json=base).json()["probes"]
    assert [p["type"] for p in probes] == ["choice", "boundary"]

    s1 = client.post("/api/score", json={**base, "attempt": 1, "self_prediction": 3}).json()
    assert [s["dimension_id"] for s in s1["scores"]] == [
        "claim_substantiation", "technical_correctness", "reasoning_transparency", "communication"]
    assert 0 <= s1["evidence_index"] <= 100 and s1["calibration"]["self_predicted"] == 3
    assert "reveal" not in s1

    own = client.post("/api/probes/evaluate", json={**base, "probes": probes,
                                                    "probe_answers": ["Because recall matters more here.", ""]}).json()
    assert own["integrity_confidence"] in {"high", "medium", "low"}

    fb = client.post("/api/feedback", json={**base, "attempt": 1, "scores": s1["scores"], "self_prediction": 3}).json()
    assert fb["checks"]["banned_words_present"] is False and fb["checks"]["word_count"] <= 180

    revised = ANSWER + " I would also use a stratified split and class weights, and check precision."
    s2 = client.post("/api/score", json={"task_id": t["task_id"], "attempt": 2, "answer": revised,
                                         "communication": COMM, "previous_answer": ANSWER,
                                         "previous_communication": COMM,
                                         "critique": fb["highest_leverage_gap"]}).json()
    assert s2["scores"][-1]["dimension_id"] == "coachability_delta"
    assert s2["evidence_index"] >= s1["evidence_index"]
    assert s2["reveal"]["embedded_complication"]


def test_blank_probe_answers_need_no_ai_call(client):
    cv = client.get("/api/demo-cv").json()["text"]
    ex = client.post("/api/extract", json={"cv_text": cv}).json()
    t = client.post("/api/task", json={"extraction": ex, "claim_id": ex["default_claim_id"]}).json()
    r = client.post("/api/probes/evaluate", json={"task_id": t["task_id"], "answer": ANSWER,
                                                  "probes": [], "probe_answers": ["", ""]}).json()
    assert r["ownership_score"] == 0 and "nerves" in r["advisory_note"]


def test_gate_blocks_thin_cv(client):
    thin = ("Skills: Python, TensorFlow, PyTorch, Docker, Kubernetes, AWS.\n"
            "Projects:\nChatbot\nBuilt an AI chatbot using LLMs.\nFace Recognition\nCV model with high accuracy.")
    ex = client.post("/api/extract", json={"cv_text": thin}).json()
    assert ex["gate"]["passed"] is False and ex["default_claim_id"] is None
    r = client.post("/api/task", json={"extraction": ex, "claim_id": "c1"})
    assert r.status_code == 422


def test_errors_are_friendly(client):
    assert client.post("/api/probes", json={"task_id": "missing", "answer": "x"}).status_code == 409
    r = client.post("/api/extract", json={"cv_text": "short"}).json()
    assert r["error"]["kind"] == "invalid_input" and "too short" in r["error"]["message"]
    r = client.post("/api/score", json={"task_id": "x", "attempt": 1, "answer": "a", "self_prediction": 9})
    assert r.status_code == 422


def test_no_key_message(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    c = TestClient(app)
    assert c.get("/api/health").json()["has_key"] is False
    r = c.post("/api/check-connection")
    assert r.status_code == 503 and r.json()["error"]["kind"] == "no_key"



def test_role_rubrics_and_request_isolation(client):
    roles = client.get("/api/roles").json()["roles"]
    assert len(roles) == 3
    assert len({r["title"] for r in roles}) == 3
    cv = client.get("/api/demo-cv").json()["text"]
    for rid in ("data-analyst-intern", "frontend-developer-intern", "ai-ml-intern"):
        ex = client.post("/api/extract", json={"cv_text": cv, "role_id": rid}).json()
        assert ex["role_id"] == rid
    assert client.get("/api/health").json()["role"] == "AI/ML Intern"
    assert client.post("/api/extract", json={"cv_text": cv, "role_id": "unknown"}).status_code == 422


def test_task_preserves_role_after_request_context_ends(client):
    from app import pipeline
    cv = client.get("/api/demo-cv").json()["text"]
    ex = client.post("/api/extract", json={"cv_text": cv}).json()
    ex["role_id"] = "data-analyst-intern"
    task = client.post("/api/task", json={"extraction": ex, "claim_id": ex["default_claim_id"]}).json()
    assert pipeline.STORE.get(task["task_id"])["role_id"] == "data-analyst-intern"


def test_pdf_import_text_and_bad_files(client):
    import base64, io
    text = "Project: Python data analysis using pandas and SQL. I cleaned sales data, validated joins and documented missing values."
    stream = ("BT /F1 12 Tf 40 700 Td (" + text + ") Tj ET").encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    out = io.BytesIO(); out.write(b"%PDF-1.4\n"); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell()); out.write(str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    xref = out.tell(); out.write(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]: out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    r = client.post("/api/import-pdf", json={"file_base64": base64.b64encode(out.getvalue()).decode()})
    assert r.status_code == 200 and "Python" in r.json()["text"]
    assert client.post("/api/import-pdf", json={"file_base64": "invalid"}).status_code == 422
    assert client.post("/api/import-pdf", json={"file_base64": "x" * 7_000_001}).status_code == 422
