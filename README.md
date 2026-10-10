# SkillBridge AI — Team Gradient

Project-grounded skill practice for AICON’26, EdTech & Workforce. Choose AI/ML Intern, Data Analyst Intern or Frontend Developer Intern. Review source claims, practise one task tied to your own tools and decisions, explain two follow-ups, choose a next step and revise once.

## This version

The original forest-green React workspace is retained. Gemini requests, schema validation, quote guards, thresholds, score aggregation and signed assessment receipts now run in the JavaScript server/Worker. No separate Python service is required. Original Python files and the old build specification are retained as historical reference; their hosting instructions do not describe this version.

Added: three distinct role rubrics, role-specific fictional rehearsals, text-based PDF import (5 MB / 30 pages), editable text preview, explicit Gemini consent, optional device-only input draft, JSON export and a print-friendly evidence report.

## Run locally (Windows PowerShell)

Node >=22.13. From the project folder:

```powershell
npm install
```

Create an ignored `.dev.vars` file in the project root with:

```text
GEMINI_API_KEY=<your server key>
GEMINI_MODEL=gemini-3.8-flash
ASSESSMENT_SIGNING_KEY=<stable random signing secret>
```

Generate the signing secret privately with `node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"`. Never commit actual values. Verify your key has access to the configured model. Restart the dev process after changing secrets.

```powershell
npm run dev
```

Open the URL printed in the terminal. The rubric and all rehearsals work without Gemini. “Live Gemini service configured” means secrets exist, not that a real provider call was tested. API failures preserve drafts and earlier results and never become synthetic live scores.

## Validation

```powershell
node --test tests/server-engine.cjs tests/frontend-loop.mjs
node node_modules/typescript/bin/tsc --noEmit
npm run build
```

Server tests use contract doubles. Frontend tests exercise real handlers/state with a React hook harness; they are not browser or screenshot tests. No live Gemini request has been run by the builder because no API key was supplied. Role rubrics are authored practice criteria, not validated psychometrics. The old Python evaluation runner covers only the historical Python engine, not this JavaScript runtime; do not use its metrics to claim this engine is validated.

## Hosted configuration

Configure `GEMINI_API_KEY`, `GEMINI_MODEL`, and `ASSESSMENT_SIGNING_KEY` as Sites server environment secrets. No secret belongs in the hosting manifest, browser code or GitHub. Keep the signing key stable across workers and restarts; rotating it invalidates existing assessments. The deployed Site is private by default.

## Score interpretation

The original five dimensions use the original 0–4 anchored scale. A score above 1 needs a literal current-answer quote. A quote does not prove technical correctness or code execution. Coachability is null on attempt 1. Before/after uses the same four initially observable dimensions and normalized weights; critique uptake is separate. Follow-up confidence does not establish authorship or detect AI use.

## Data

No assessment database, candidate account system, rankings or request-body telemetry. PDF bytes are processed for text and not stored. Live submissions and answers go to Gemini; provider policies are distinct from the app not having a database. Optional browser draft saving is off by default and stores only source text and role, not scores, secrets or trusted assessment context. Exported reports contain candidate text. Rehearsals are fictional and clearly marked in the workspace and report.

## Competition disclosure

The supplied original pack and visual reference predate this revision. This migration and enhancements were created with Codex assistance. Preserve accurate authorship/timing disclosure and follow organizer rules for preparatory material. Do not describe all code as created inside the official build window unless that is true.

## Five-minute demo

- 0:00–0:35: A CV names skills; learners need a way to practise and inspect evidence.
- 0:35–1:10: Choose a target role and show project input and exact source claims.
- 1:10–1:50: Show the task tied to a real tool and decision, with one hypothetical complication.
- 1:50–2:45: Show an answer, self-prediction, rubric scores and literal evidence.
- 2:45–3:20: Answer the two follow-ups; explain that this is not AI-use detection.
- 3:20–4:20: Choose feedback, revise and show comparable evidence change.
- 4:20–5:00: Export report, limitations and future human evaluation.

If provider configuration or quota blocks live AI, explicitly switch to “Synthetic rehearsal · not live AI”. Rehearsal scores are illustrative, not evaluation results.

## Local live-button troubleshooting

The live button now validates input and consent on click and displays explicit server errors rather than staying silently disabled after a health check. The setup panel names missing secrets and includes Recheck connection. Keep `.dev.vars` beside `package.json` (not `.dev.vars.txt`), save actual values, restart `npm run dev`, and refresh. The health check does not send a provider request and never proves model access. Eleven automated tests pass, including the live-button request/error/draft-preservation path. No real provider call was possible without a supplied API key.
