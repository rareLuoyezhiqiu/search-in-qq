import asyncio
import contextlib
import os
import secrets
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from .db import Store
from .service import ingest, process_one, cleanup

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
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(loop())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None)
    @app.post('/events/onebot')
    async def event(request:Request, authorization:str=Header(default='')):
        expected=os.getenv('INGEST_TOKEN','')
        if len(expected)<32 or not secrets.compare_digest(authorization,'Bearer '+expected):
            raise HTTPException(401,'接入令牌无效')
        payload=bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload)>1024*1024:
                raise HTTPException(413,'事件过大')
        try:
            import json
            obj=json.loads(payload)
            if not isinstance(obj,dict):
                raise ValueError()
            return await asyncio.to_thread(ingest,store,obj)
        except (ValueError,TypeError,KeyError):
            raise HTTPException(422,'OneBot 事件格式无效')
    return app
app=create_worker()
