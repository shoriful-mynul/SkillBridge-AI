import os
import asyncio
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from .models import Assessment,CreateRequest,TaskRequest,SubmitRequest,ProbeRequest
from .service import AssessmentService,role
from .llm import ProviderUnavailable

app=FastAPI(title='SkillBridge AI',version='2.0.0')
service=AssessmentService()

async def bounded(operation):
    try:
        async with asyncio.timeout(130):return await operation
    except TimeoutError as exc:raise ProviderUnavailable('The assessment exceeded its time budget. Your draft and previous results are unchanged.') from exc

async def service_boundary(x_backend_token: str | None=Header(default=None)):
    expected=os.getenv('BACKEND_SHARED_SECRET')
    # No candidate account system. Protect the hosted service-to-service route.
    if expected:
        import hmac
        if not x_backend_token or not hmac.compare_digest(x_backend_token,expected):raise HTTPException(403,'Private service access is required.')
    elif os.getenv('DEPLOYMENT_ENV')=='production':raise HTTPException(503,'The private service boundary is not configured.')

@app.exception_handler(ValueError)
async def contract_error(request,exc):return JSONResponse(status_code=422,content={'error':{'code':'CONTRACT_GUARD','message':str(exc),'retryable':False}})
@app.exception_handler(ProviderUnavailable)
async def provider_error(request,exc):return JSONResponse(status_code=503,content={'error':{'code':'AI_UNAVAILABLE','message':str(exc),'retryable':True}})

@app.get('/health',dependencies=[Depends(service_boundary)])
async def health()->dict:return {'status':'ok','ai_configured':bool(os.getenv('GEMINI_API_KEY')),'model':service.llm.model,'schema_version':'2.0.0'}
@app.get('/api/roles/ai-ml-intern',dependencies=[Depends(service_boundary)])
async def get_role()->dict:return role('ai-ml-intern')
@app.post('/api/assessments',response_model=Assessment,dependencies=[Depends(service_boundary)])
async def create_assessment(body:CreateRequest)->Assessment:return await bounded(service.create(body))
@app.post('/api/assessments/task',response_model=Assessment,dependencies=[Depends(service_boundary)])
async def generate_task(body:TaskRequest)->Assessment:return await bounded(service.task(body))
@app.post('/api/assessments/submit',response_model=Assessment,dependencies=[Depends(service_boundary)])
async def submit(body:SubmitRequest)->Assessment:return await bounded(service.submit(body))
@app.post('/api/assessments/probes',response_model=Assessment,dependencies=[Depends(service_boundary)])
async def answer_probes(body:ProbeRequest)->Assessment:return await bounded(service.probes(body))
@app.post('/api/assessments/revise',response_model=Assessment,dependencies=[Depends(service_boundary)])
async def revise(body:SubmitRequest)->Assessment:return await bounded(service.submit(body,revision=True))
