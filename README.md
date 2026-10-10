# SkillBridge AI — Team Gradient

Candidate-owned, project-grounded skill practice for AICON’26, EdTech & Workforce. One role in depth: AI/ML Intern. Read [the complete A–J build specification](docs/BUILD_SPEC.md).

## Implemented flow

React retains the earlier forest-green visual direction with newly authored application code: text → structured claims → task quoting the candidate’s tools and approach → self-prediction → single-dimension scoring → two adaptive probes → chosen revision → comparable evidence change. The rubric is JSON data. Python checks quotes, thresholds, aggregation, calibration and ordering. No database, document parser, vector store, candidate accounts, telemetry, rankings or hiring decisions are implemented.

The private Sites frontend has a clearly labeled synthetic rehearsal with curated fictional answers and illustrative scores. Custom assessment uses the real FastAPI/Gemini route only. Missing configuration or an outage preserves the draft and creates no score.

Current verification: Python HTTP flow and provider payload tests use contract doubles; a frontend handler/state test exercises the complete labeled rehearsal; the frontend builds for Sites. No live Gemini assessment or reliability evaluation has run: no API key or hosted Python service was supplied. Browser visual/click verification was unavailable. Complete the official-window preflight before presenting live AI.

## Stack and hosting boundary

React 19/TypeScript through the Sites Vinext starter; Python 3.12/FastAPI/Pydantic/httpx/Uvicorn, pinned in `requirements.txt`; Gemini Generate Content REST API, default `gemini-3.8-flash`, configurable with `GEMINI_MODEL`. Scores use temperature 0.0, one dimension’s anchors, JSON Schema output and Python revalidation.

Sites hosts a JS Worker, not Python. Host the provided Docker/FastAPI service on a team-controlled HTTPS runtime and configure the same-origin gateway. No external Python hosting service has been provisioned. Secrets never enter React or this repository.

## Local backend and evaluation

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Fill .env privately with your server key and stable signing/shared secrets.
set -a
source .env
set +a
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

In a second terminal using the same environment:

```sh
python -m pytest tests -q
node --test tests/frontend-loop.mjs
node node_modules/typescript/bin/tsc --noEmit
python -m evals.run
```

Windows: activate `.venv\Scripts\Activate.ps1` and set the same environment variables in PowerShell. Evaluation makes real provider calls. Without a key it exits 2 with `status: not_run`; incomplete runs also exit 2. It writes ignored `evals/results/raw-runs.json` and `metrics.json`, never rehearsal numbers. `evals/human_labels.csv` is intentionally blank for two independent raters.

Docker contains no secrets. Its production configuration requires the service token. Keep TLS and the shared token at the host boundary and disable request-body logging. Local development has no candidate account system. The assessment signing key prevents browser tampering with returned context; it is not candidate authentication. Use a stable key across workers or restarts invalidate sessions.

## Private Sites configuration

| Runtime | Variable | Purpose |
| --- | --- | --- |
| Sites | `FASTAPI_BASE_URL` | Team-controlled HTTPS origin, no path prefix |
| Sites + Python | `BACKEND_SHARED_SECRET` | Identical random server-to-server token |
| Python | `GEMINI_API_KEY` | Team-owned API key, server only |
| Python | `GEMINI_MODEL` | Record actual model used in evaluation |
| Python | `ASSESSMENT_SIGNING_KEY` | Stable random stateless receipt key |
| Python | `DEPLOYMENT_ENV` | `production` on hosted service |

Node requires 22.13+. In Sites, use the supported Sites install/build workflow and preserve the starter build integration. `npm run build` remains available standalone. The gateway requires HTTPS, including development: test FastAPI directly on loopback or connect React to the team’s HTTPS development backend. Private Site access is platform-managed, separate from the absent candidate account system. Do not widen access without owner approval.

## Interpretation

A score above 1 needs a literal current-answer quote. Existence of a quote does not prove technical correctness or code execution. Internal `verified` displays “Evidenced on this task”; other claims remain not assessed. Ownership is 0–3 confidence after two answers, always with nerves/time-pressure/language as innocent explanations. No AI-use detection or misconduct accusation is made.

Coachability is null on attempt 1; initial weights renormalize over the other four dimensions. The before/after index always uses those same four weights on both attempts, while critique uptake is shown separately. This is one task’s evidence change, not employability, lasting learning or validated psychometrics.

## Freshness and disclosure

This is a new Sites project separate from the earlier SkillProof repository. Only the visual direction is retained; its implementation/classifier was not copied. The user’s settled brief and attached `skillproof-starter.zip` were design/reference material. This implementation, prompts, rubric, synthetic profiles and paired answers were authored with Codex assistance before the supplied 09:00 official build window. A new repository alone does not establish eligibility under the prohibition on pre-existing work. Confirm allowed preparatory material with organizers and author eligible competition work within the official window; do not present this package as code written inside it.

Disclosed boilerplate/libraries: Sites Vinext starter and Sites Worker/build integration; React/React DOM, TypeScript, Vite/Vinext, Tailwind, Cloudflare tooling, FastAPI, Pydantic, httpx, Uvicorn, pytest and jsonschema. Frontend versions and stock dependencies are retained in `package.json`/`pnpm-lock.yaml`, including unused UI/database scaffolding; optional databases/uploads are disabled (`d1`/`r2` null). License notices under `build/` and `vendor/` remain. Gemini is an external proprietary model API, not an open-source library. No earlier team application code or classifier is included.

All fixture profiles/answers are synthetic and authored for this design; no scraped CVs or third-party personal data. Add team CVs only with consent and outside the committed synthetic eval set. State stays in browser memory; voluntary exports contain candidate text. In live mode the AI provider receives submitted text; provider retention is distinct from the app having no database.

## Primary references

[Gemini model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output), [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/latest/), [React](https://react.dev/). Research-informed humane principles and honest validity limitations are in the build spec.
