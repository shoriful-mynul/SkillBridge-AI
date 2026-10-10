# SkillBridge AI

**Project-grounded skill practice for students**

**Team Gradient · AICON’26 Build With AI · EdTech & Workforce · NUST**

SkillBridge AI helps students explain the technical decisions behind their own projects. It turns a project-linked CV claim into a focused task, asks follow-up questions, provides feedback supported by answer quotations, and compares the evidence before and after a student-chosen revision.

The report belongs to the student. It describes evidence on one task, rather than certifying a skill or recommending a hiring decision.

## Team Gradient

SkillBridge AI is a group project developed by four team members:

## Team Gradient

SkillBridge AI is a group project developed by four team members:

| Team member | GitHub |
|---|---|
| Shoriful Islam | [@shoriful-mynul](https://github.com/shoriful-mynul) |
| Fatima Salam | [@FatimaSalam29](https://github.com/FatimaSalam29) |
| Jabir Sharif | [@starbucksat4thave](https://github.com/starbucksat4thave) |
| Zoya Jabeen | [@ZoyaJabeen468](https://github.com/ZoyaJabeen468) |

## Problem and approach

A CV can list a tool without explaining why it was chosen, how its result was checked, or which constraints affected the decision. Students need an opportunity to practise those explanations and act on specific feedback.

SkillBridge AI connects that practice to the student's stated work:

1. Choose a target role and provide project or CV text.
2. Review extracted claims and their source evidence.
3. Select an eligible claim linked to a sufficiently described project.
4. Predict the expected score and answer a grounded technical task.
5. Respond to two follow-up probes about the explanation.
6. Review dimension scores and feedback.
7. Choose whether to revise.
8. Inspect the final comparison, performance graphs, and optional roadmap.

## Implemented features

| Feature | Purpose |
|---|---|
| Three target roles | AI/ML Intern, Data Analyst Intern, and Frontend Developer Intern |
| Project and CV input | Paste text or import a text-based PDF with an editable preview |
| Source-linked claim review | Inspect quotations and select an eligible project-linked claim |
| Grounded tasks | Practise a decision connected to the student's stated project and tools |
| Self-prediction | Compare the expected score with demonstrated evidence |
| Follow-up probes | Explain choices and boundaries in the submitted answer |
| Rubric feedback | Inspect scores, supporting quotations, and next-level evidence |
| Guided revision | Respond to feedback through a student-chosen revision |
| Performance graphs | Compare dimensions and distance to the two Evidenced gates |
| Branching roadmap | Explore growth options or a small seven-day practice plan |
| Student-owned exports | Download Markdown reports, save sessions for replay, or print to PDF |

PDF import supports selectable text, up to 5 MB and 30 pages. It does not perform OCR on scanned documents.

The **What changed** graphs and roadmap appear after **Score my revision**. Choosing **Saved for later** records the initial attempt without inventing a revision comparison.

## Current application and repository layout

The current application is in:

```text
skillbridge-ai/skillbridge-ai/
```

All current application commands must run from that directory.

| Location | Contents |
|---|---|
| `skillbridge-ai/skillbridge-ai/app/` | FastAPI routes, pipeline, schemas, provider adapters, and deterministic checks |
| `skillbridge-ai/skillbridge-ai/static/` | Plain HTML, CSS, and JavaScript frontend |
| `skillbridge-ai/skillbridge-ai/prompts/` | Six system prompts, including the revision roadmap |
| `skillbridge-ai/skillbridge-ai/rubrics/` | Three role-specific rubric files |
| `skillbridge-ai/skillbridge-ai/tests/` | Automated application and guardrail checks |
| `skillbridge-ai/skillbridge-ai/demo/` | Synthetic demonstration input |
| `skillbridge-ai/skillbridge-ai/fixtures/` | Synthetic evaluation fixtures |
| `skillbridge-ai/skillbridge-ai/evals/` | Optional provider-based evaluation scripts |

An earlier JavaScript implementation remains at the repository root. Its npm/pnpm and signing-key setup is separate from the current FastAPI application. See [the earlier implementation reference](docs/LEGACY_JAVASCRIPT.md).

## Technology and responsibilities

The current application uses **Python 3.10+, FastAPI, Pydantic, httpx, python-dotenv, pypdf, and Google Gemini**. FastAPI serves the frontend and API from one process. The frontend needs no Node.js, npm, build step, database, or external CDN.

**AI responsibilities:** claim extraction, task generation, follow-up probes, dimension-level assessment, feedback, and roadmap generation.

**Application responsibilities:** schema validation, source-quote checks, grounding rules, score caps, weighted aggregation, verification status, roadmap branching, and generated-language checks.

Live AI requires internet access, a configured provider key, and available quota. Local frontend assets, saved-session replay, and labelled mock tests do not imply offline live AI generation.

## Run locally

Clone the repository and enter the current application directory:

```sh
git clone https://github.com/shoriful-mynul/SkillBridge-AI.git
cd SkillBridge-AI/skillbridge-ai/skillbridge-ai
python -m venv .venv
```

Install dependencies on Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS or Linux:

```sh
.venv/bin/python -m pip install -r requirements.txt
```

Create a file named `.env` beside the application's `requirements.txt`:

```dotenv
LLM_PROVIDER=gemini
GEMINI_API_KEY=REPLACE_WITH_YOUR_PRIVATE_API_KEY
GEMINI_MODEL=REPLACE_WITH_YOUR_TESTED_MODEL_ID
GEMINI_FALLBACK_MODEL=REPLACE_WITH_YOUR_TESTED_MODEL_ID
```

Replace every placeholder. Use a model available to your API key. If a separate fallback has not been tested, use the same model ID for both model variables. Keep real API keys out of GitHub, screenshots, and exported reports.

Start the application on Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

On macOS or Linux:

```sh
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** and select **Check connection** before running a live assessment.

## Assessment and evidence rules

Scores use anchored criteria on a **0–4 scale**.

| Dimension | Rubric weight |
|---|---|
| Claim Substantiation | 0.30 |
| Technical Correctness | 0.25 |
| Reasoning Transparency | 0.20 |
| Communication | 0.15 |
| Coachability Delta | 0.10; revision only |

The **0–100 evidence index** compares the same four base dimensions on both attempts, with their weights normalized. Coachability is reported separately.

A score above 1 requires a supporting quotation that can be found in the submission. Unverifiable evidence is removed, and unsupported scores are capped.

The status **Evidenced on this task** requires both:

- Claim Substantiation at least 3.
- Technical Correctness at least 3.

Other results use **Partially evidenced** or **Not yet evidenced** framing. A quotation establishes what was written; it does not establish that code ran or that the explanation is technically correct.

### Branching roadmap

The server chooses the branch from the scored revision:

- **Both gates at least 3:** a verified source quotation, exactly two growth options from the lowest-scoring dimensions, two or three repeatable habits, and another eligible claim or guidance on adding CV project evidence.
- **Either gate below 3:** literal gate scores, seven small optional practice actions with checkable outcomes, next-level evidence, an adjacent grounded claim option, and an explanation of any score cap.

Roadmap prose is checked and kept under 320 words. Unsuitable content receives one correction request before a checked fallback is attempted. A roadmap error preserves the scored report and can be retried without rescoring.

## Render deployment

Create a **Web Service** connected to this repository.

| Setting | Value |
|---|---|
| Branch | `main` |
| Root Directory | `skillbridge-ai/skillbridge-ai` |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1` |
| Health Check Path | `/api/health` |

Configure the provider variables from the local setup in Render's **Environment** settings. A single worker preserves request access to the same in-memory task store.

After deployment, check `/api/health`, run **Check connection**, and complete an assessment through the final report. A healthy server or detected API key alone does not establish provider access or assessment quality.

Free-instance cold starts can delay the first request. Open the application before a demonstration and retain an exported session as a clearly labelled replay option.

## Testing and evaluation

From the current application directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Use `.venv/bin/python -m pytest -q` on macOS or Linux.

The latest recorded development run passed **50 tests**, covering source checks, gates, scoring rules, API flow, roadmap branches, correction/fallback behavior, and an optional Node-based check of graph markup, exports, and retry behavior. JavaScript syntax checking also passed. Node is optional for that development check and is not needed to run the application.

For an offline wiring demonstration, set `LLM_PROVIDER=mock` in the application `.env`. Mock output is a deterministic test double, clearly labelled **TEST MODE**, and must not be presented as live AI output.

The optional `python -m evals.run` command uses the configured provider and consumes API quota. Automated checks and synthetic fixtures are engineering evidence, not a student study or validation of learning outcomes.

## Privacy and practical limits

- The frontend requests consent before sending project text to the AI provider.
- The application has no assessment database or candidate-account system; live task state is held in process memory.
- Restarting, redeploying, or losing the server process clears active task state.
- Reports and saved sessions contain submitted text; students choose whether to export or share them.
- AI provider retention policies are separate from the application's storage design.
- Provider errors, model availability, quotas, and connectivity can interrupt live requests.
- Follow-up confidence is advisory. It is not AI-use detection or proof of authorship.

The report describes evidence on one task. It is not a certification, an employability score, a ranking, a hiring recommendation, or proof of lasting learning.

## Development disclosure and next steps

AI coding assistance was used during development. Repository history retains earlier drafts and implementations. The team should describe contributions and preparation timing accurately; this README does not assert that every file was authored within a particular competition window.

Next evaluation priorities are a small student pilot, independently rated explanations, rubric calibration, and usability feedback. These are planned activities, not completed educational validation.
