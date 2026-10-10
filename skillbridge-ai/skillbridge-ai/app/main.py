"""FastAPI app. Serves the frontend and the API from ONE process on ONE port.

Run:  uvicorn app.main:app --port 8000   then open http://127.0.0.1:8000
"""
from __future__ import annotations

from fastapi import FastAPI, Request, Depends, HTTPException
import base64
import io
from pypdf import PdfReader
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .config import ROOT, get_settings
from .llm import LLMError, complete_json
from .schemas import (ExtractRequest, FeedbackRequest, ProbeEvalRequest, ScoreRequest,
                      Submission, TaskRequest)

VERSION = "1.0.0"
async def role_context(request: Request):
    role_id = "ai-ml-intern"
    if request.method == "POST" and request.url.path not in ("/api/import-pdf", "/api/check-connection"):
        body = await request.json()
        if isinstance(body, dict):
            role_id = body.get("role_id") or body.get("extraction", {}).get("role_id", role_id)
            if body.get("task_id"):
                record = pipeline.STORE._d.get(body["task_id"])
                role_id = record.get("role_id", "ai-ml-intern") if record else "ai-ml-intern"
    if role_id not in pipeline.ROLE_IDS:
        raise HTTPException(422, "Unknown target role")
    token = pipeline.ACTIVE_ROLE.set(role_id)
    try:
        yield
    finally:
        pipeline.ACTIVE_ROLE.reset(token)

app = FastAPI(dependencies=[Depends(role_context)],title="SkillBridge AI", version=VERSION, docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def _error(status: int, kind: str, message: str, hint: str = "") -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"kind": kind, "message": message, "hint": hint}})


@app.exception_handler(LLMError)
async def _llm_error(_: Request, exc: LLMError):
    return _error(exc.status_code, exc.kind, exc.message, exc.hint)


@app.exception_handler(pipeline.SessionExpired)
async def _expired(_: Request, __: Exception):
    return _error(409, "session_expired", "This task session has expired (the server restarted).",
                  "Start a new task. Your CV text is still in the box.")


@app.exception_handler(pipeline.GateError)
async def _gate(_: Request, exc: pipeline.GateError):
    return _error(422, "gate", exc.message, exc.hint)


_FIELD_NAMES = {"cv_text": "CV text", "answer": "Your answer", "communication": "Explanation"}


@app.exception_handler(RequestValidationError)
async def _invalid(_: Request, exc: RequestValidationError):
    first = (exc.errors() or [{}])[0]
    field = str((first.get("loc") or ["", "input"])[-1])
    label = _FIELD_NAMES.get(field, field)
    ctx = first.get("ctx") or {}
    if first.get("type") == "string_too_short":
        msg = f"{label} is too short (at least {ctx.get('min_length', '?')} characters)."
    elif first.get("type") == "string_too_long":
        msg = f"{label} is too long (at most {ctx.get('max_length', '?')} characters)."
    else:
        msg = f"{label}: {first.get('msg', 'invalid input')}"
    return _error(422, "invalid_input", msg)


# --------------------------------------------------------------------------
# Pages and status
# --------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health():
    s = get_settings()
    r = pipeline.rubric()
    return {"ok": True, "version": VERSION, "provider": s.provider, "model": s.active_model,
            "fallback_model": s.gemini_fallback_model if s.provider == "gemini" else None,
            "has_key": s.has_key, "test_mode": s.provider == "mock",
            "role": r["role_title"], "rubric_version": r["rubric_version"]}


def _must_be_object(obj):
    if not isinstance(obj, dict):
        raise ValueError("expected a JSON object")
    return obj


@app.post("/api/check-connection")
async def check_connection():
    obj, meta = await complete_json(
        'You are a connectivity check. Reply with ONE JSON object only: {"ok": true, "message": "ready"}',
        "Connection test.", purpose="ping", validate=_must_be_object)
    return {"ok": True, "reply": obj, "meta": meta.to_dict()}


@app.get("/api/demo-cv")
async def demo_cv():
    return {"text": (ROOT / "demo" / "demo_cv.txt").read_text(encoding="utf-8")}


@app.get("/api/rubric")
async def get_rubric():
    return pipeline.rubric()


# --------------------------------------------------------------------------
# Assessment flow
# --------------------------------------------------------------------------
@app.post("/api/extract")
async def extract(req: ExtractRequest):
    return await pipeline.extract_claims(req.cv_text)


@app.post("/api/task")
async def task(req: TaskRequest):
    return await pipeline.generate_task(req.extraction, req.claim_id)


@app.post("/api/probes")
async def probes(req: Submission):
    return await pipeline.generate_probes(req.task_id, req.answer, req.communication)


@app.post("/api/score")
async def score(req: ScoreRequest):
    return await pipeline.score_attempt(req.task_id, req.attempt, req.answer, req.communication,
                                        req.previous_answer, req.previous_communication,
                                        req.critique, req.self_prediction)


@app.post("/api/probes/evaluate")
async def probes_evaluate(req: ProbeEvalRequest):
    return await pipeline.evaluate_probes(req.task_id, req.answer, req.communication,
                                          req.probes, req.probe_answers)


@app.post("/api/feedback")
async def feedback(req: FeedbackRequest):
    return await pipeline.write_feedback(req.task_id, req.attempt, req.answer, req.communication,
                                         req.scores, req.self_prediction)



@app.get("/api/roles")
async def roles():
    return {"roles": [{"role_id": rid, "title": pipeline._load_rubric(rid)["role_title"],
                       "rubric_version": pipeline._load_rubric(rid)["rubric_version"]}
                      for rid in pipeline.ROLE_IDS]}


@app.post("/api/import-pdf")
async def import_pdf(request: Request):
    body = await request.json()
    encoded = body.get("file_base64", "") if isinstance(body, dict) else ""
    if not isinstance(encoded, str) or len(encoded) > 7_000_000:
        return _error(422, "pdf", "Please choose a PDF smaller than 5 MB.")
    try:
        data = base64.b64decode(encoded, validate=True)
        if len(data) > 5 * 1024 * 1024 or not data.startswith(b"%PDF-"):
            raise ValueError("Invalid PDF")
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            return _error(422, "pdf", "Password-protected PDFs are not supported. Paste the text instead.")
        if len(reader.pages) > 30:
            return _error(422, "pdf", "Choose a PDF with at most 30 pages.")
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if len(text) < 80:
            return _error(422, "pdf", "No usable text found. Scanned PDFs need OCR; paste your text instead.")
        if len(text) > 20000:
            return _error(422, "pdf", "This PDF exceeds 20,000 characters. Paste only the relevant project details.")
        return {"text": text, "pages": len(reader.pages)}
    except Exception:
        return _error(422, "pdf", "Could not read this PDF. Paste your project text instead.")
