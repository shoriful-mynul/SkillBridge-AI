# SkillBridge UI, roles and PDF update

This is the Python/FastAPI project, not the previous npm/AI Studio version.

## Run locally

Open a terminal in `skillbridge-ai/skillbridge-ai`, beside `requirements.txt`.

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Put `.env` beside requirements.txt, with LLM_PROVIDER=gemini, GEMINI_API_KEY and an accessible GEMINI_MODEL. Secrets remain on the server. Mock mode is labeled and is only for offline testing.

## Changes

- Forest green / warm cream three-column responsive workspace, matching the earlier SkillBridge visual direction.
- AI/ML Intern, Data Analyst Intern and Frontend Developer Intern dropdown with distinct skill taxonomies and technical rubric anchors. Task records retain their chosen role during scoring; concurrent requests use isolated role contexts.
- Text-based PDF import, maximum 5 MB and 30 pages, editable preview before AI processing. Scanned, encrypted, corrupt or overlong PDFs show a paste-text fallback. No OCR; no PDF files are stored by this endpoint.
- Explicit consent before sending input to AI, dark practice context card, print/save-PDF action. Existing quote checks, calibrated prediction, follow-up probes, before/after evidence comparison, Markdown export and session replay remain.
- Existing 0–4 scale retained. A new role requires a fresh extraction/task, rather than relabeling an existing task.

## Validation

36 pytest tests passed with the mock provider, including PDF text extraction, invalid/oversized PDF handling, role isolation and role persistence. JavaScript syntax check passed. No live Gemini key or browser rendering verification was available.

## Deployment

For the existing Render service use root directory `skillbridge-ai/skillbridge-ai`, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Add API credentials through service environment settings, never GitHub. This PR does not publish a deployment.

## Hackathon priorities

Show a complete grounded task, literal evidence highlights and a comparable revision delta. Use PDF import and role-specific tasks to demonstrate usability. Keep saved-session replay explicitly labeled as a recorded run. Avoid adding authentication, leaderboards, hiring recommendations or unrelated chat features before the core live flow works.
