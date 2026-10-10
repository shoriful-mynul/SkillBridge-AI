"use strict";

/* SkillBridge AI frontend. No build step, no external requests except our own API. */

const STEPS = [
  ["cv", "Your CV"], ["claims", "Your claims"], ["task", "Your task"],
  ["probes", "Two questions"], ["results", "Your evidence"], ["revise", "Revise"], ["final", "What changed"],
];
const LEVELS = [["0", "Not at all"], ["1", "A little"], ["2", "Partly"], ["3", "Mostly"], ["4", "Fully"]];
const SKILL_NAMES = {
  python_fundamentals: "Python", data_wrangling: "Data wrangling", classical_ml: "Classical ML",
  deep_learning: "Deep learning", model_evaluation: "Model evaluation", sql: "SQL",
  experiment_hygiene: "Experiment hygiene", technical_communication: "Technical communication",
};
const STRENGTH_NAMES = { asserted: "Listed only", contextual: "Used in a project", substantiated: "Backed by a result" };

const S = {
  roleId: "ai-ml-intern", roles: [], consent: false, health: null, conn: null, stage: "cv", cv: "", extraction: null, claimId: null, task: null,
  selfPrediction: null, answer: "", comm: "", probes: null, probeAnswers: ["", ""],
  s1: null, ownership: null, fb1: null, revAnswer: "", revComm: "", s2: null, fb2: null,
  finishedEarly: false, busy: false, error: null, progress: null, replay: null,
};

/* ---------------- helpers ---------------- */
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const words = (t) => (t || "").trim().split(/\s+/).filter(Boolean).length;
const skillName = (c) => {
  const base = SKILL_NAMES[c.skill] || c.raw_label || "Skill";
  return c.raw_label && base.toLowerCase() !== c.raw_label.toLowerCase() ? `${base} (${c.raw_label})` : base;
};
const stageIndex = (id) => STEPS.findIndex((s) => s[0] === id);
const fmtMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`);

async function api(path, body) {
  const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw Object.assign(new Error("Can't reach the SkillBridge server."), { hint: "Make sure the server window is still running, then try again.", kind: "offline" });
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = data.error || {};
    throw Object.assign(new Error(err.message || `Request failed (${res.status}).`), { hint: err.hint || "", kind: err.kind || "error" });
  }
  return data;
}

/* ---------------- evidence highlighting ---------------- */
const QMAP = { "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " " };
const mapChars = (s) => s.replace(/[‘’“”–— ]/g, (c) => QMAP[c]); // length-preserving
const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function collectQuotes(scores) {
  const map = new Map();
  for (const s of scores || []) {
    for (const e of s.evidence_spans || []) {
      const key = e.quote.trim();
      if (!key) continue;
      if (!map.has(key)) map.set(key, new Set());
      map.get(key).add(s.label);
    }
  }
  return [...map].map(([quote, labels]) => ({ quote, dims: [...labels] }));
}

function highlight(text, quotes) {
  const hay = mapChars(text || "");
  const ranges = [];
  for (const { quote, dims } of quotes) {
    const frags = mapChars(quote).split(/\s*(?:\.\.\.|…)\s*/)
      .map((f) => f.trim().replace(/^[\s"'`.,;:!?()]+|[\s"'`.,;:!?()]+$/g, ""))
      .filter((f) => f.length >= 6);
    for (const f of frags) {
      const m = new RegExp(f.split(/\s+/).map(escRe).join("\\s+"), "i").exec(hay);
      if (m) ranges.push({ start: m.index, end: m.index + m[0].length, dims });
    }
  }
  ranges.sort((a, b) => a.start - b.start);
  const merged = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r.start < last.end) {
      last.end = Math.max(last.end, r.end);
      last.dims = [...new Set([...last.dims, ...r.dims])];
    } else merged.push({ ...r });
  }
  let html = "", pos = 0;
  for (const r of merged) {
    html += esc(text.slice(pos, r.start));
    html += `<mark class="ev" title="Evidence for: ${esc(r.dims.join(", "))}">${esc(text.slice(r.start, r.end))}</mark>`;
    pos = r.end;
  }
  return html + esc(text.slice(pos));
}

/* ---------------- top bar ---------------- */
function renderTop() {
  const chip = $("#status-chip");
  const h = S.health;
  let cls = "chip", text = "Checking setup…";
  if (S.replay) { cls = "chip ok"; text = "Viewing a saved session"; }
  else if (!h) { cls = "chip bad"; text = "Server not reachable"; }
  else if (h.test_mode) { cls = "chip bad"; text = "Test mode (not AI)"; }
  else if (!h.has_key) { cls = "chip warn"; text = "No API key yet"; }
  else if (S.conn && S.conn.ok) { cls = "chip ok"; text = `Live AI: ${S.conn.model}`; }
  else if (S.conn && !S.conn.ok) { cls = "chip bad"; text = "Connection problem"; }
  else { cls = "chip"; text = `Ready: ${h.model}`; }
  chip.className = cls;
  chip.textContent = text;
  $("#btn-check").disabled = !!S.replay;

  const b = $("#banner");
  b.className = "";
  if (S.replay) {
    b.className = "replay";
    b.textContent = `Viewing a saved session recorded ${S.replay.recorded_at} with ${S.replay.model}. These are the real results from that run; nothing is being scored live.`;
  } else if (h && h.test_mode) {
    b.className = "test";
    b.textContent = "TEST MODE: answers come from canned test doubles, not AI. Never present these as AI results. Set LLM_PROVIDER=gemini in .env for real assessments.";
  } else if (S.conn && !S.conn.ok) {
    b.className = "nokey";
    b.textContent = `${S.conn.message} ${S.conn.hint || ""}`;
  } else if (h && !h.has_key) {
    b.className = "nokey";
    b.textContent = "No API key yet. Add GEMINI_API_KEY to the .env file, then press Check connection. No restart needed.";
  } else {
    b.textContent = "";
  }
}

/* ---------------- rail ---------------- */
function renderRail() {
  const cur = stageIndex(S.stage);
  $("#steps").innerHTML = STEPS.map(([id, label], i) => {
    const cls = i < cur ? "done" : i === cur ? "current" : "";
    return `<li class="${cls}"${i === cur ? ' aria-current="step"' : ""}>${esc(label)}</li>`;
  }).join("");
}

/* ---------------- shared fragments ---------------- */
function errorBox() {
  if (!S.error) return "";
  const extra = S.error.kind === "session_expired" && S.extraction
    ? `<div class="actions"><button class="btn ghost" data-act="build-task">Build a new task</button></div>` : "";
  return `<div class="error" role="alert"><strong>${esc(S.error.message)}</strong>${S.error.hint ? `<div class="hint">${esc(S.error.hint)}</div>` : ""}${extra}</div>`;
}

function progressList() {
  if (!S.progress) return "";
  return `<ul class="progress" aria-live="polite">${S.progress.map((p) =>
    `<li class="${p.state}">${esc(p.label)}${p.ms ? `<span class="ms">${fmtMs(p.ms)}</span>` : ""}</li>`).join("")}</ul>`;
}

function summary(what, val) {
  return `<div class="panel summary"><span class="what">${esc(what)}</span><span class="val">${val}</span></div>`;
}

function pips(score) {
  return `<span class="pips" aria-label="${score} of 4">${[1, 2, 3, 4].map((i) => `<span class="${i <= score ? "on" : ""}"></span>`).join("")}<em>${score} of 4</em></span>`;
}

function metaLine(models, verb = "Scored by") {
  const list = [...new Set((models || []).filter(Boolean))];
  return list.length ? `<p class="meta-line">${verb} ${esc(list.join(", "))}</p>` : "";
}

/* ---------------- stage panels ---------------- */
function panelCv() {
  const dis = S.busy || S.replay ? "disabled" : "";
  return `<section class="panel">
    <h1>Show what you can actually do</h1>
    <p class="lead">Paste your CV as plain text. SkillBridge reads the skills you claim, builds one short task from your own project, and then shows you the exact lines in your answer that prove the skill, or what isn't shown yet.</p>
    <div class="row"><span class="small">Target role</span><select id="target-role" ${dis} aria-label="Target role">${S.roles.map(r=>`<option value="${esc(r.role_id)}" ${r.role_id===S.roleId?"selected":""}>${esc(r.title)}</option>`).join("")}</select></div>
    <label class="upload-zone">Upload a text-based PDF <span>Up to 5 MB · preview and edit before sending to AI</span><input id="pdf-input" type="file" accept=".pdf,application/pdf" ${dis}></label>
    <label class="field" for="cv">Project or CV text</label>
    <textarea id="cv" class="cv" placeholder="Paste your CV here as plain text" ${S.replay ? "readonly" : ""}>${esc(S.cv)}</textarea>
    <div class="actions">
      <button class="btn" data-act="read-cv" ${dis}>Understand my project</button>
      <button class="btn ghost" data-act="load-demo" ${dis}>Load demo CV</button>
    </div>
    <p class="small" style="margin-top:12px"><label class="consent"><input id="consent" type="checkbox" ${S.consent?"checked":""} ${dis}> I agree to send this text to the configured AI provider. Remove personal details first.</label> Your text goes to the AI provider for this assessment only. The SkillBridge server keeps no database.</p>
    ${progressList()}${errorBox()}
  </section>`;
}

function panelClaims() {
  const ex = S.extraction;
  const st = ex.stats || {};
  const by = st.by_strength || {};
  const rows = ex.claims.map((c) => {
    const picked = c.claim_id === S.claimId;
    return `<tr class="${picked ? "pick" : ""} ${c.eligible ? "" : "off"}">
      <td><input type="radio" name="claim" value="${esc(c.claim_id)}" aria-label="Test ${esc(skillName(c))}" ${picked ? "checked" : ""} ${c.eligible && !S.busy && !S.replay ? "" : "disabled"}></td>
      <td>${esc(skillName(c))}${c.eligible ? "" : `<span class="why-off">${esc(c.ineligible_reason)}</span>`}</td>
      <td><span class="str ${esc(c.strength)}">${esc(STRENGTH_NAMES[c.strength] || c.strength)}</span></td>
      <td><q>${esc(c.evidence_span)}</q></td></tr>`;
  }).join("");
  const removed = ex.quote_check?.removed_count || 0;
  const quoteNote = removed
    ? `<div class="notice warn">${removed} item${removed > 1 ? "s" : ""} the AI cited ${removed > 1 ? "were" : "was"} not found word for word in your CV and ${removed > 1 ? "were" : "was"} removed.</div>`
    : `<div class="notice ok">Every quote below was checked word for word against your CV by code.</div>`;
  const gate = ex.gate?.passed
    ? ""
    : `<div class="notice warn"><strong>No fair task is possible yet.</strong> ${esc(ex.gate?.message)}</div>`;
  const warnings = (ex.warnings || []).map((w) => `<div class="notice">${esc(w)}</div>`).join("");
  return `<section class="panel">
    <h2>What your CV claims</h2>
    <p class="lead">Each claim is tagged by how much your CV backs it up. Pick one to prove. We suggest the claim with the least backing that still has a project behind it, because that's where proof adds the most.</p>
    ${quoteNote}
    <p class="small">${st.claims || 0} claims found: ${by.asserted || 0} listed only, ${by.contextual || 0} used in a project, ${by.substantiated || 0} backed by a result.</p>
    <div style="overflow-x:auto"><table class="claims">
      <thead><tr><th></th><th>Skill</th><th>How it's backed</th><th>From your CV</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4">No skill claims were found.</td></tr>`}</tbody>
    </table></div>
    ${warnings}${gate}
    <div class="actions">
      ${ex.gate?.passed ? `<button class="btn" data-act="build-task" ${S.claimId && !S.busy && !S.replay ? "" : "disabled"}>Build my task</button>` : ""}
      <button class="btn ghost" data-act="edit-cv" ${S.busy || S.replay ? "disabled" : ""}>Edit my CV</button>
    </div>
    ${progressList()}${errorBox()}
    ${metaLine([ex.meta?.model], "Read by")}
  </section>`;
}

function panelTask() {
  const t = S.task;
  const scale = LEVELS.map(([v, label]) =>
    `<button type="button" data-act="predict" data-v="${v}" aria-pressed="${String(S.selfPrediction) === v}" ${S.busy || S.replay ? "disabled" : ""}><b>${v}</b>${esc(label)}</button>`).join("");
  const cw = words(S.comm);
  const ready = S.selfPrediction !== null && S.answer.trim() && !S.busy && !S.replay;
  return `<section class="panel">
    <h2>Your task</h2>
    <p class="grounding">Built from your project <strong>${esc(t.project.title)}</strong>. ${esc(t.grounding_justification)}</p>
    ${t.grounding_check === "weak" ? `<div class="notice warn">This task may be less specific to your project than intended.</div>` : ""}
    <div class="task-text">${esc(t.task_prompt)}</div>
    <h3 style="margin-top:22px">Before you start</h3>
    <p>How well do you expect this attempt to show the skill? You'll see how your guess compares.</p>
    <div class="scale" role="group" aria-label="Self prediction">${scale}</div>
    <label class="field" for="answer">Your answer <span class="small">Prose, pseudocode or code are all fine.</span></label>
    <textarea id="answer" ${S.replay ? "readonly" : ""}>${esc(S.answer)}</textarea>
    <label class="field" for="comm">Explain it simply <span class="small">${esc(t.communication_subtask)}</span></label>
    <textarea id="comm" style="min-height:100px" ${S.replay ? "readonly" : ""}>${esc(S.comm)}</textarea>
    <div class="counter ${cw > 120 ? "over" : ""}" id="comm-count">${cw} / 120 words</div>
    <div class="actions"><button class="btn" data-act="submit-answer" ${ready ? "" : "disabled"}>Submit answer</button>
      <span class="small">${S.selfPrediction === null ? "Choose your guess above first." : "There's no timer. Take the time you need."}</span></div>
    ${progressList()}${errorBox()}
    ${metaLine([t.meta?.model], "Task written by")}
  </section>`;
}

function panelProbes() {
  const items = S.probes.map((p, i) => `<div class="probe">
      ${p.anchored_quote ? `<blockquote>You wrote: “${esc(p.anchored_quote)}”</blockquote>` : ""}
      <label class="field" for="probe-${i}" style="margin-top:4px">${esc(p.question)}</label>
      <textarea id="probe-${i}" data-probe="${i}" style="min-height:90px" ${S.replay ? "readonly" : ""}>${esc(S.probeAnswers[i])}</textarea>
    </div>`).join("");
  return `<section class="panel">
    <h2>Two quick questions about your answer</h2>
    <p class="lead">These ask about what you actually wrote, so the evidence report can show the work is yours. Two or three sentences each is plenty.</p>
    ${items}
    <div class="actions"><button class="btn" data-act="see-evidence" ${S.busy || S.replay ? "disabled" : ""}>See my evidence</button></div>
    ${progressList()}${errorBox()}
  </section>`;
}

function dimBlock(s) {
  const quotes = (s.evidence_spans || []).map((e) =>
    `<div class="ev-quote">“${esc(e.quote)}”</div>${e.why_it_supports ? `<div class="ev-why">${esc(e.why_it_supports)}</div>` : ""}`).join("");
  return `<div class="dim">
    <div class="dim-head"><h3>${esc(s.label)}</h3>${pips(s.score)}</div>
    <p class="anchor">${esc(s.anchor)}</p>
    ${quotes}
    ${s.capped ? `<span class="flag">Capped at 1: no quote the scorer cited could be found in your answer.</span>` : ""}
    ${s.anomaly_flag ? `<span class="flag">Note: ${esc(s.anomaly_flag)}</span>` : ""}
    ${s.missing_for_next_level ? `<p class="next"><strong>For the next level:</strong> ${esc(s.missing_for_next_level)}</p>` : ""}
  </div>`;
}

function calibBlock(c) {
  if (!c) return "";
  const pct = (v) => `${(v / 4) * 100}%`;
  const ticks = [0, 1, 2, 3, 4].map((v) => `<span class="tick" style="left:${pct(v)}">${v}</span>`).join("");
  return `<h3 style="margin-top:22px">Your guess and this attempt</h3>
    <div class="calib" aria-label="You predicted ${c.self_predicted}, this attempt showed ${c.demonstrated}">
      <div class="track"></div>${ticks}
      <span class="pin you" style="left:${pct(c.self_predicted)}">Your guess</span>
      <span class="pin shown" style="left:${pct(c.demonstrated)};top:${Math.abs(c.self_predicted - c.demonstrated) < 0.6 ? "-18px" : "0"}">This attempt</span>
    </div>
    <p>${esc(c.framing)}</p>`;
}

function answerDocs(answer, comm, scores) {
  const q = collectQuotes(scores);
  return `<div class="answer-doc"><h4>Your answer</h4>${highlight(answer, q)}</div>
    ${comm.trim() ? `<div class="answer-doc"><h4>Your plain-language explanation</h4>${highlight(comm, q)}</div>` : ""}`;
}

function panelResults() {
  const s1 = S.s1, fb = S.fb1, own = S.ownership;
  const gap = fb.highest_leverage_gap || {};
  const ns = fb.next_step_choice || {};
  const dis = S.busy || S.replay ? "disabled" : "";
  return `<section class="panel">
    <p class="small">First attempt</p>
    <div class="verdict ${esc(s1.verification.status)}">${esc(s1.verification.label)}</div>
    <p class="small">${esc(s1.verification.caveat)}</p>

    <h3 style="margin-top:22px">Feedback</h3>
    <div class="feedback-prose">${esc(fb.full_prose)}</div>

    <h3 style="margin-top:22px">Your answer, with the evidence marked</h3>
    <p class="small"><span class="mark-legend"></span>Highlighted text is what the scorer quoted as evidence. Code checked every quote word for word against your answer.</p>
    ${answerDocs(S.answer, S.comm, s1.scores)}

    <h3 style="margin-top:26px">How each part was judged</h3>
    <p class="small">Each part is a separate AI call that sees only that part's checklist. A score above 1 needs a quote that really is in your answer.</p>
    ${s1.scores.map(dimBlock).join("")}

    ${calibBlock(s1.calibration)}

    <h3 style="margin-top:22px">Your follow-up answers</h3>
    <p>${esc(own.advisory_note)}</p>
    <p class="small">How clearly your answers explained your own work: ${esc(own.integrity_confidence)} confidence. This is never an accusation, and no AI-detection is used.</p>

    <h3 style="margin-top:22px">Choose your next step</h3>
    <p>${esc(gap.what_happened)} <strong>${esc(gap.concrete_fix)}</strong></p>
    <div class="choice">
      <div><p>${esc(ns.option_a || "Revise this answer using the feedback above.")}</p>
        <button class="btn" data-act="start-revise" ${dis}>Revise my answer</button></div>
      <div><p>${esc(ns.option_b || "Practise the idea separately and come back later.")}</p>
        <button class="btn ghost" data-act="finish-early" ${dis}>Finish here</button></div>
    </div>
    ${exportRow()}
    ${metaLine([...(s1.models_used || []), fb.meta?.model, own.meta?.model])}
  </section>`;
}

function panelRevise() {
  const gap = S.fb1.highest_leverage_gap || {};
  return `<section class="panel">
    <h2>Revise your answer</h2>
    <div class="reveal"><p><strong>The one change that would move your result most</strong></p><p>${esc(gap.what_happened)} ${esc(gap.concrete_fix)}</p></div>
    <details><summary>Show the task again</summary><div class="task-text">${esc(S.task.task_prompt)}</div></details>
    <label class="field" for="rev-answer">Your revised answer</label>
    <textarea id="rev-answer" style="min-height:170px" ${S.replay ? "readonly" : ""}>${esc(S.revAnswer)}</textarea>
    <label class="field" for="rev-comm">Your plain-language explanation <span class="small">${esc(S.task.communication_subtask)}</span></label>
    <textarea id="rev-comm" style="min-height:100px" ${S.replay ? "readonly" : ""}>${esc(S.revComm)}</textarea>
    <div class="actions"><button class="btn" data-act="score-revision" ${S.busy || S.replay ? "disabled" : ""}>Score my revision</button></div>
    ${progressList()}${errorBox()}
  </section>`;
}

function panelFinal() {
  if (!S.s2) {
    return `<section class="panel">
      <h2>Saved for later</h2>
      <p>You chose to practise first. Your evidence report records this attempt, and you can come back to the same claim any time.</p>
      ${exportRow()}
      <div class="actions"><button class="btn ghost" data-act="restart" ${S.replay ? "disabled" : ""}>Start a new assessment</button></div>
    </section>`;
  }
  const s1 = S.s1, s2 = S.s2, fb = S.fb2;
  const gain = s2.evidence_index - s1.evidence_index;
  const before = Object.fromEntries(s1.scores.map((s) => [s.dimension_id, s.score]));
  const coach = s2.scores.find((s) => s.dimension_id === "coachability_delta");
  const rows = s2.scores.filter((s) => s.dimension_id !== "coachability_delta").map((s) => {
    const b = before[s.dimension_id] ?? 0;
    const d = s.score - b;
    return `<tr><td>${esc(s.label)}</td><td class="num">${b}</td><td class="num">${s.score}</td><td class="${d > 0 ? "up" : ""}">${d > 0 ? "+" + d : d}</td></tr>`;
  }).join("");
  const r = s2.reveal || {};
  return `<section class="panel">
    <h2>What changed after one round of feedback</h2>
    <div class="delta"><span class="n before">${s1.evidence_index}</span><span class="arrow">→</span><span class="n">${s2.evidence_index}</span>
      <span class="gain">${gain >= 0 ? "+" + gain : gain} points</span></div>
    <p class="small">Evidence index from 0 to 100, computed over the same four parts on both attempts. It measures one task's evidence, not you.</p>
    <p class="small" style="margin-top:14px">Now</p>
    <div class="verdict ${esc(s2.verification.status)}">${esc(s2.verification.label)}</div>
    <p class="small">${esc(s2.verification.caveat)}</p>
    <table class="compare"><thead><tr><th>Part</th><th>First</th><th>Revised</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table>
    ${coach ? `<h3 style="margin-top:22px">How you used the feedback</h3>${dimBlock(coach)}` : ""}
    <h3 style="margin-top:22px">Feedback on your revision</h3>
    <div class="feedback-prose">${esc(fb.full_prose)}</div>
    <h3 style="margin-top:22px">Your revised answer, with the evidence marked</h3>
    ${answerDocs(S.revAnswer, S.revComm, s2.scores)}
    <h3 style="margin-top:22px">What this task was testing</h3>
    <div class="reveal"><p>${esc(r.embedded_complication)}</p>
      ${r.expected_strong_answer ? `<details><summary>See a strong answer</summary><p style="margin-top:8px">${esc(r.expected_strong_answer)}</p></details>` : ""}</div>
    ${exportRow()}
    <div class="actions"><button class="btn ghost" data-act="restart" ${S.replay ? "disabled" : ""}>Start a new assessment</button></div>
    ${metaLine([...(s2.models_used || []), fb.meta?.model])}
  </section>`;
}

function exportRow() {
  return `<div class="actions" style="border-top:1px solid var(--line);padding-top:16px">
    <button class="btn ghost" data-act="download-report">Download evidence report</button>
    <button class="btn ghost" data-act="save-session" ${S.replay ? "disabled" : ""}>Save session for replay</button>
    <button class="btn ghost" data-act="print-report">Print / Save PDF</button><span class="small">The report is yours to keep and share.</span></div>`;
}

/* ---------------- main render ---------------- */
function render(scroll) {
  renderTop();
  renderRail();
  const cur = stageIndex(S.stage);
  const parts = [];
  if (cur > 0) parts.push(summary("CV", `${S.cv.length.toLocaleString()} characters read`));
  if (cur > 1 && S.task) parts.push(summary("Claim being proved", esc(skillName(S.task.claim))));
  if (cur > 2 && S.task) parts.push(summary("Task built from", esc(S.task.project.title)));
  if (cur > 3) parts.push(summary("Follow-up questions", "Answered"));
  if (cur > 4 && S.s1) parts.push(summary("First attempt", `${esc(S.s1.verification.label)}, evidence index ${S.s1.evidence_index}`));
  if (cur > 5 && S.s2) parts.push(summary("Revision", "Scored"));
  const panel = { cv: panelCv, claims: panelClaims, task: panelTask, probes: panelProbes, results: panelResults, revise: panelRevise, final: panelFinal }[S.stage]();
  $("#main").innerHTML = parts.join("") + panel;
  const role = S.roles.find(r=>r.role_id===S.roleId);
  $("#focus").innerHTML = `<span class="eyebrow">EVIDENCE, NOT ASSUMPTIONS</span><h2>${esc(role?.title||"AI/ML Intern")}</h2><p>${S.task?esc(S.task.project.title):"One project. One grounded challenge. A clearer next step."}</p><div class="focus-divider"></div><p>Read your claims → defend a decision → use the feedback → revise.</p><p class="small">A quote proves what was written, not that code ran. Practice only, not hiring screening or certification.</p>`;
  if (scroll) {
    const last = $("#main").lastElementChild;
    if (last) last.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }
}

function go(stage) {
  S.stage = stage;
  S.error = null;
  S.progress = null;
  render(true);
}

/* ---------------- actions ---------------- */
async function run(steps, fn) {
  S.busy = true;
  S.error = null;
  S.progress = steps.map((label) => ({ label, state: "" }));
  render();
  try {
    await fn((i, state, ms) => { S.progress[i].state = state; if (ms) S.progress[i].ms = ms; render(); });
  } catch (e) {
    S.error = { message: e.message, hint: e.hint, kind: e.kind };
    S.progress = null;
  } finally {
    S.busy = false;
    render();
  }
}

async function timed(step, i, promise) {
  step(i, "run");
  const t0 = performance.now();
  const out = await promise;
  step(i, "ok", performance.now() - t0);
  return out;
}

const actions = {
  async "load-demo"() {
    try {
      S.cv = (await api("/api/demo-cv")).text;
      S.error = null;
    } catch (e) { S.error = { message: e.message, hint: e.hint }; }
    render();
  },
  async "read-cv"() {
    S.cv = $("#cv").value;
    if (!S.consent) { S.error = {message: "Please confirm consent before sending your text to AI."}; render(); return; }
    await run(["Reading your CV and checking every quote against it"], async (step) => {
      S.extraction = await timed(step, 0, api("/api/extract", { cv_text: S.cv, role_id: S.roleId }));
      S.claimId = S.extraction.default_claim_id;
      S.stage = "claims";
    });
    render(true);
  },
  "edit-cv"() { go("cv"); },
  async "build-task"() {
    await run(["Building a task from your own project"], async (step) => {
      S.task = await timed(step, 0, api("/api/task", { extraction: S.extraction, claim_id: S.claimId }));
      Object.assign(S, { selfPrediction: null, answer: "", comm: "", probes: null, probeAnswers: ["", ""], s1: null, ownership: null, fb1: null, s2: null, fb2: null, revAnswer: "", revComm: "", finishedEarly: false });
      S.stage = "task";
    });
    render(true);
  },
  predict(el) { S.selfPrediction = Number(el.dataset.v); render(); },
  async "submit-answer"() {
    await run(["Writing two follow-up questions about your answer"], async (step) => {
      const r = await timed(step, 0, api("/api/probes", { task_id: S.task.task_id, answer: S.answer, communication: S.comm }));
      S.probes = r.probes;
      S.probeAnswers = ["", ""];
      S.stage = "probes";
    });
    render(true);
  },
  async "see-evidence"() {
    const base = { task_id: S.task.task_id, answer: S.answer, communication: S.comm };
    await run([
      "Scoring four rubric parts, one AI call each, and checking every quote",
      "Reading your follow-up answers",
      "Writing your feedback",
    ], async (step) => {
      const [s1, own] = await Promise.all([
        timed(step, 0, api("/api/score", { ...base, attempt: 1, self_prediction: S.selfPrediction })),
        timed(step, 1, api("/api/probes/evaluate", { ...base, probes: S.probes, probe_answers: S.probeAnswers })),
      ]);
      const fb = await timed(step, 2, api("/api/feedback", { ...base, attempt: 1, scores: s1.scores, self_prediction: S.selfPrediction }));
      Object.assign(S, { s1, ownership: own, fb1: fb, stage: "results" });
    });
    render(true);
  },
  "start-revise"() {
    S.revAnswer = S.answer;
    S.revComm = S.comm;
    go("revise");
  },
  "finish-early"() { S.finishedEarly = true; S.s2 = null; go("final"); },
  async "score-revision"() {
    const body = {
      task_id: S.task.task_id, attempt: 2, answer: S.revAnswer, communication: S.revComm,
      previous_answer: S.answer, previous_communication: S.comm, critique: S.fb1.highest_leverage_gap,
    };
    await run(["Scoring five parts, including how you used the feedback", "Writing feedback on your revision"], async (step) => {
      const s2 = await timed(step, 0, api("/api/score", body));
      const fb = await timed(step, 1, api("/api/feedback", { task_id: S.task.task_id, attempt: 2, answer: S.revAnswer, communication: S.revComm, scores: s2.scores, self_prediction: null }));
      Object.assign(S, { s2, fb2: fb, stage: "final" });
    });
    render(true);
  },
  restart() {
    Object.assign(S, { stage: "cv", extraction: null, claimId: null, task: null, selfPrediction: null, answer: "", comm: "", probes: null, probeAnswers: ["", ""], s1: null, ownership: null, fb1: null, revAnswer: "", revComm: "", s2: null, fb2: null, finishedEarly: false, error: null, progress: null });
    render(true);
  },
  "print-report"() { window.print(); },
  "download-report"() { download(`skillbridge-evidence-report.md`, reportMarkdown(), "text/markdown"); },
  "save-session"() {
    const keep = ["roleId", "cv", "extraction", "claimId", "task", "selfPrediction", "answer", "comm", "probes", "probeAnswers", "s1", "ownership", "fb1", "revAnswer", "revComm", "s2", "fb2", "finishedEarly", "stage"];
    const data = { app: "SkillBridge AI", version: S.health?.version || "", recorded_at: new Date().toLocaleString(), model: modelsUsed().join(", ") || S.health?.model || "", state: Object.fromEntries(keep.map((k) => [k, S[k]])) };
    download(`skillbridge-session-${Date.now()}.json`, JSON.stringify(data, null, 2), "application/json");
  },
};

function modelsUsed() {
  return [...new Set([...(S.s1?.models_used || []), ...(S.s2?.models_used || []), S.fb1?.meta?.model, S.fb2?.meta?.model].filter(Boolean))];
}

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function reportMarkdown() {
  const L = [];
  const dimTable = (scores) => {
    L.push("| Part | Score | Evidence quoted from the answer |", "|---|---|---|");
    for (const s of scores) L.push(`| ${s.label} | ${s.score}/4 | ${(s.evidence_spans || []).map((e) => `"${e.quote.replace(/\|/g, "/").replace(/\n/g, " ")}"`).join("<br>") || "none"} |`);
  };
  L.push("# SkillBridge AI evidence report", "");
  L.push(`Recorded: ${S.replay?.recorded_at || new Date().toLocaleString()}  `);
  L.push(`Role: ${S.roles.find(r=>r.role_id===S.roleId)?.title || "AI/ML Intern"}  `);
  L.push(`Scored by: ${modelsUsed().join(", ") || "n/a"}`, "");
  L.push("> This report describes the evidence from one task. It is not a grade, a ranking or a hiring recommendation.", "");
  if (S.task) {
    L.push("## Claim tested", `${skillName(S.task.claim)}: "${S.task.claim.evidence_span}"`, "");
    L.push(`## Task (built from "${S.task.project.title}")`, S.task.task_prompt, "");
  }
  if (S.s1) {
    L.push("## First attempt", `**${S.s1.verification.label}.** ${S.s1.verification.caveat}  `, `Evidence index: ${S.s1.evidence_index}/100`, "");
    dimTable(S.s1.scores);
    L.push("", "### Feedback", S.fb1?.full_prose || "", "");
    if (S.s1.calibration) L.push("### Self-prediction", `Predicted ${S.s1.calibration.self_predicted}/4, this attempt showed ${S.s1.calibration.demonstrated}/4. ${S.s1.calibration.framing}`, "");
    if (S.ownership) L.push("### Follow-up questions", `${S.ownership.advisory_note} (Confidence: ${S.ownership.integrity_confidence}. No AI-detection is used.)`, "");
  }
  if (S.s2) {
    L.push("## Revision after feedback", `**${S.s2.verification.label}.** ${S.s2.verification.caveat}  `, `Evidence index: ${S.s1.evidence_index} -> ${S.s2.evidence_index}`, "");
    dimTable(S.s2.scores);
    L.push("", "### Feedback on the revision", S.fb2?.full_prose || "", "");
    if (S.s2.reveal?.embedded_complication) L.push("## What the task was testing", S.s2.reveal.embedded_complication, "");
  } else if (S.finishedEarly) {
    L.push("## Next step", "The candidate chose to practise before revising.", "");
  }
  return L.join("\n");
}

/* ---------------- events ---------------- */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.disabled) return;
  const fn = actions[el.dataset.act];
  if (fn) fn(el);
});

document.addEventListener("change", (e) => {
  if (e.target.id === "target-role") { S.roleId=e.target.value; S.extraction=null; S.claimId=null; render(); }
  if (e.target.id === "consent") S.consent=e.target.checked;
  if (e.target.id === "pdf-input") importPdf(e.target.files[0]);
  if (e.target.name === "claim") { S.claimId = e.target.value; render(); }
});

document.addEventListener("input", (e) => {
  const t = e.target;
  if (t.id === "cv") S.cv = t.value;
  else if (t.id === "answer") { S.answer = t.value; const b = $('[data-act="submit-answer"]'); if (b) b.disabled = !(S.selfPrediction !== null && S.answer.trim()) || S.busy; }
  else if (t.id === "comm") {
    S.comm = t.value;
    const c = $("#comm-count"), n = words(S.comm);
    if (c) { c.textContent = `${n} / 120 words`; c.classList.toggle("over", n > 120); }
  }
  else if (t.dataset.probe !== undefined) S.probeAnswers[Number(t.dataset.probe)] = t.value;
  else if (t.id === "rev-answer") S.revAnswer = t.value;
  else if (t.id === "rev-comm") S.revComm = t.value;
});

$("#btn-check").addEventListener("click", async () => {
  const btn = $("#btn-check");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const t0 = performance.now();
    const r = await api("/api/check-connection", {});
    S.conn = { ok: true, model: `${r.meta.model} (${fmtMs(performance.now() - t0)})` };
  } catch (e) {
    S.conn = { ok: false, message: e.message, hint: e.hint };
  }
  try { S.health = await api("/api/health"); } catch { /* keep previous */ }
  btn.textContent = "Check connection";
  btn.disabled = false;
  renderTop();
});

$("#file-session").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  try {
    const data = JSON.parse(await file.text());
    if (data.app !== "SkillBridge AI" || !data.state) throw new Error("This file isn't a SkillBridge session.");
    Object.assign(S, data.state, { busy: false, error: null, progress: null });
    S.replay = { recorded_at: data.recorded_at || "earlier", model: data.model || "an AI model" };
    if (!STEPS.some(([id]) => id === S.stage)) S.stage = S.s2 ? "final" : S.s1 ? "results" : "cv";
    render(true);
  } catch (err) {
    alertBanner(err.message);
  }
});

function alertBanner(msg) {
  const b = $("#banner");
  b.className = "nokey";
  b.textContent = msg;
}

/* ---------------- boot ---------------- */
(async function boot() {
  try { S.health = await api("/api/health"); S.roles=(await api("/api/roles")).roles; } catch { S.health = null; }
  render();
})();


async function importPdf(file) {
  if (!file || S.busy || S.replay) return;
  await run(["Extracting PDF text for your review"], async () => {
    if (file.size > 5 * 1024 * 1024) throw new Error("Choose a PDF smaller than 5 MB.");
    const encoded = await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=()=>reject(new Error("Could not read file."));reader.readAsDataURL(file);});
    const result=await api("/api/import-pdf", {file_base64:encoded});
    S.cv=result.text;
  });
  render();
}
