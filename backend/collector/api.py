import hashlib
import json
import secrets
import time
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pwdlib import PasswordHash
from .db import Store, rows, run, VISIBLE
from .service import usage

passwords = PasswordHash.recommended()

def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()

class Login(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
class Source(BaseModel):
    external_id: str = Field(pattern=r'^\d{1,20}$')
    name: str = Field(min_length=1, max_length=100)
class SourceEdit(BaseModel):
    enabled: bool
class Edit(BaseModel):
    favorite: bool
    note: str = Field(max_length=5000)
    tags: list[str] = Field(max_length=30)
    confirm_expired: bool = False
class Settings(BaseModel):
    days: int = Field(ge=1, le=365)
    budget: int = Field(ge=30*1024*1024, le=10**13)

def create_app(store=None):
    store = store or Store()
    app = FastAPI(title='拾图 API', docs_url=None, redoc_url=None)
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=['https://localhost','http://localhost','http://127.0.0.1:5173'],allow_methods=['GET','POST','PATCH','DELETE','PUT'],allow_headers=['Authorization','Content-Type'])
    def auth(authorization: str = Header(default='')):
        token = authorization.removeprefix('Bearer ')
        with store.tx() as c:
            if not rows(c,'SELECT digest FROM sessions WHERE digest=:d AND expires>:now',d=hashed(token),now=time.time()):
                raise HTTPException(401,'登录已失效，请重新登录')
        return hashed(token)
    def accessible(c, id):
        found = rows(c, 'SELECT DISTINCT i.* FROM images i JOIN occurrences o ON o.image_id=i.id WHERE i.id=:id AND '+VISIBLE,id=id,now=time.time())
        if not found:
            raise HTTPException(404,'图片不存在或已过期')
        return found[0]
    def detail(c,id):
        image=accessible(c,id)
        image['tags']=json.loads(image['tags'])
        image['sources']=rows(c,'SELECT s.name,s.external_id,m.body,m.sender,m.published,o.received,o.expires FROM occurrences o JOIN messages m ON m.id=o.message_id JOIN sources s ON s.id=m.source_id WHERE o.image_id=:id AND (:fav=1 OR o.expires>:now) ORDER BY o.received DESC',id=id,fav=image['favorite'],now=time.time())
        return image
    @app.get('/health')
    def health():
        return {'ok':True}
    @app.post('/api/login')
    def login(body: Login):
        now=time.time()
        with store.tx() as c:
            if len(rows(c,'SELECT id FROM attempts WHERE at>:cut',cut=now-900))>=10:
                raise HTTPException(429,'尝试过多，请 15 分钟后重试')
            password=rows(c,'SELECT password FROM settings')[0]['password']
            valid=bool(password) and passwords.verify(body.password,password)
            if not valid:
                run(c,'INSERT INTO attempts(at) VALUES(:now)',now=now)
            else:
                token=secrets.token_urlsafe(32)
                run(c,'INSERT INTO sessions VALUES(:d,:exp)',d=hashed(token),exp=now+7*86400)
        if not valid:
            raise HTTPException(401,'密码错误或管理员尚未初始化')
        return {'token':token,'expires':now+7*86400}
    @app.delete('/api/session')
    def logout(session=Depends(auth)):
        with store.tx() as c:
            run(c,'DELETE FROM sessions WHERE digest=:d',d=session)
        return {'ok':True}
    @app.get('/api/sources',dependencies=[Depends(auth)])
    def sources():
        with store.tx() as c:
            return rows(c,'SELECT * FROM sources WHERE removed=0 ORDER BY id DESC')
    @app.post('/api/sources',dependencies=[Depends(auth)])
    def add_source(body: Source):
        with store.tx() as c:
            run(c,'INSERT INTO sources(external_id,name) VALUES(:external_id,:name) ON CONFLICT(external_id) DO UPDATE SET name=excluded.name,removed=0,enabled=1',**body.model_dump())
        return {'ok':True}
    @app.patch('/api/sources/{id}',dependencies=[Depends(auth)])
    def edit_source(id:int,body:SourceEdit):
        with store.tx() as c:
            run(c,'UPDATE sources SET enabled=:enabled WHERE id=:id',id=id,enabled=int(body.enabled))
        return {'ok':True}
    @app.delete('/api/sources/{id}',dependencies=[Depends(auth)])
    def remove_source(id:int):
        with store.tx() as c:
            run(c,'UPDATE sources SET removed=1,enabled=0 WHERE id=:id',id=id)
        return {'ok':True}
    @app.get('/api/images',dependencies=[Depends(auth)])
    def images(q:str='',tag:str='',source:int|None=None,favorite:bool=False,start:float|None=None,end:float|None=None,offset:int=0,limit:int=40):
        if offset<0 or limit<1 or limit>100 or len(q)>500:
            raise HTTPException(422,'分页或搜索参数无效')
        with store.tx() as c:
            found=rows(c,"SELECT DISTINCT i.* FROM images i JOIN occurrences o ON o.image_id=i.id JOIN messages m ON m.id=o.message_id WHERE "+VISIBLE+" AND (:source IS NULL OR m.source_id=:source) AND (:start IS NULL OR o.received>=:start) AND (:end IS NULL OR o.received<:end) AND (:fav=0 OR i.favorite=1) AND (:q='' OR instr(i.note,:q)>0 OR instr(i.tags,:q)>0 OR instr(m.body,:q)>0) GROUP BY i.id ORDER BY MAX(o.received) DESC,i.id DESC",now=time.time(),source=source,start=start,end=end,fav=int(favorite),q=q)
            for i in found:
                i['tags']=json.loads(i['tags'])
            if tag:
                found=[i for i in found if tag in i['tags']]
            return {'items':found[offset:offset+limit],'total':len(found)}
    @app.get('/api/images/{id}',dependencies=[Depends(auth)])
    def get_image(id:str):
        with store.tx() as c:
            return detail(c,id)
    @app.patch('/api/images/{id}',dependencies=[Depends(auth)])
    def edit_image(id:str,body:Edit):
        with store.tx() as c:
            i=accessible(c,id)
            if i['favorite'] and not body.favorite and not rows(c,'SELECT id FROM occurrences WHERE image_id=:id AND expires>:now',id=id,now=time.time()) and not body.confirm_expired:
                raise HTTPException(409,'全部来源已过期，取消收藏后图片将不可访问。请确认。')
            tags=list(dict.fromkeys(t.strip() for t in body.tags if t.strip()))
            if any(len(t)>50 for t in tags):
                raise HTTPException(422,'标签最多 50 个字符')
            run(c,'UPDATE images SET favorite=:fav,note=:note,tags=:tags WHERE id=:id',id=id,fav=int(body.favorite),note=body.note,tags=json.dumps(tags,ensure_ascii=False))
        return {'ok':True}
    @app.delete('/api/images/{id}',dependencies=[Depends(auth)])
    def delete_image(id:str):
        with store.tx() as c:
            accessible(c,id)
            for suffix in ('.original','.jpg'):
                (store.media/(id+suffix)).unlink(missing_ok=True)
            run(c,'DELETE FROM occurrences WHERE image_id=:id',id=id)
            run(c,'DELETE FROM images WHERE id=:id',id=id)
        return {'ok':True}
    @app.get('/api/images/{id}/file',dependencies=[Depends(auth)])
    def file(id:str,thumbnail:bool=False):
        with store.tx() as c:
            i=accessible(c,id)
            path=store.media/(id+('.jpg' if thumbnail else '.original'))
            if not path.is_file():
                raise HTTPException(410,'持久文件缺失，请查看失败任务')
            # Read under lock so cleanup cannot unlink between authorization and open.
            from fastapi.responses import Response
            return Response(path.read_bytes(),media_type='image/jpeg' if thumbnail else 'image/'+i['format'].lower(),headers={'Cache-Control':'no-store'})
    @app.get('/api/tasks',dependencies=[Depends(auth)])
    def tasks():
        with store.tx() as c:
            return rows(c,"SELECT o.id,o.state,o.error,o.attempts,o.expires,s.name FROM occurrences o JOIN messages m ON m.id=o.message_id JOIN sources s ON s.id=m.source_id LEFT JOIN images i ON i.id=o.image_id WHERE o.state!='saved' AND (o.expires>:now OR i.favorite=1) ORDER BY o.id DESC LIMIT 200",now=time.time())
    @app.post('/api/tasks/{id}/retry',dependencies=[Depends(auth)])
    def retry(id:int):
        with store.tx() as c:
            task=rows(c,'SELECT o.*,COALESCE(i.favorite,0) AS favorite FROM occurrences o LEFT JOIN images i ON i.id=o.image_id WHERE o.id=:id',id=id)
            if not task or (task[0]['expires']<=time.time() and not task[0]['favorite']):
                raise HTTPException(410,'任务已过期，不能重新下载')
            if task[0]['state']=='running':
                raise HTTPException(409,'任务正在执行')
            run(c,"UPDATE occurrences SET state='waiting',attempts=0,next_try=0,error='' WHERE id=:id",id=id)
        return {'ok':True}
    @app.get('/api/settings',dependencies=[Depends(auth)])
    def settings():
        import shutil
        with store.tx() as c:
            result=rows(c,'SELECT days,budget FROM settings')[0]
            result.update(rows(c,'SELECT * FROM runtime')[0])
            result['favorites_bytes']=rows(c,'SELECT COALESCE(SUM(size),0) AS n FROM images WHERE favorite=1')[0]['n']
        result.update(used=usage(store),free=shutil.disk_usage(store.root).free,database_bytes=sum(p.stat().st_size for p in store.root.glob('collector.db*')))
        return result
    @app.put('/api/settings',dependencies=[Depends(auth)])
    def update_settings(body:Settings):
        with store.tx() as c:
            run(c,'UPDATE settings SET days=:days,budget=:budget',**body.model_dump())
            run(c,'UPDATE occurrences SET expires=received+:seconds',seconds=body.days*86400)
        return {'ok':True}
    return app

app=create_app()
