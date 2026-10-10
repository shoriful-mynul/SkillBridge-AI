"""Roadmap integration and guardrail tests; no API key or network required."""
import copy

import pytest
from fastapi.testclient import TestClient

from app import pipeline, textcheck as tc
from app.main import app
from app.schemas import RoadmapOut


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.ENV_FILE", tmp_path / "missing.env")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    return TestClient(app)


def scored_revision(client, answer, communication=""):
    cv = client.get("/api/demo-cv").json()["text"]
    ex = client.post("/api/extract", json={"cv_text": cv}).json()
    task = client.post("/api/task", json={"extraction": ex, "claim_id": ex["default_claim_id"]}).json()
    body = {"task_id": task["task_id"], "answer": answer, "communication": communication}
    r = client.post("/api/score", json={**body, "attempt": 2,
        "previous_answer": "I reported accuracy on my first attempt."})
    assert r.status_code == 200, r.text
    return body, r.json()


def assert_safe(result, body):
    texts = list(pipeline._roadmap_strings({k: v for k, v in result.items() if k not in {"meta", "checks"}}))
    assert all(not tc.find_banned(t) for t in texts)
    assert not any(pipeline._ROADMAP_UNSAFE.search(t) for t in texts)
    assert sum(tc.word_count(t) for t in texts) == result["checks"]["word_count"] < 320
    quote = result["opening_strength"]["quote"]
    if quote:
        assert tc.quote_in_source(quote, pipeline.combine(body["answer"], body["communication"]))
    assert "on this task" in " ".join(texts)


def test_verified_branch_mock(client):
    body, scores = scored_revision(client,
        "I checked precision and recall against a baseline because imbalance inflated accuracy. "
        "I used a stratified split to prevent leakage and documented the threshold.",
        "Our alarm finds rare cases; checking false alarms also matters.")
    result = client.post("/api/roadmap", json=body)
    assert result.status_code == 200, result.text
    r = result.json()
    gates = {s["dimension_id"]: s["score"] for s in scores["scores"]}
    assert gates["claim_substantiation"] >= 3 and gates["technical_correctness"] >= 3
    assert r["branch"] == "verified"
    assert len(r["growth_areas"]) == 2 and 2 <= len(r["habits"]) <= 3
    assert not r["days"] and not r["gating_dimensions"]
    low = sorted(scores["scores"], key=lambda s: s["score"])[:2]
    assert [g["dimension_id"] for g in r["growth_areas"]] == [s["dimension_id"] for s in low]
    assert r["next_claim"]["claim_id"] != pipeline.STORE.get(body["task_id"])["claim"]["claim_id"]
    assert r["checks"]["opening_quote_verified"]
    assert_safe(r, body)


def test_practice_branch_mock(client):
    body, _ = scored_revision(client, "I reported precision for the recorded results on this project.")
    response = client.post("/api/roadmap", json=body)
    assert response.status_code == 200, response.text
    r = response.json()
    assert r["branch"] == "practice"
    assert [d["day"] for d in r["days"]] == list(range(1, 8))
    assert all(d["action"] and d["outcome"] for d in r["days"])
    assert r["opening_strength"] == {"quote": "", "statement": ""}
    assert not r["growth_areas"] and not r["habits"]
    assert len(r["gating_dimensions"]) == 2
    assert all(g["score"] == 1 and g["needed"] == 3 for g in r["gating_dimensions"])
    assert_safe(r, body)


@pytest.mark.parametrize("gate_scores", [(3, 2), (2, 3), (2, 2), (1, 3), (3, 3)])
def test_branch_is_decided_by_both_server_gates(client, gate_scores):
    body, _ = scored_revision(client, "I checked precision and recall against a baseline with imbalance.")
    rec = pipeline.STORE.get(body["task_id"])
    for item, value in zip(rec["scored_revision"]["scores"][:2], gate_scores):
        item["score"] = value
    # Extra fields cannot override the server's scores or branch.
    r = client.post("/api/roadmap", json={**body, "scores": [{"score": 4}], "branch": "verified"})
    assert r.status_code == 200, r.text
    assert r.json()["branch"] == ("verified" if min(gate_scores) >= 3 else "practice")
    assert_safe(r.json(), body)


def test_unscored_and_changed_revision_are_blocked(client):
    body, _ = scored_revision(client, "I checked precision and recall against a baseline with imbalance.")
    assert client.post("/api/roadmap", json={**body, "answer": "Changed revision."}).status_code == 422
    del pipeline.STORE.get(body["task_id"])["scored_revision"]
    assert client.post("/api/roadmap", json=body).status_code == 422
    assert client.post("/api/roadmap", json={**body, "task_id": "expired"}).status_code == 409


def test_quote_retry_then_verified_fallback(client, monkeypatch):
    body, _ = scored_revision(client, "I checked precision and recall against a baseline with imbalance.")
    original = pipeline.complete_json
    messages = []

    async def fabricated(system, user, **kwargs):
        out, meta = await original(system, user, **kwargs)
        if kwargs.get("purpose") == "roadmap":
            messages.append(user)
            raw = out.model_dump()
            raw["opening_strength"]["quote"] = "A fabricated sentence that never appeared."
            raw["opening_strength"]["statement"] = "You're talented and ready for hiring."
            return RoadmapOut.model_validate(raw), meta
        return out, meta

    monkeypatch.setattr(pipeline, "complete_json", fabricated)
    r = client.post("/api/roadmap", json=body)
    assert r.status_code == 200, r.text
    assert len(messages) == 2 and "REVISION NEEDED" in messages[1]
    assert r.json()["checks"]["fallback_used"]
    assert_safe(r.json(), body)


def test_capped_score_and_no_adjacent_claim(client):
    body, _ = scored_revision(client, "I used precision to check these recorded project results.")
    rec = pipeline.STORE.get(body["task_id"])
    rec["roadmap_claims"] = []
    rec["scored_revision"]["scores"][0]["capped"] = True
    r = client.post("/api/roadmap", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "quote could not be found" in data["cap_note"]
    assert "reasoning explicitly" in data["cap_note"]
    assert data["next_claim"]["claim_id"] is None and "CV" in data["next_claim"]["why"]
    assert_safe(data, body)


def test_adjacent_claim_prefers_higher_grounding(client):
    body, _ = scored_revision(client, "I used precision to check these recorded project results.")
    rec = pipeline.STORE.get(body["task_id"])
    project = copy.deepcopy(rec["roadmap_projects"][0])
    medium = {**project, "project_id": "medium-project", "task_grounding_potential": "medium"}
    high = {**project, "project_id": "high-project", "task_grounding_potential": "high"}
    rec["roadmap_projects"] = [medium, high]
    base = {**rec["claim"], "eligible": True}
    rec["roadmap_claims"] = [
        {**base, "claim_id": "medium-claim", "linked_project_id": "medium-project"},
        {**base, "claim_id": "high-claim", "linked_project_id": "high-project"},
        {**base, "claim_id": "ineligible", "eligible": False, "linked_project_id": "high-project"},
    ]
    r = client.post("/api/roadmap", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["next_claim"]["claim_id"] == "high-claim"


@pytest.mark.parametrize("bad_action", ['Use "an invented source quotation" in the revision.', "Repeated detail " * 400])
def test_embedded_quote_and_word_limit_get_checked_fallback(client, monkeypatch, bad_action):
    body, _ = scored_revision(client, "I reported precision for the recorded project results.")
    original = pipeline.complete_json
    calls = []

    async def invalid_plan(system, user, **kwargs):
        out, meta = await original(system, user, **kwargs)
        if kwargs.get("purpose") == "roadmap":
            calls.append(user)
            raw = out.model_dump()
            raw["days"][0]["action"] = bad_action
            return RoadmapOut.model_validate(raw), meta
        return out, meta

    monkeypatch.setattr(pipeline, "complete_json", invalid_plan)
    response = client.post("/api/roadmap", json=body)
    assert response.status_code == 200, response.text
    assert len(calls) == 2 and response.json()["checks"]["fallback_used"]
    assert_safe(response.json(), body)
