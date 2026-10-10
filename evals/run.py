import asyncio
import copy
import json
import os
import statistics
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from backend.models import *
from backend.service import AssessmentService,role
from backend.llm import render_prompt,ProviderUnavailable
from backend.guards import guard_score,validate_task
from backend.rules import weighted,verify_claims

ROOT=Path(__file__).resolve().parents[1]

async def main():
    output=ROOT/'evals'/'results';output.mkdir(exist_ok=True)
    if not os.getenv('GEMINI_API_KEY'):
        (output/'metrics.json').write_text(json.dumps({'status':'not_run','reason':'GEMINI_API_KEY is not configured. No live scores, variances or gaps are available.','synthetic_rehearsal_excluded':True},indent=2))
        print('Evaluation NOT RUN: live Gemini key is not configured. No metric values invented.')
        return 2
    cases=json.loads((ROOT/'fixtures'/'cases.json').read_text());rubric=role('ai-ml-intern');service=AssessmentService();records=[]
    for case in cases:
        a=await service.create(CreateRequest(text=case['cv']))
        claims=[c for c in a.claims if c.skill==case['skill'] and c.linked_project_id]
        if a.state=='needs_detail' or not claims:
            checks=[{'run':1,'state':a.state,'claim_count':len(a.claims)}]
            for repeat in [2,3]:
                repeated=await service.create(CreateRequest(text=case['cv']))
                checks.append({'run':repeat,'state':repeated.state,'claim_count':len(repeated.claims)})
            records.append({'id':case['id'],'status':'needs_detail','claim_count':len(a.claims),'assessed_claim_count':0,'unevidenced_claim_rate':1.0 if a.claims else None,'tested_unevidenced_claim_rate':None,'weighted_mean':None,'dimension_stats':None,'grounding_checks':checks,'runs':[]})
            (output/'raw-runs.json').write_text(json.dumps(records,indent=2))
            continue
        claim=claims[0];project=next(p for p in a.projects if p.project_id==claim.linked_project_id)
        # Freeze a human-authored fixture complication for every repeat. This
        # is scoring reliability, not task-generation or extraction accuracy.
        task=Task(**case['task']);task.targets_claim_id=claim.claim_id;task.grounded_in_project_id=project.project_id
        task.grounding_quotes=[project.tools_named[0],project.stated_approach]
        task.task_prompt=f'You named "{project.tools_named[0]}" and wrote "{project.stated_approach}". For this exercise, consider a hypothetical change: {task.complication}. Explain a check, a correction, an alternative and the validation boundary in this same project.'
        validate_task(task,a,claim.claim_id)
        runs=[]
        critique='Make the project-specific choice and its validation boundary explicit, compare an alternative, and add a concrete edge-case check.'
        for repetition in range(3):
            scored=[]
            for dimension in rubric['dimensions']:
                coach=dimension['requires_resubmission'];submission=case['revised'] if coach else case['initial']
                payload={'task':task.model_dump(),'target_claim':claim.model_dump(),'submission':submission}
                if coach:payload.update(previous_submission=case['initial'],previous_critique=critique)
                score=await service.llm.generate(render_prompt('03_score_evidence.md',DIMENSION_ID=dimension['id'],DIMENSION_LABEL=dimension['label'],DIMENSION_QUESTION=dimension['question'],DIMENSION_ANCHORS=dimension['anchors']),payload,Score,0)
                scored.append(guard_score(score,dimension,submission))
            first=[s for s in scored if s.dimension_id!='coachability_delta']
            verification=verify_claims(a.claims,claim.claim_id,first,rubric)
            runs.append({'run':repetition+1,'scores':[s.model_dump() for s in scored],'task_evidence_index':weighted(first,rubric,False),'verification':[v.model_dump() for v in verification]})
        dimension_stats={}
        for d in rubric['dimensions']:
            values=[next(s['score'] for s in run['scores'] if s['dimension_id']==d['id']) for run in runs]
            dimension_stats[d['id']]={'scores':values,'population_variance':statistics.pvariance(values),'population_stddev':statistics.pstdev(values),'range':max(values)-min(values)}
        # Majority over the three recorded verdicts, with no cherry-picked run.
        last=copy.deepcopy(runs[0]['verification'])
        for item in last:
            statuses=[next(v['status'] for v in run['verification'] if v['claim_id']==item['claim_id']) for run in runs]
            frequencies=Counter(statuses)
            item['status']=max(['not_yet','partial','verified'],key=lambda x:(frequencies[x],-['not_yet','partial','verified'].index(x)))
        assessed=[v for v in last if v['assessed']]
        mean=statistics.mean(x['task_evidence_index'] for x in runs)
        expected=case['range']
        majority=next(v['status'] for v in assessed) if assessed else None
        records.append({'id':case['id'],'status':'scored','claim_count':len(a.claims),'assessed_claim_count':len(assessed),'unevidenced_claim_rate':sum(v['status']=='not_yet' for v in last)/len(last) if last else None,'tested_unevidenced_claim_rate':sum(v['status']=='not_yet' for v in assessed)/len(assessed) if assessed else None,'weighted_mean':mean,'expected_range_pass':bool(expected and expected[0]<=mean<=expected[1]),'majority_verdict':majority,'expected_verdict_pass':majority==case['expected'],'dimension_stats':dimension_stats,'frozen_task':task.model_dump(),'runs':runs})
        (output/'raw-runs.json').write_text(json.dumps(records,indent=2))
    means={r['id']:r['weighted_mean'] for r in records}
    def gap(i,j):return None if means.get(i) is None or means.get(j) is None else round(means[i]-means[j],2)
    control=gap('06_strong_control','04_keyword_stuffed');fairness=gap('05_career_switcher','04_keyword_stuffed')
    claim_count=sum(r['claim_count'] for r in records)
    assessed_count=sum(r['assessed_claim_count'] for r in records)
    not_yet_count=round(sum((r['unevidenced_claim_rate'] or 0)*r['claim_count'] for r in records))
    tested_not_yet=round(sum((r['tested_unevidenced_claim_rate'] or 0)*r['assessed_claim_count'] for r in records))
    pooled={'unevidenced_claim_count':not_yet_count,'claim_count':claim_count,'unevidenced_claim_rate':not_yet_count/claim_count if claim_count else None,'assessed_claim_count':assessed_count,'coverage':assessed_count/claim_count if claim_count else None,'tested_unevidenced_claim_count':tested_not_yet,'tested_unevidenced_claim_rate':tested_not_yet/assessed_count if assessed_count else None,'interpretation':'Unsampled claims are not yet evidenced, never inferred false or absent ability.'}
    metrics={'status':'completed','created_at':datetime.now(timezone.utc).isoformat(),'model':service.llm.model,'temperature':0.0,'runs_per_fixture':3,'synthetic_rehearsal_excluded':True,'scope':'Live scoring on fixed task+answer; four dimensions on first answer, Coachability on a fixed revision and critique. Extractor called once per fixture; task synthesis is not included in variance.','fixtures':records,'discrimination_gap':control,'adjacent_evidence_gap':fairness,'control_gate_pass':control is not None and control>=35,'fairness_gate_pass':fairness is not None and fairness>=20,'human_rating_agreement':'not measured; repeatability is not correctness'}
    metrics['scope']+=' Blocked fixtures repeat grounding checks three times with no numeric score variance.'
    metrics['unevidenced_claim_summary']=pooled
    (output/'metrics.json').write_text(json.dumps(metrics,indent=2));print(json.dumps({k:v for k,v in metrics.items() if k!='fixtures'},indent=2))
    return 0

if __name__=='__main__':
    try:code=asyncio.run(main())
    except (ProviderUnavailable,ValueError) as exc:
        output=ROOT/'evals'/'results';output.mkdir(exist_ok=True)
        (output/'metrics.json').write_text(json.dumps({'status':'incomplete','reason':str(exc),'synthetic_rehearsal_excluded':True,'instruction':'Inspect raw-runs.json for completed fixtures; do not report incomplete aggregates as measured results.'},indent=2))
        print('Evaluation incomplete: a provider or evidence-contract step could not finish. No aggregate metric invented.');code=2
    raise SystemExit(code)
