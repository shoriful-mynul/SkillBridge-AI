"""Evaluation runner. Produces the numbers for your slides from REAL model calls.

    python -m evals.run

Part A - extraction on the 6 synthetic fixture CVs:
    asserted-only claim rate, evidence-strength index, grounding-gate accuracy,
    discrimination (strong CV vs keyword-stuffed CV) and fairness (career
    switcher vs keyword-stuffed CV).
Part B - scorer reliability on one fixed task (evals/eval_task.json):
    each dimension scored 3 times for a strong and a weak synthetic answer ->
    score variance and strong-vs-weak separation.

About 30 API calls. Writes evals/results/metrics.json and evals/results/summary.md.
Exits with code 2 and status "not_run" if no API key is configured.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime

from app import pipeline
from app.config import ROOT, get_settings
from app.llm import LLMError

FIX = ROOT / "fixtures"
OUT = ROOT / "evals" / "results"


def _sd(values: list[float]) -> float:
    return round(statistics.pstdev(values), 3) if len(values) > 1 else 0.0


async def part_a(pause: float) -> dict:
    expected = json.loads((FIX / "EXPECTED.json").read_text(encoding="utf-8"))
    rows = []
    for f in expected["fixtures"]:
        cv = (FIX / f["file"]).read_text(encoding="utf-8")
        print(f"  extracting {f['file']} ...", flush=True)
        ex = await pipeline.extract_claims(cv)
        st = ex["stats"]
        rows.append({
            "file": f["file"], "profile": f["profile"], "claims": st["claims"],
            "asserted_only_rate": st["asserted_only_rate"],
            "evidence_strength_index": st["evidence_strength_index"],
            "quotes_removed": ex["quote_check"]["removed_count"],
            "gate_passed": ex["gate"]["passed"], "gate_expected": f["expected_gate_passed"],
            "gate_correct": ex["gate"]["passed"] == f["expected_gate_passed"],
            "model": ex["meta"]["model"],
        })
        await asyncio.sleep(pause)
    by = {r["file"]: r for r in rows}
    esi = lambda name: by[name]["evidence_strength_index"] or 0.0  # noqa: E731
    return {
        "fixtures": rows,
        "gate_accuracy": f"{sum(r['gate_correct'] for r in rows)}/{len(rows)}",
        "discrimination_strong_minus_stuffed": round(esi("cv_06_strong_control.txt") - esi("cv_04_keyword_stuffed.txt"), 3),
        "fairness_switcher_minus_stuffed": round(esi("cv_05_career_switcher.txt") - esi("cv_04_keyword_stuffed.txt"), 3),
        "mean_asserted_only_rate": round(statistics.mean(r["asserted_only_rate"] or 0 for r in rows), 3),
    }


async def part_b(runs: int, pause: float) -> dict:
    spec = json.loads((ROOT / "evals" / "eval_task.json").read_text(encoding="utf-8"))
    task_id = pipeline.STORE.put({k: spec[k] for k in (
        "task_prompt", "communication_subtask", "embedded_complication", "accessible_entry_point",
        "expected_strong_answer", "probe_seeds")} | {"claim": {}, "project": {}})
    results: dict = {}
    models: set[str] = set()
    for label, ans in spec["answers"].items():
        per_dim: dict[str, list[int]] = {}
        indices = []
        for i in range(runs):
            print(f"  scoring {label} answer, run {i + 1}/{runs} ...", flush=True)
            r = await pipeline.score_attempt(task_id, 1, ans["answer"], ans["communication"],
                                             None, None, None, None)
            indices.append(r["evidence_index"])
            models.update(r["models_used"])
            for s in r["scores"]:
                per_dim.setdefault(s["dimension_id"], []).append(s["score"])
            await asyncio.sleep(pause)
        results[label] = {
            "index_runs": indices, "index_mean": round(statistics.mean(indices), 1), "index_sd": _sd(indices),
            "dimension_runs": per_dim, "dimension_sd": {k: _sd(v) for k, v in per_dim.items()},
        }
    all_sd = [sd for r in results.values() for sd in r["dimension_sd"].values()]
    return {
        "runs_per_answer": runs, "models_used": sorted(models), "answers": results,
        "mean_dimension_sd": round(statistics.mean(all_sd), 3) if all_sd else None,
        "max_dimension_sd": max(all_sd) if all_sd else None,
        "separation_strong_minus_weak": round(results["strong"]["index_mean"] - results["weak"]["index_mean"], 1),
    }


def summary_md(m: dict) -> str:
    a, b = m["part_a"], m["part_b"]
    lines = [
        "# SkillBridge AI - evaluation summary",
        f"Run: {m['run_at']} | Provider: {m['provider']} | Models: {', '.join(sorted(set(b['models_used']) | {r['model'] for r in a['fixtures']}))}",
        "",
        "## Scorer reliability (same answer, scored repeatedly)",
        f"- Mean score standard deviation across runs: **{b['mean_dimension_sd']}** points on a 0-4 scale (max {b['max_dimension_sd']})",
        f"- Strong answer index: {b['answers']['strong']['index_mean']} (runs: {b['answers']['strong']['index_runs']})",
        f"- Weak answer index: {b['answers']['weak']['index_mean']} (runs: {b['answers']['weak']['index_runs']})",
        f"- Separation, strong minus weak: **{b['separation_strong_minus_weak']}** index points",
        "",
        "## CV reading on 6 synthetic CVs",
        f"- Grounding gate matched expectation: **{a['gate_accuracy']}**",
        f"- Mean share of claims that are listed only, with no backing: **{round(a['mean_asserted_only_rate'] * 100)}%**",
        f"- Discrimination, strong CV minus keyword-stuffed CV (evidence strength 0-1): **{a['discrimination_strong_minus_stuffed']}**",
        f"- Fairness, career switcher minus keyword-stuffed CV: **{a['fairness_switcher_minus_stuffed']}**",
        "",
        "| CV | Claims | Listed only | Evidence strength | Gate (got / expected) |",
        "|---|---|---|---|---|",
    ]
    for r in a["fixtures"]:
        lines.append(f"| {r['file']} | {r['claims']} | {round((r['asserted_only_rate'] or 0) * 100)}% | "
                     f"{r['evidence_strength_index']} | {r['gate_passed']} / {r['gate_expected']} |")
    if m["provider"] == "mock":
        lines.insert(1, "**TEST MODE: mock test doubles, not AI. These numbers are meaningless. Do not present them.**")
    else:
        lines += ["", "Synthetic inputs, real model outputs. Small sample: report these as a pilot check, not a validation study."]
    return "\n".join(lines)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between calls (free-tier friendly)")
    ap.add_argument("--allow-mock", action="store_true", help="wiring test only; numbers are meaningless")
    args = ap.parse_args()

    s = get_settings()
    if s.provider == "mock" and not args.allow_mock:
        print(json.dumps({"status": "not_run", "reason": "LLM_PROVIDER=mock gives test doubles, not AI. Use a real provider."}))
        return 2
    if not s.has_key:
        print(json.dumps({"status": "not_run", "reason": "No API key configured. Add GEMINI_API_KEY to .env."}))
        return 2

    print(f"Provider {s.provider}, model {s.active_model}. About {6 + 2 * args.runs * 4} API calls.\n")
    t0 = time.time()
    try:
        print("Part A: reading the 6 fixture CVs")
        a = await part_a(args.pause)
        print("Part B: scorer reliability")
        b = await part_b(args.runs, args.pause)
    except LLMError as e:
        print(json.dumps({"status": "incomplete", "error": e.to_dict()}, indent=2))
        return 2
    metrics = {"status": "complete", "run_at": datetime.now().isoformat(timespec="seconds"),
               "provider": s.provider, "seconds": round(time.time() - t0, 1), "part_a": a, "part_b": b}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    md = summary_md(metrics)
    (OUT / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md + f"\n\nSaved to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
