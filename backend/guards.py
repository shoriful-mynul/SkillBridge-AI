import hashlib
import hmac
import json
import os
import re
import secrets
from .models import Assessment, Extraction, Task, Score, Feedback

BANNED = re.compile(r'\b(failed|inadequate|poor|weak|unqualified|lacks)\b',re.I)
SIGNING_KEY = (os.getenv('ASSESSMENT_SIGNING_KEY') or secrets.token_hex(32)).encode()

def safe_text(text: str) -> str:
    return BANNED.sub('not yet evidenced',text)

def safe_quoted_text(text: str, quote: str) -> str:
    # Filter authored prose while keeping all literal candidate spans intact.
    return quote.join(safe_text(part) for part in text.split(quote))

def exact(quote: str, source: str) -> bool:
    return bool(quote.strip()) and quote in source

def seal(a: Assessment) -> Assessment:
    payload=json.dumps(a.model_dump(exclude={'receipt'}),sort_keys=True,separators=(',',':')).encode()
    a.receipt=hmac.new(SIGNING_KEY,payload,hashlib.sha256).hexdigest()
    return a

def verify_receipt(a: Assessment):
    provided=a.receipt
    expected=seal(a.model_copy(deep=True)).receipt
    if a.engine!='live_gemini' or not hmac.compare_digest(provided,expected):
        raise ValueError('Assessment context changed. Start a new assessment to refresh its receipt.')

def validate_extraction(e: Extraction, source: str, taxonomy: list[str]):
    ids=[c.claim_id for c in e.claims]
    projects={p.project_id:p for p in e.projects}
    if len(set(ids))!=len(ids) or len(projects)!=len(e.projects):
        raise ValueError('Extraction returned duplicate identifiers.')
    for c in e.claims:
        if not exact(c.evidence_span,source):raise ValueError('Extraction returned an unsupported claim quote.')
        if c.skill not in taxonomy+['other']:raise ValueError('Extraction returned an unsupported skill identifier.')
        if c.linked_project_id and c.linked_project_id not in projects:raise ValueError('Extraction returned an unknown project link.')
    for p in e.projects:
        if not exact(p.description_span,source) or not exact(p.stated_approach,source):raise ValueError('Extraction returned an unsupported project quote.')
        if any(tool.lower() not in p.description_span.lower() for tool in p.tools_named):raise ValueError('A named tool is absent from the project quote.')

def validate_task(t: Task,a: Assessment,claim_id: str):
    claim=next(c for c in a.claims if c.claim_id==claim_id)
    project=next(p for p in a.projects if p.project_id==claim.linked_project_id)
    if t.targets_claim_id!=claim_id or t.grounded_in_project_id!=project.project_id:raise ValueError('Task is linked to the wrong claim or project.')
    if not all(exact(q,project.description_span) and q in t.task_prompt for q in t.grounding_quotes):raise ValueError('Task grounding quotes must be verbatim, project-specific, and visible in the task.')
    if max(map(len,t.grounding_quotes))<30 or not any(tool in t.task_prompt for tool in project.tools_named):raise ValueError('Task does not quote enough of the stated tools and approach.')
    if project.stated_approach not in t.task_prompt:raise ValueError('Task does not reference the described approach verbatim.')
    if t.issue_source=='explicitly_described' and not exact(t.complication,project.description_span):raise ValueError('A described issue must be quoted from the project; otherwise mark it hypothetical.')

def guard_score(score: Score,dimension: dict,submission: str)->Score:
    if score.dimension_id!=dimension['id']:raise ValueError('Scorer returned a different dimension.')
    score.evidence_spans=[s for s in score.evidence_spans if len(s.quote.strip())>=8 and exact(s.quote,submission)]
    if score.score is None:raise ValueError('An assessed dimension cannot have a null score.')
    if score.score>1 and not score.evidence_spans:
        score.score=1;score.confidence='low';score.guard_applied=True
    score.anchor_matched=dimension['anchors'][str(score.score)]
    score.missing_for_next_level=safe_text(score.missing_for_next_level)
    for span in score.evidence_spans:span.why_it_supports=safe_text(span.why_it_supports)
    return score

def guard_feedback(f: Feedback,submission: str,scores: list[Score]):
    if not exact(f.opening_quote,submission):raise ValueError('Feedback strength quote is not in the answer.')
    if {c.choice_id for c in f.next_step_choices}!={'a','b'} or len({c.instruction.strip().casefold() for c in f.next_step_choices})!=2:raise ValueError('Feedback needs two distinct named next-step choices.')
    levels={s.dimension_id:s.score for s in scores if s.score is not None}
    choice_dimensions={choice.dimension_id for choice in f.next_step_choices}
    if len(choice_dimensions)!=1 or not levels or levels.get(next(iter(choice_dimensions)))!=min(levels.values()):raise ValueError('Both choices must practise the same lowest-scoring observed dimension.')
    for choice in f.next_step_choices:
        if choice.dimension_id not in levels:raise ValueError('Choice refers to an unassessed dimension.')
        if choice.target_level!=min(4,levels[choice.dimension_id]+1):raise ValueError('Next step must target exactly one anchor level up, capped at 4.')
        choice.title=safe_text(choice.title);choice.instruction=safe_text(choice.instruction)
    f.strength_statement=safe_text(f.strength_statement);f.strategy_feedback=safe_text(f.strategy_feedback)
    prose=' '.join([f.strength_statement,f.strategy_feedback]+[part for choice in f.next_step_choices for part in [choice.title,choice.instruction]])
    if len(prose.split())>180:raise ValueError('Feedback exceeded the concise strategy-feedback limit.')
    return f
