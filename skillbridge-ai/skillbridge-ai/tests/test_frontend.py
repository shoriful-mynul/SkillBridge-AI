"""Exercise SVG, export and roadmap-only retry with Node, when available.

Node is a development check only: the FastAPI app still needs no Node or npm.
"""
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Optional JavaScript check needs Node")
def test_final_svg_export_and_retry():
    source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text()
    functions = source[source.index("function performanceGraphs("):source.index("function panelFinal()")]
    report = source[source.index("function reportMarkdown()"):source.index("/* ---------------- events")]
    script = r'''
const assert = require('node:assert/strict');
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metaLine = () => '';
const skillName = c => c.raw_label;
const modelsUsed = () => ['mock'];
const S = {task:{task_id:'t',claim:{raw_label:'Python',evidence_span:'Real project'},project:{title:'Project'}},
  revAnswer:'Actual revision', revComm:'', roles:[], roleId:'ai-ml-intern'};
let calls = [], fail = true;
const api = async (path, body) => { calls.push({path,body}); if(fail) throw new Error('provider unavailable'); return {ok:true}; };
'''
    script += functions + report + r'''
const dimensions = ['claim_substantiation','technical_correctness','reasoning_transparency','communication','coachability_delta'];
const labels = ['Claim Substantiation','Technical Correctness','Reasoning Transparency','Communication','Coachability Delta'];
S.s1 = {scores: dimensions.slice(0,4).map((dimension_id,i)=>({dimension_id,label:labels[i],score:2})), evidence_index:50, verification:{label:'Partial',caveat:'On this task'}};
S.s2 = {scores: dimensions.map((dimension_id,i)=>({dimension_id,label:labels[i],score:i===0?2:3})),evidence_index:75, verification:{label:'Partial',caveat:'On this task'}};
const svg = performanceGraphs(S.s1,S.s2);
assert.equal((svg.match(/<svg /g)||[]).length,2);
assert.equal((svg.match(/role="img"/g)||[]).length,2);
assert.equal((svg.match(/<title>/g)||[]).length,2);
assert.equal((svg.match(/preserveAspectRatio=/g)||[]).length,2);
assert(svg.includes('Coachability Delta: first not observed, revised 3'));
assert(svg.includes('First: not observed'));
assert(svg.includes('Needs 3: 1 to go'));
assert(svg.includes('Met (needs 3)'));
assert(!/<svg[^>]*\bwidth=/.test(svg));
assert(!svg.includes('NaN'));
S.s2.scores[0].label='<script>alert(1)</script>';
assert(!performanceGraphs(S.s1,S.s2).includes('<script>'));
S.s2.scores[0].label=labels[0];
const r={branch:'practice',opening_strength:{quote:'',statement:''},growth_areas:[],habits:[],
  gating_dimensions:[{explanation:'Claim Substantiation is at 2; Evidenced needs 3.'}],
  days:Array.from({length:7},(_,i)=>({day:i+1,action:'Try one check.',outcome:'Saved result.'})),
  what_would_flip:{evidence:'One reproducible check.',framing:'On this task.'},
  cap_note:'',next_claim:{label:'Another claim',why:'Grounded in this task.'},choice:'Choose or consolidate.',caveat:'On this task only.'};
S.roadmap=r;
assert(roadmapPanel().includes('Day 7'));
assert(reportMarkdown().includes('7. Try one check. Check: Saved result.'));
assert(reportMarkdown().includes('Claim Substantiation is at 2; Evidenced needs 3.'));
S.roadmap={...r,branch:'verified',opening_strength:{quote:'Actual revision',statement:'This decision is evidenced on this task.'},growth_areas:[{label:'Communication',action:'State a boundary.',next_level_evidence:'One limit.'}],habits:['Save the check.']};
assert(roadmapPanel().includes('Actual revision'));
assert(reportMarkdown().includes('Save the check.'));
(async()=>{
  const before=S.s2;
  S.roadmap=null;
  await requestRoadmap();
  assert.equal(S.s2,before);
  assert(S.roadmapError.includes('scored report is preserved'));
  assert(roadmapPanel().includes('Retry roadmap only'));
  fail=false;
  await requestRoadmap();
  assert.equal(S.s2,before);
  assert.equal(S.roadmapError,null);
  assert.deepEqual(calls.map(c=>c.path),['/api/roadmap','/api/roadmap']);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    result = subprocess.run([shutil.which("node")], input=script, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
