import asyncio
import json
import os
from pathlib import Path
from typing import TypeVar
import httpx
from pydantic import BaseModel

ROOT=Path(__file__).resolve().parents[1]
T=TypeVar('T',bound=BaseModel)

class ProviderUnavailable(Exception):pass

def render_prompt(filename: str,**values)->str:
    prompt=(ROOT/'prompts'/filename).read_text()
    for key,value in values.items():
        prompt=prompt.replace('{{'+key+'}}',value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
    if '{{' in prompt:raise ValueError('A system prompt has an unresolved placeholder.')
    return prompt

class Gemini:
    model=os.getenv('GEMINI_MODEL','gemini-3.8-flash')
    def __init__(self):self.semaphore=asyncio.Semaphore(2)
    async def generate(self,prompt: str,user: dict,output: type[T],temperature: float=0.0)->T:
        key=os.getenv('GEMINI_API_KEY')
        if not key:raise ProviderUnavailable('Live AI is not configured. No assessment was generated.')
        body={'systemInstruction':{'parts':[{'text':prompt}]},'contents':[{'role':'user','parts':[{'text':json.dumps(user,ensure_ascii=False)}]}], 'generationConfig':{'temperature':temperature,'responseFormat':{'text':{'mimeType':'application/json','schema':output.model_json_schema()}}}}
        async with self.semaphore:
            async with httpx.AsyncClient(timeout=35.0) as client:
                for attempt in range(2):
                    try:
                        response=await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent',headers={'x-goog-api-key':key},json=body)
                        if response.status_code in (429,500,502,503,504) and attempt==0:
                            delay=min(2,float(response.headers.get('retry-after','1')));await asyncio.sleep(delay);continue
                        if response.status_code!=200:raise ProviderUnavailable('The AI service could not complete this step. Your previous work is unchanged. Try again shortly.')
                        candidates=response.json().get('candidates',[])
                        if not candidates:raise ProviderUnavailable('The AI service returned no usable assessment. Your previous work is unchanged.')
                        content=''.join(p.get('text','') for p in candidates[0].get('content',{}).get('parts',[]))
                        return output.model_validate_json(content)
                    except (httpx.TimeoutException,httpx.NetworkError) as exc:
                        if attempt==0:continue
                        raise ProviderUnavailable('The AI request timed out. Your draft is still available; no new score was created.') from exc
                    except (ValueError,KeyError,TypeError) as exc:
                        raise ProviderUnavailable('The AI response did not match the evidence contract. No new score was created.') from exc
