import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from .models import *
from .guards import validate_extraction,validate_task,guard_score,guard_feedback,exact,safe_text,safe_quoted_text,seal,verify_receipt
from .rules import weighted,verify_claims,calibration,improvement,ordered_choices
from .llm import Gemini,render_prompt

ROOT=Path(__file__).resolve().parents[1]

def role(role_id):
    # One role ships; dimensions and weights are loaded from data, not hardcoded.
    import re
    if not re.fullmatch(r'[a-z][a-z0-9-]*',role_id):raise ValueError('Unknown role identifier.')
    path=ROOT/'rubrics'/f'{role_id}.json'
    if not path.is_file():raise ValueError('This demo ships the AI/ML Intern role only.')
    return json.loads(path.read_text())

class AssessmentService:
    def __init__(self,llm=None):self.llm=llm or Gemini()
    async def create(self,request: CreateRequest):
        rubric=role(request.role_id)
        extraction=await self.llm.generate(render_prompt('01_extract_claims.md',SKILL_TAXONOMY=rubric['skill_taxonomy']),{'cv_text':request.text},Extraction,0)
        validate_extraction(extraction,request.text,rubric['skill_taxonomy'])
        has_grounding=any(c.linked_project_id and c.skill in rubric['skill_taxonomy'] and next(p for p in extraction.projects if p.project_id==c.linked_project_id).task_grounding_potential!='low' for c in extraction.claims)
        return seal(Assessment(assessment_id=str(uuid4()),role_id=request.role_id,rubric_version=rubric['rubric_version'],created_at=datetime.now(timezone.utc).isoformat(),state='claims_ready' if has_grounding else 'needs_detail',source_text=request.text,claims=extraction.claims,projects=extraction.projects,warnings=[safe_text(x) for x in extraction.extraction_warnings]))

    async def task(self,request: TaskRequest):
        a=request.assessment.model_copy(deep=True);verify_receipt(a)
        if a.attempts:raise ValueError('Start a new session before changing the task.')
        claim=next((c for c in a.claims if c.claim_id==request.claim_id),None)
        if not claim or claim.skill=='other' or not claim.linked_project_id:raise ValueError('This claim needs a described project before a task can be grounded.')
        project=next(p for p in a.projects if p.project_id==claim.linked_project_id)
        if project.task_grounding_potential=='low' or not project.tools_named:raise ValueError('Add the tools and one concrete step or decision you took, then extract again.')
        task=await self.llm.generate(render_prompt('02_generate_task.md'),{'claim':claim.model_dump(),'project':project.model_dump(),'role_id':a.role_id},Task,.2)
        validate_task(task,a,claim.claim_id)
        a.task=task;a.state='task_ready';return seal(a)

    async def submit(self,request: SubmitRequest,revision=False):
        a=request.assessment.model_copy(deep=True);verify_receipt(a)
        if not a.task:raise ValueError('Create a grounded task before submitting.')
        if len(a.attempts)!=(1 if revision else 0):raise ValueError('This demo supports one first attempt and one revision.')
        if revision:
            allowed=[c.choice_id for c in a.attempts[0].feedback.next_step_choices]
            if request.chosen_next_step_id not in allowed:raise ValueError('Choose one next step before revising.')
        rubric=role(a.role_id)
        claim=next(c for c in a.claims if c.claim_id==a.task.targets_claim_id)
        prior=a.attempts[0] if revision else None
        async def score_one(d):
            if d['requires_resubmission'] and not revision:
                return Score(dimension_id=d['id'],score=None,anchor_matched='Not observed yet: a revision is required.',evidence_spans=[],missing_for_next_level='Revise your approach after reviewing the critique.',confidence='low')
            user={'task':a.task.model_dump(),'target_claim':claim.model_dump(),'submission':request.text}
            if d['requires_resubmission']:user['previous_submission']=prior.text;user['previous_critique']=prior.feedback.model_dump()
            scored=await self.llm.generate(render_prompt('03_score_evidence.md',DIMENSION_ID=d['id'],DIMENSION_LABEL=d['label'],DIMENSION_QUESTION=d['question'],DIMENSION_ANCHORS=d['anchors']),user,Score,0)
            return guard_score(scored,d,request.text)
        scores=await asyncio.gather(*(score_one(d) for d in rubric['dimensions']))
        feedback,probe_set=await asyncio.gather(
            self.llm.generate(render_prompt('04_feedback.md'),{'submission':request.text,'scores':[s.model_dump() for s in scores if s.score is not None]},Feedback,.2),
            self.llm.generate(render_prompt('05_probe.md',MODE='generate',OWNERSHIP_ANCHORS=rubric['ownership_rubric']['anchors']),{'task':a.task.model_dump(),'submission':request.text},Probes,0)
        )
        feedback=guard_feedback(feedback,request.text,scores)
        feedback.next_step_choices=ordered_choices(feedback.next_step_choices,scores)
        if [p.type for p in probe_set.probes]!=['choice','boundary'] or [p.probe_id for p in probe_set.probes]!=['q1','q2']:raise ValueError('The probe pair did not match the protocol.')
        for p in probe_set.probes:
            if not exact(p.anchored_quote,request.text) or p.anchored_quote not in p.question:raise ValueError('A follow-up must visibly quote your own answer.')
            p.question=safe_quoted_text(p.question,p.anchored_quote)
        index=weighted(scores,rubric,include_coach=False)
        a.attempts.append(Attempt(attempt=len(a.attempts)+1,text=request.text,self_predicted_score=request.self_predicted_score,scores=scores,feedback=feedback,probes=probe_set.probes,calibration=calibration(request.self_predicted_score,index),task_evidence_index=index,weighted_score=weighted(scores,rubric)))
        a.verification=verify_claims(a.claims,a.task.targets_claim_id,scores,rubric)
        a.state='revised_review' if revision else 'first_review'
        if revision:a.delta=improvement(a.attempts[0].task_evidence_index,index)
        return seal(a)

    async def probes(self,request: ProbeRequest):
        a=request.assessment.model_copy(deep=True);verify_receipt(a)
        if not a.attempts:raise ValueError('Submit an answer before the follow-up.')
        current=a.attempts[-1]
        if current.probe_answers:raise ValueError('This follow-up pair was already reviewed.')
        if {x.probe_id for x in request.answers}!={p.probe_id for p in current.probes}:raise ValueError('Answer both distinct follow-up questions.')
        rubric=role(a.role_id)
        ownership=await self.llm.generate(render_prompt('05_probe.md',MODE='evaluate',OWNERSHIP_ANCHORS=rubric['ownership_rubric']['anchors']),{'task':a.task.model_dump(),'submission':current.text,'questions':[p.model_dump() for p in current.probes],'answers':[x.model_dump() for x in request.answers]},Ownership,0)
        source='\n'.join(x.text for x in request.answers)
        spans=[s for s in ownership.evidence_spans if len(s.quote.strip())>=8 and exact(s.quote,source)]
        score=ownership.ownership_score
        if score>1 and not spans:score=1
        confidence='high' if score==3 else 'medium' if score==2 else 'low'
        current.probe_answers=request.answers
        for span in spans:span.why_it_supports=safe_text(span.why_it_supports)
        current.integrity=Integrity(ownership_score=score,confidence=confidence,evidence_spans=spans,advisory_note=rubric['ownership_rubric']['anchors'][str(score)]+' '+rubric['ownership_rubric']['innocent_reading'])
        return seal(a)
