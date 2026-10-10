import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from jsonschema import validate
from backend.main import app
from backend.service import AssessmentService,role
from backend.models import *
from backend.guards import guard_score,guard_feedback,validate_task,seal,verify_receipt,BANNED,safe_quoted_text
from backend.rules import weighted,improvement

ROOT=Path(__file__).resolve().parents[1]
CASES=json.loads((ROOT/'fixtures'/'cases.json').read_text())
REPLAY=json.loads((ROOT/'public'/'rehearsal'/'honest-junior.json').read_text())
RUBRIC=role('ai-ml-intern')

class FakeProvider:
    model='contract-test-double'
    def __init__(self):self.calls=[]
    async def generate(self,prompt,user,output,temperature=0):
        self.calls.append((prompt,user,output,temperature))
        if output==Extraction:return Extraction(**CASES[2]['extraction'])
        if output==Task:return Task(**CASES[2]['task'])
        if output==Score:
            revised='previous_submission' in user or user['submission']==CASES[2]['revised']
            attempt=REPLAY['records'][2 if revised else 1]['attempts'][-1]
            dimension=next(d for d in RUBRIC['dimensions'] if f"Dimension id: {d['id']}\n" in prompt)
            return Score(**next(s for s in attempt['scores'] if s['dimension_id']==dimension['id']))
        if output==Feedback:return Feedback(**REPLAY['records'][2 if user['submission']==CASES[2]['revised'] else 1]['attempts'][-1]['feedback'])
        if output==Probes:return Probes(probes=REPLAY['records'][2 if user['submission']==CASES[2]['revised'] else 1]['attempts'][-1]['probes'])
        if output==Ownership:return Ownership(ownership_score=3,evidence_spans=[Span(quote=user['answers'][0]['text'],why_it_supports='Specific boundary described.')],reasoning='The answer explains its stated training boundary and an alternative.')
        raise AssertionError(output)

def test_complete_http_flow_and_single_dimension_protocol():
    fake=FakeProvider()
    with patch('backend.main.service',AssessmentService(fake)),TestClient(app) as client:
        a=client.post('/api/assessments',json={'text':CASES[2]['cv']}).json()
        assert a['state']=='claims_ready'
        a=client.post('/api/assessments/task',json={'assessment':a,'claim_id':'c1'}).json()
        assert a['task']['grounding_quotes'][1] in a['task']['task_prompt']
        response=client.post('/api/assessments/submit',json={'assessment':a,'text':CASES[2]['initial'],'self_predicted_score':3})
        assert response.status_code==200,response.text
        a=response.json();assert a['attempts'][0]['scores'][4]['score'] is None
        assert a['verification'][0]['status']=='partial'
        a=client.post('/api/assessments/probes',json={'assessment':a,'answers':CASES[2]['probe_answers']}).json()
        assert a['attempts'][0]['integrity']['ownership_score']==3
        before=a['attempts'][0]['scores']
        response=client.post('/api/assessments/revise',json={'assessment':a,'text':CASES[2]['revised'],'self_predicted_score':3.5,'chosen_next_step_id':'a'})
        assert response.status_code==200,response.text
        a=response.json();validate(a,json.loads((ROOT/'schema'/'assessment.schema.json').read_text()))
        assert a['delta']['change']>0
        assert a['attempts'][0]['scores']==before
        assert a['attempts'][1]['scores'][4]['score']==3
        for prompt,payload,output,temp in fake.calls:
            if output==Score:
                assert temp==0
                assert sum(f"Dimension id: {d['id']}\n" in prompt for d in RUBRIC['dimensions'])==1
                others=[d for d in RUBRIC['dimensions'] if f"Dimension id: {d['id']}\n" not in prompt]
                assert all(d['anchors']['4'] not in prompt for d in others)

def test_missing_prediction_cannot_reach_scorer():
    with TestClient(app) as c:
        a=Assessment.model_validate(REPLAY['records'][0]);a.engine='live_gemini';seal(a)
        r=c.post('/api/assessments/submit',json={'assessment':a.model_dump(),'text':CASES[2]['initial']})
        assert r.status_code==422

def test_hallucinated_quote_caps_score_and_uses_correct_anchor():
    d=RUBRIC['dimensions'][0]
    s=Score(dimension_id=d['id'],score=4,anchor_matched='invented',evidence_spans=[Span(quote='a nonexistent technical line',why_it_supports='weak detail')],missing_for_next_level='poor reasoning',confidence='high')
    result=guard_score(s,d,'This submission describes a different starting operation.')
    assert result.score==1 and result.guard_applied and result.confidence=='low'
    assert result.anchor_matched==d['anchors']['1']
    assert not BANNED.search(result.missing_for_next_level)

def test_verbatim_quote_survives_generated_word_filter():
    d=RUBRIC['dimensions'][0];text='My poor first approach is to fit the imputer on the training set only.'
    s=Score(dimension_id=d['id'],score=2,anchor_matched='',evidence_spans=[Span(quote=text,why_it_supports='weak explanation')],missing_for_next_level='Add a specific choice.',confidence='medium')
    assert guard_score(s,d,text).evidence_spans[0].quote==text
    assert not BANNED.search(s.evidence_spans[0].why_it_supports)

def test_task_cannot_invent_or_transfer_a_source_quote():
    a=Assessment.model_validate(REPLAY['records'][0]);t=a.task.model_copy(deep=True)
    t.grounding_quotes[1]='An invented project approach that the student never wrote.'
    with pytest.raises(ValueError):validate_task(t,a,'c1')

def test_client_cannot_modify_scores_or_task_to_create_a_delta():
    a=Assessment.model_validate(REPLAY['records'][1]);a.engine='live_gemini';seal(a)
    a.attempts[0].scores[0].score=4
    with pytest.raises(ValueError):verify_receipt(a)

def test_like_for_like_delta_excludes_coach_weight():
    scores=[Score(dimension_id=d['id'],score=2,anchor_matched='',evidence_spans=[],missing_for_next_level='',confidence='medium') for d in RUBRIC['dimensions']]
    first=weighted(scores,RUBRIC,False)
    scores[-1].score=4
    assert weighted(scores,RUBRIC,False)==first
    assert improvement(first,weighted(scores,RUBRIC,False)).change==0

def test_feedback_requires_actual_quote_and_one_level_up():
    a=Assessment.model_validate(REPLAY['records'][1]);f=a.attempts[0].feedback.model_copy(deep=True)
    f.opening_quote='This is not in the submission.'
    with pytest.raises(ValueError):guard_feedback(f,a.attempts[0].text,a.attempts[0].scores)
    f=a.attempts[0].feedback.model_copy(deep=True);f.next_step_choices[0].target_level=4
    with pytest.raises(ValueError):guard_feedback(f,a.attempts[0].text,a.attempts[0].scores)

def test_rehearsal_schema_quotes_and_disclosure():
    assert 'No live LLM ran' in REPLAY['disclosure']
    for raw in REPLAY['records']+[REPLAY['ownership_record'],REPLAY['ownership_record_revision']]:
        a=Assessment.model_validate(raw)
        assert a.engine=='synthetic_rehearsal'
        for attempt in a.attempts:
            assert attempt.feedback.opening_quote in attempt.text
            for s in attempt.scores:
                if s.score is not None and s.score>1:assert s.evidence_spans
                assert all(e.quote in attempt.text for e in s.evidence_spans)
            for p in attempt.probes:assert p.anchored_quote in attempt.text and p.anchored_quote in p.question
            assert all(e.quote in '\n'.join(p.text for p in attempt.probe_answers) for e in attempt.integrity.evidence_spans)
    assert REPLAY['ownership_record_revision']['delta']==REPLAY['records'][2]['delta']
    assert len(REPLAY['ownership_record_revision']['attempts'])==2

def test_quoted_candidate_words_do_not_disable_generated_prose_filter():
    quote='My weak initial idea was a random split.'
    result=safe_quoted_text('You wrote "'+quote+'". Why was the alternative poor?',quote)
    assert quote in result
    assert not BANNED.search(result.replace(quote,''))

def test_provider_rest_payload_uses_single_dimension_schema_and_zero_temperature(monkeypatch):
    import httpx
    from backend.llm import Gemini
    monkeypatch.setenv('GEMINI_API_KEY','synthetic-test-key')
    d=RUBRIC['dimensions'][0]
    value=Score(dimension_id=d['id'],score=1,anchor_matched=d['anchors']['1'],evidence_spans=[],missing_for_next_level='Show a concrete operation.',confidence='low')
    seen=[]
    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':value.model_dump_json()}]}}]})
    original=httpx.AsyncClient
    def local_client(**kwargs):return original(transport=httpx.MockTransport(respond),**kwargs)
    with patch('backend.llm.httpx.AsyncClient',local_client):
        result=asyncio.run(Gemini().generate('One-dimension system prompt',{'submission':'A synthetic answer for this contract test.'},Score,0))
    assert result==value
    assert seen[0]['generationConfig']['temperature']==0
    assert seen[0]['generationConfig']['responseFormat']['text']['schema']==Score.model_json_schema()
    assert 'synthetic-test-key' not in json.dumps(seen)

def test_api_outage_returns_no_fabricated_score_and_keeps_input_untouched(monkeypatch):
    from backend.llm import ProviderUnavailable
    class Unavailable:
        model='test-outage'
        async def generate(self,*args,**kwargs):raise ProviderUnavailable('AI unavailable. Your draft is unchanged.')
    body={'text':CASES[2]['cv']}
    with patch('backend.main.service',AssessmentService(Unavailable())),TestClient(app) as c:
        r=c.post('/api/assessments',json=body)
        assert r.status_code==503
        assert r.json()['error']['code']=='AI_UNAVAILABLE'
        assert 'attempts' not in r.json()
        assert body['text']==CASES[2]['cv']

def test_role_is_data_and_telemetry_fields_are_absent():
    assert sum(d['weight'] for d in RUBRIC['dimensions'])==pytest.approx(1)
    assert all(set(d['anchors'])=={'0','1','2','3','4'} for d in RUBRIC['dimensions'])
    schema=(ROOT/'schema'/'assessment.schema.json').read_text()
    assert 'paste_events' not in schema and 'elapsed_seconds' not in schema
