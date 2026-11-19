import asyncio
import hmac
import json
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from functools import partial
from fastapi import FastAPI, Header, HTTPException, Request
from .db import Store
from .service import ingest, process_one, cleanup
from .review import process_review
from .vision import classify

def create_worker(store=None):
    store=store or Store()
    async def loop():
        last=0
        while True:
            try:
                if time.time()-last>=900:
                    await asyncio.to_thread(cleanup,store)
                    last=time.time()
                worked=await asyncio.to_thread(process_one,store)
            except Exception as exc:
                print('Worker cycle failed:',type(exc).__name__,flush=True)
                worked=False
            await asyncio.sleep(0.1 if worked else 2)
    async def review_loop(key):
        classifier = partial(classify, key)
        while True:
            try:
                worked = await asyncio.to_thread(process_review, store, classifier)
            except Exception as exc:
                print('AI review cycle failed:', type(exc).__name__, flush=True)
                worked = False
            await asyncio.sleep(0.2 if worked else 15)
    @asynccontextmanager
    async def lifespan(app):
        tasks=[asyncio.create_task(loop())]
        key=os.getenv('DEEPSEEK_API_KEY','').strip()
        if key:
            tasks.append(asyncio.create_task(review_loop(key)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
    @app.post('/events/onebot')
    async def event(
        request: Request,
        authorization: str = Header(default=''),
        x_signature: str = Header(default=''),
    ):
        expected=os.getenv('INGEST_TOKEN','')
        if len(expected)<32:
            raise HTTPException(401,'接入令牌无效')
        bearer_ok = secrets.compare_digest(authorization.encode(), ('Bearer '+expected).encode())
        if not bearer_ok and not re.fullmatch(r'sha1=[0-9a-f]{40}', x_signature):
            raise HTTPException(401,'接入令牌无效')
        payload=bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload)>1024*1024:
                raise HTTPException(413,'事件过大')
        if not bearer_ok:
            # OneBot signs the exact request bytes, including JSON whitespace.
            signature = 'sha1=' + hmac.digest(expected.encode(), payload, 'sha1').hex()
            if not secrets.compare_digest(signature, x_signature):
                raise HTTPException(401,'接入令牌无效')
        try:
            obj=json.loads(payload)
            if not isinstance(obj,dict):
                raise ValueError()
            return await asyncio.to_thread(ingest,store,obj)
        except (ValueError,TypeError,KeyError):
            raise HTTPException(422,'OneBot 事件格式无效')
    return app
app=create_worker()
