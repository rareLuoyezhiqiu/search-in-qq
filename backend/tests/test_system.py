import hashlib
import io
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from collector.db import Store, rows, run
from collector.api import create_app, passwords
from collector.service import ingest, process_one, cleanup
from collector.download import public_target

@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path)
    store.init()
    with store.tx() as c:
        run(c,'UPDATE settings SET password=:p',p=passwords.hash('test-password-123'))
    client=TestClient(create_app(store))
    token=client.post('/api/login',json={'password':'test-password-123'}).json()['token']
    client.headers['Authorization']='Bearer '+token
    assert client.post('/api/sources',json={'external_id':'123','name':'插画群'}).status_code==200
    yield store,client
    store.engine.dispose()

def event(mid='1',group='123',urls=2):
    return {'self_id':99,'group_id':group,'message_id':mid,'time':time.time(),'message_type':'group','user_id':456,'message':[{'type':'text','data':{'text':'春日插画 100%_完成'}}]+[{'type':'image','data':{'url':'https://example.com/'+str(i)}} for i in range(urls)]}

def pixels(url,path):
    Image.new('RGB',(40,30),(12,134,76)).save(path,'PNG')

def collect(store,mid='1',now=None):
    ingest(store,event(mid),now)
    while process_one(store,pixels,now):
        pass

def image_id(client):
    return client.get('/api/images').json()['items'][0]['id']

def test_save_dedupe_sources_search_and_restart(env):
    store,client=env
    collect(store)
    assert client.get('/api/images').json()['total']==1
    id=image_id(client)
    assert len(client.get('/api/images/'+id).json()['sources'])==2
    data=client.get('/api/images/'+id+'/file').content
    assert Image.open(io.BytesIO(data)).size==(40,30)
    assert len(list(store.media.glob('*.original')))==1
    again=Store(store.root)
    assert not ingest(again,event())['accepted']
    collect(store,'2')
    assert len(client.get('/api/images/'+id).json()['sources'])==4
    assert client.patch('/api/images/'+id,json={'favorite':True,'note':'夏天','tags':['壁纸','中文']}).status_code==200
    for q in ['壁纸','夏天','春日','%_']:
        assert client.get('/api/images',params={'q':q}).json()['total']==1
    assert client.get('/api/images',params={'q':'不存在'}).json()['total']==0
    assert client.get('/api/images',params={'tag':'壁'}).json()['total']==0
    assert client.get('/api/images',params={'tag':'壁纸','favorite':True}).json()['total']==1
    again.engine.dispose()

def test_expiry_boundary_and_replay_receipt(env,monkeypatch):
    store,client=env
    start=time.time()
    collect(store,now=start)
    id=image_id(client)
    monkeypatch.setattr('collector.api.time.time',lambda:start+432000-1)
    assert client.get('/api/images/'+id+'/file').status_code==200
    monkeypatch.setattr('collector.api.time.time',lambda:start+432000)
    assert client.get('/api/images').json()['total']==0
    assert client.get('/api/images/'+id+'/file').status_code==404
    cleanup(store,start+432000)
    assert not list(store.media.glob('*.original'))
    assert not ingest(store,event(),start+500000)['accepted']
    with store.tx() as c:
        assert rows(c,'SELECT * FROM messages')==[]
        assert len(rows(c,'SELECT * FROM receipts'))==1

def test_shared_expiry_and_favorite_confirmation(env,monkeypatch):
    store,client=env
    start=time.time()
    collect(store,now=start)
    collect(store,'2',start+3*86400)
    id=image_id(client)
    cleanup(store,start+5*86400)
    assert (store.media/(id+'.original')).exists()
    monkeypatch.setattr('collector.api.time.time',lambda:start+5*86400)
    assert len(client.get('/api/images/'+id).json()['sources'])==2
    client.patch('/api/images/'+id,json={'favorite':True,'note':'','tags':[]})
    cleanup(store,start+10*86400)
    monkeypatch.setattr('collector.api.time.time',lambda:start+6*86400)
    # Reauthenticate after cleanup has expired the original session.
    token=client.post('/api/login',json={'password':'test-password-123'}).json()['token']
    client.headers['Authorization']='Bearer '+token
    assert client.get('/api/images/'+id+'/file').status_code==200
    with store.tx() as c:
        run(c,'UPDATE occurrences SET expires=:exp',exp=start+5*86400)
    assert client.patch('/api/images/'+id,json={'favorite':False,'note':'','tags':[]}).status_code==409
    assert client.patch('/api/images/'+id,json={'favorite':False,'note':'','tags':[],'confirm_expired':True}).status_code==200
    cleanup(store,start+6*86400)
    assert not (store.media/(id+'.original')).exists()

def test_failure_manual_retry_lease_and_missing_file(env):
    store,client=env
    ingest(store,event(urls=1))
    def fail(url,path):raise ValueError('下载失败')
    for shift in (0,31,100):
        process_one(store,fail,time.time()+shift)
    task=client.get('/api/tasks').json()[0]
    assert task['state']=='failed'
    assert client.post('/api/tasks/'+str(task['id'])+'/retry').status_code==200
    with store.tx() as c:
        run(c,"UPDATE occurrences SET state='running',lease=1")
    process_one(store,pixels)
    id=image_id(client)
    (store.media/(id+'.original')).unlink()
    cleanup(store)
    assert client.get('/api/images').json()['total']==0
    assert client.get('/api/tasks').json()[0]['state']=='failed'
    client.post('/api/tasks/'+str(task['id'])+'/retry')
    process_one(store,pixels)
    assert client.get('/api/images/'+id+'/file').status_code==200

def test_auth_revocation_throttling_and_media(env):
    store,client=env
    collect(store)
    id=image_id(client)
    other=TestClient(create_app(store))
    for path in ['/api/images','/api/images/'+id+'/file','/api/settings','/api/images/'+id+'/file?thumbnail=true']:
        assert other.get(path).status_code==401
    assert client.delete('/api/session').status_code==200
    assert client.get('/api/images').status_code==401
    for _ in range(10):assert other.post('/api/login',json={'password':'wrong'}).status_code==401
    assert other.post('/api/login',json={'password':'test-password-123'}).status_code==429

def test_source_pause_remove_and_expired_retry(env):
    store,client=env
    collect(store)
    id=image_id(client)
    source=client.get('/api/sources').json()[0]['id']
    client.patch('/api/sources/'+str(source),json={'enabled':False})
    assert not ingest(store,event('2'))['accepted']
    client.delete('/api/sources/'+str(source))
    assert client.get('/api/images/'+id).status_code==200
    with store.tx() as c:
        run(c,'UPDATE occurrences SET expires=1')
    assert client.post('/api/tasks/1/retry').status_code==410

def test_capacity_and_settings_original_clock(env):
    store,client=env
    collect(store)
    id=image_id(client)
    ingest(store,event('2'))
    with store.tx() as c:run(c,'UPDATE settings SET budget=1')
    process_one(store,pixels)
    assert '容量不足' in client.get('/api/tasks').json()[1]['error']
    assert client.get('/api/images/'+id+'/file').status_code==200
    assert client.put('/api/settings',json={'days':2,'budget':50000000}).status_code==200
    with store.tx() as c:
        for o in rows(c,'SELECT received,expires FROM occurrences'):
            assert o['expires']-o['received']==172800

def test_concurrent_replay_and_delete_failure(env,monkeypatch):
    store,client=env
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:ingest(store,event()),range(8)))
    collect(store)
    id=image_id(client)
    with store.tx() as c:
        assert len(rows(c,'SELECT * FROM occurrences'))==2
        run(c,'UPDATE occurrences SET expires=1')
    from pathlib import Path
    original=Path.unlink
    def denied(path,*a,**kw):
        if path.suffix=='.original':raise PermissionError('busy')
        return original(path,*a,**kw)
    monkeypatch.setattr(Path,'unlink',denied)
    with pytest.raises(PermissionError):cleanup(store)
    assert (store.media/(id+'.original')).exists()
    monkeypatch.setattr(Path,'unlink',original)
    cleanup(store)
    assert not (store.media/(id+'.original')).exists()

@pytest.mark.parametrize('url',['http://example.com/a','https://127.0.0.1/a','https://169.254.169.254/a','https://[::1]/a','file:///etc/passwd','https://user:pass@example.com/a'])
def test_ssrf_rejected(url):
    with pytest.raises(ValueError):public_target(url)

def test_worker_auth_and_malformed_event(env,monkeypatch):
    from collector.worker import create_worker
    store,_=env
    monkeypatch.setenv('INGEST_TOKEN','a'*32)
    c=TestClient(create_worker(store))
    assert c.post('/events/onebot',json=event()).status_code==401
    c.headers['Authorization']='Bearer '+'a'*32
    assert c.post('/events/onebot',json=event()).json()['accepted']
    assert c.post('/events/onebot',json=['invalid']).status_code==422
    assert c.post('/events/onebot',json={'post_type':'meta_event','status':{'online':False}}).status_code==200
    with store.tx() as db:assert rows(db,'SELECT online FROM runtime')[0]['online']==0

def test_corrupt_payload_never_saved(env):
    store,client=env
    ingest(store,event(urls=1))
    def corrupt(url,path):path.write_bytes(b'not an image')
    process_one(store,corrupt)
    assert client.get('/api/images').json()['total']==0
    assert client.get('/api/tasks').json()[0]['error']
    assert list(store.media.iterdir())==[]

