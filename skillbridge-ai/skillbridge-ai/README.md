# SkillBridge AI

**Team Gradient · AICON'26 Build With AI · EdTech & Workforce**

Skill claims on a CV can't be checked, so nobody trusts them, and students never find out which of their own claims won't hold up. SkillBridge AI turns one claim into evidence the student owns. It builds a short task from **the student's own project**, scores the answer with **quotes from the answer itself**, explains the one change that would help most, and shows the improvement after a single revision.

The candidate is the user, not the employer. It never ranks people, never recommends hiring decisions and never produces an employability score.

---

## Run it

You need **Python 3.10 or newer**. No Node, no database, no build step.

| Windows | Mac / Linux |
|---|---|
| Double-click **`run.bat`** | In a terminal: `./run.sh` |

The first run installs requirements (about a minute). Your browser then opens **http://127.0.0.1:8000**. Keep the window open while you use the app.

Manual start, if you prefer:

```sh
python -m venv .venv
.venv\Scripts\activate           # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Windows   (Mac/Linux: cp .env.example .env)
uvicorn app.main:app --port 8000
```

## Add your API key

1. Get a key at **https://aistudio.google.com/apikey** (sign in with Google, then "Create API key").
2. Open the **`.env`** file in this folder (run.bat/run.sh create it) and paste the key after `GEMINI_API_KEY=`, with no quotes or spaces.
3. Save the file. In the app, click **Check connection**. The chip turns green: *Live AI: gemini-3.8-flash*. No restart needed.

Alternative providers: set `LLM_PROVIDER=openai` and fill in `OPENAI_API_KEY`, `OPENAI_BASE_URL` and `OPENAI_MODEL`. This works with OpenAI, Groq and OpenRouter.

## Demo

Click **Load demo CV**, then **Read my CV**. The demo profile (`demo/demo_cv.txt`) is synthetic. Its strongest project is a student-dropout early-warning model that reports 92% accuracy when only 7% of students drop out, so the grounded task usually probes whether accuracy means anything here.

---

## How it works

After revision scoring, two accessible inline SVG graphs show dimension changes and the distance to the two Evidenced gates; the comparison table stays available. An optional AI roadmap branches from the server-held revision scores: both gates at 3 or above unlock two growth options and repeatable habits, otherwise a small seven-day practice option identifies the next evidence to try. Quotes and language are checked, prose stays under 320 words, and roadmap retries preserve the scored report. The roadmap is included in Markdown exports and saved offline replays; mock mode remains clearly labelled test output.

```
CV text ─► 1 read claims ─► [code: verify quotes, link projects, grounding gate, pick claim]
        ─► 2 grounded task ─► [code: task must name THEIR project or tools]
        ─► self-prediction (0–4, before any score)
        ─► answer ─► 4 two probes about their own answer
        ─► 3 score 4 parts, one AI call each ─► [code: verify quotes, cap at 1 without one,
                                                    weights, index, verification status, calibration]
        ─► feedback ─► [code: banned-word filter, verified opening quote, 180-word limit]
        ─► revision ─► rescore + coachability ─► before/after evidence index
```

**The AI does four jobs:** reading an unstructured CV into structured claims, writing a task grounded in the candidate's own project, scoring one rubric part at a time with quoted evidence, and asking and judging two follow-up probes. It also writes the feedback.

**Code does everything that can be a rule:** checking every quote word for word against the source, the grounding gate (a project needs at least 15 words and a medium or high rating), choosing the claim to test, score caps, weights, the evidence index, verification status, calibration, ownership confidence and the banned-word filter. Knowing where *not* to use the model is part of the design.

### Scoring protocol

- **Anchored 0–4 rubric**, five parts: Claim Substantiation 0.30, Technical Correctness 0.25, Reasoning Transparency 0.20, Communication 0.15, Coachability 0.10 (`rubrics/ai-ml-intern.json`).
- **One part per AI call**, with only that part's anchors in context. Bundled scoring drifts.
- **Quote gate, enforced in code:** a score above 1 needs a quote that really exists in the answer. Quotes that can't be found are removed and the score is capped at 1.
- **Temperature:** Google's Gemini 3 guidance says to keep temperature at its default (1.0) and warns that lower values can cause looping or degraded output. So consistency comes from the design above and is **measured** by the 3-run variance eval rather than assumed. OpenAI-compatible providers use temperature 0.
- **Evidence index (0–100)** uses the same four parts on both attempts, so the before/after change is comparable. Coachability is reported separately.
- **Verification:** *Evidenced* when Claim Substantiation ≥ 3 and Technical Correctness ≥ 3; *Partially evidenced* when both ≥ 2; otherwise *Not yet evidenced*. Every status says it covers one task.

### Integrity

There is **no AI-detection**: detectors are unreliable, and we don't claim one. Instead the task can't be transferred, because it is built from the candidate's own stated project, and two follow-up probes ask them to account for their own answer. Ownership is reported as confidence, never as an accusation, and a low score always comes with the innocent readings (nerves, time pressure, language). The task's hidden "what this tests" notes stay on the server until the final screen.

### The humane layer

These are design principles drawn from research, not validated psychometrics:

- **Self-determination theory:** the next step is offered as a choice.
- **Zone of proximal development:** the suggested step is one level up.
- **Growth mindset:** feedback is about process, never the person, enforced by a banned-word filter.
- **Mastery experience:** every result opens with one specific quoted strength.
- **Temporal framing:** "Not yet evidenced", never "failed".

## Evaluations

With a key configured:

```sh
python -m evals.run
```

This makes about 30 API calls and writes `evals/results/summary.md` with:

- **scorer variance:** the same answer scored 3 times, with the standard deviation per part;
- **separation:** a strong answer vs a weak one on a fixed task (`evals/eval_task.json`);
- **CV reading on 6 synthetic CVs:** listed-only claim rate, evidence strength, grounding-gate accuracy, discrimination (strong CV vs keyword-stuffed) and fairness (career switcher vs keyword-stuffed). Expected verdicts are in `fixtures/EXPECTED.json`.

The inputs are synthetic and the outputs come from the real model. It is a small pilot check, not a validation study.

## Tests

```sh
python -m pytest
```

33 tests cover quote verification, gates, weights, status rules, the Gemini payload fallback ladder and model fallback (against simulated API responses), friendly errors, and the full API flow. `LLM_PROVIDER=mock` runs the app on canned test doubles for offline wiring checks, and the UI shows a red **TEST MODE** banner while it does. Never present mock output as AI output.

## Deploy (for the submission link)

**Render, free plan:** push this folder to GitHub, then on render.com choose **New > Blueprint** and select the repo. `render.yaml` configures everything. Add `GEMINI_API_KEY` in the service's **Environment** tab. FastAPI serves the frontend too, so one service gives one link.

## Project structure

```
app/          FastAPI app, pipeline, provider adapters, deterministic checks
prompts/      the five system prompts
rubrics/      ai-ml-intern.json  (add a role = add a file)
static/       the frontend (plain HTML/CSS/JS, served by FastAPI)
demo/         demo_cv.txt
fixtures/     6 synthetic CVs + EXPECTED.json
evals/        run.py + eval_task.json
tests/        pytest suite
```

## Non-goals

SkillBridge AI is not a ranking engine, not a hiring decision system, not a proctoring or surveillance tool, and not a personality or trait assessment. One task is not proof of a skill, and every result says so.

## Troubleshooting

| You see | Do this |
|---|---|
| "No API key yet" | Add `GEMINI_API_KEY` to `.env`, then click Check connection |
| "The API key was rejected" | Copy the key again from aistudio.google.com/apikey |
| "Model … is not available" | Set `GEMINI_MODEL` in `.env` to one of the models the message lists |
| "Rate limit reached" | Wait a minute. Free keys allow limited requests per minute |
| "Could not reach the AI provider" | Venue Wi-Fi may block it. Switch to mobile data |
| Port 8000 in use | `set PORT=8010` then `run.bat` (Mac/Linux: `PORT=8010 ./run.sh`) |
| Wi-Fi fails during the demo | Click **Open saved session** and load a session you saved from an earlier live run. The banner states it is a replay |

---

## Originality and disclosure

**When it was built.** Team Gradient received its domain, EdTech & Workforce, at the Day 1 briefing on 9 October 2026, when the Build With AI module officially began. That evening the team defined the problem, designed the scoring rubric, drafted the AI prompts and wrote the synthetic test CVs. The application code in this repository was written on 10 October 2026 during the Day 2 build session.

**How AI tools were used to build it.** AI coding assistants helped write and test the code, which the rulebook permits (pp. 5–6). Team Gradient made the product and design decisions: the problem, the candidate-first stance, the rubric and its anchors, the rule that code rather than the model verifies quotes and computes scores, and the demo.

**What it does not contain.** There is no code from any earlier team project. An earlier draft of this idea, a website starter and a prototype made before the Day 2 session, was set aside. Earlier commits in this repository's history contain parts of that draft; none of it is used by the code here.

**Third-party resources.** Open-source libraries: FastAPI, Starlette, Uvicorn, Pydantic, httpx, python-dotenv and pytest. AI model: the Google Gemini API, a proprietary model used through its public API. There are no UI templates or component kits; the frontend is hand-written HTML, CSS and JavaScript.

**Data.** Every CV in `demo/` and `fixtures/` is synthetic, written by the team for this event. No scraped CVs or third-party personal data are used. The app keeps no database: text submitted in live mode goes to the AI provider for that assessment only.

