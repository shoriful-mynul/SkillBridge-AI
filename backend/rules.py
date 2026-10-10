from .models import Score, Verification, Delta, Calibration

def weighted(scores: list[Score],rubric: dict,include_coach: bool=True)->float:
    weights={d['id']:d['weight'] for d in rubric['dimensions']}
    active=[s for s in scores if s.score is not None and (include_coach or s.dimension_id!='coachability_delta')]
    denominator=sum(weights[s.dimension_id] for s in active)
    if not denominator:raise ValueError('No dimension scores to aggregate.')
    return round(100*sum(weights[s.dimension_id]*s.score for s in active)/(4*denominator),2)

def verify_claims(claims,target_id,scores,rubric):
    by_id={s.dimension_id:s.score for s in scores}
    substantiation=by_id.get('claim_substantiation') or 0
    correctness=by_id.get('technical_correctness') or 0
    result=[]
    for claim in claims:
        assessed=claim.claim_id==target_id
        status='not_yet'
        if assessed:
            for rule in rubric['verification_status']['rules']:
                if all((by_id.get(key) or 0)>=minimum for key,minimum in rule['minimum_scores'].items()):
                    status=rule['status'];break
        rule=next(r for r in rubric['verification_status']['rules'] if r['status']==status)
        result.append(Verification(claim_id=claim.claim_id,status=status,display_label=rule['label'] if assessed else 'Not yet assessed',assessed=assessed,caveat=rule['display_caveat'] if assessed else 'This claim has not been sampled. No capability inference is made.'))
    return result

def calibration(predicted: float,index: float)->Calibration:
    demonstrated=round(index/25,2)
    gap=round(predicted-demonstrated,2)
    direction='close to' if abs(gap)<=.5 else 'above' if gap>0 else 'below'
    return Calibration(self_predicted=predicted,demonstrated=demonstrated,gap=gap,framing=f'Your prediction is {direction} the evidence shown in this attempt. This is calibration on one task, not a statement about honesty or overall ability.')

def improvement(before: float,after: float)->Delta:
    return Delta(before=before,after=after,change=round(after-before,2))

def ordered_choices(choices,scores):
    levels={s.dimension_id:s.score for s in scores}
    return sorted(choices,key=lambda c:(levels.get(c.dimension_id,4),c.choice_id))
