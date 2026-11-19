import hashlib
import json
import os
import shutil
import time
import warnings
from PIL import Image
from .db import rows, run
from .download import download, MAX_BYTES

Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter('error', Image.DecompressionBombWarning)

def ingest(store, event, now=None):
    now = time.time() if now is None else now
    if event.get('post_type') == 'meta_event':
        status = event.get('status', {})
        if not isinstance(status, dict):
            raise ValueError('心跳格式无效')
        with store.tx() as c:
            run(c, 'UPDATE runtime SET heartbeat=:now, online=:online WHERE id=1', now=now, online=int(bool(status.get('online', False))))
        return {'accepted': False, 'reason': 'heartbeat'}
    if event.get('message_type') != 'group' or not isinstance(event.get('message'), list):
        return {'accepted': False, 'reason': '仅接收 OneBot v11 群消息数组'}
    required = ('self_id', 'group_id', 'message_id', 'time')
    if any(event.get(k) is None for k in required):
        raise ValueError('缺少消息标识字段')
    digest = hashlib.sha256(json.dumps([str(event[k]) for k in required[:3]], ensure_ascii=False).encode()).hexdigest()
    segments = event['message']
    if any(not isinstance(s, dict) or not isinstance(s.get('data', {}), dict) for s in segments):
        raise ValueError('消息段格式无效')
    if len(segments) > 100:
        raise ValueError('消息段超过上限')
    images = [(n, s.get('data', {}).get('url', '')) for n,s in enumerate(segments) if s.get('type') == 'image']
    body = ''.join(str(s.get('data', {}).get('text', '')) for s in segments if s.get('type') == 'text')[:20000]
    with store.tx() as c:
        source = rows(c, 'SELECT * FROM sources WHERE external_id=:id AND enabled=1 AND removed=0', id=str(event['group_id']))
        if not source:
            return {'accepted': False, 'reason': '来源未启用'}
        if rows(c, 'SELECT digest FROM receipts WHERE digest=:d', d=digest):
            return {'accepted': False, 'reason': 'duplicate'}
        run(c, 'INSERT INTO receipts VALUES(:d,:now)', d=digest, now=now)
        run(c, 'UPDATE sources SET last_event=:now WHERE id=:id', now=now, id=source[0]['id'])
        if not images:
            return {'accepted': True, 'images': 0}
        days = rows(c, 'SELECT days FROM settings')[0]['days']
        mid = run(c, 'INSERT INTO messages(digest,source_id,received,published,sender,body) VALUES(:d,:s,:now,:pub,:sender,:body)', d=digest,s=source[0]['id'],now=now,pub=float(event['time']),sender=str(event.get('user_id','')),body=body).lastrowid
        for pos,url in images:
            run(c, 'INSERT INTO occurrences(message_id,position,received,expires,url) VALUES(:m,:p,:now,:exp,:url)', m=mid,p=pos,now=now,exp=now+days*86400,url=str(url)[:8192])
    return {'accepted': True, 'images': len(images)}

def usage(store):
    return sum(p.stat().st_size for p in store.media.iterdir() if p.is_file())

def remove_image_records(c, image_id):
    run(c, 'DELETE FROM occurrences WHERE image_id=:id', id=image_id)
    run(c, 'DELETE FROM images WHERE id=:id', id=image_id)

def cleanup(store, now=None):
    now = time.time() if now is None else now
    # Writer lock covers eligibility recheck, unlink and record removal. Failed unlink rolls
    # back metadata; next pass retries. API also checks actual files before serving.
    with store.tx() as c:
        run(c, "DELETE FROM occurrences WHERE expires<=:now AND (image_id IS NULL OR image_id IN (SELECT id FROM images WHERE favorite=0))", now=now)
        for i in rows(c, 'SELECT * FROM images WHERE favorite=0 AND NOT EXISTS (SELECT 1 FROM occurrences WHERE image_id=images.id)'):
            for suffix in ('.original', '.jpg'):
                (store.media / (i['id']+suffix)).unlink(missing_ok=True)
            run(c, 'DELETE FROM images WHERE id=:id', id=i['id'])
        run(c, 'DELETE FROM messages WHERE NOT EXISTS(SELECT 1 FROM occurrences WHERE message_id=messages.id)')
        run(c, 'DELETE FROM sessions WHERE expires<=:now', now=now)
        run(c, 'DELETE FROM attempts WHERE at<:cut', cut=now-900)
        known = {i['id'] for i in rows(c, 'SELECT id FROM images')}
        for p in store.media.iterdir():
            if p.is_file() and p.stem not in known and p.stat().st_mtime < now-600:
                p.unlink(missing_ok=True)
        for i in rows(c, "SELECT * FROM images WHERE state='saved'"):
            if not all((store.media/(i['id']+s)).exists() for s in ('.original','.jpg')):
                run(c, "UPDATE images SET state='missing' WHERE id=:id", id=i['id'])
                run(c, "UPDATE occurrences SET state='failed',error='持久文件缺失，可重试下载' WHERE image_id=:id", id=i['id'])

def process_one(store, downloader=download, now=None):
    realtime = now is None
    now = time.time() if now is None else now
    with store.tx() as c:
        run(c, 'UPDATE runtime SET worker=:now WHERE id=1', now=now)
        run(c, "UPDATE occurrences SET state='waiting' WHERE state='running' AND lease<:now", now=now)
        tasks = rows(c, "SELECT o.* FROM occurrences o LEFT JOIN images i ON i.id=o.image_id WHERE o.state='waiting' AND o.next_try<=:now AND (o.expires>:now OR i.favorite=1) ORDER BY o.id LIMIT 1", now=now)
        if not tasks:
            return False
        task = tasks[0]
        run(c, "UPDATE occurrences SET state='running',lease=:lease,attempts=attempts+1 WHERE id=:id", lease=now+180,id=task['id'])
    tmp = store.media / (str(task['id'])+'.part')
    thumb = store.media / (str(task['id'])+'.thumb')
    try:
        with store.tx() as c:
            budget = rows(c,'SELECT budget FROM settings')[0]['budget']
        if usage(store)+MAX_BYTES > budget:
            cleanup(store, now)
        if usage(store)+MAX_BYTES > budget or shutil.disk_usage(store.root).free < MAX_BYTES+100*1024*1024:
            raise ValueError('容量不足，下载已暂停；释放空间或提高预算后重试')
        downloader(task['url'],tmp)
        if tmp.stat().st_size > MAX_BYTES:
            raise ValueError('图片超过 25 MiB 限制')
        with Image.open(tmp) as im:
            fmt, width, height = im.format, im.width, im.height
            if fmt not in ('JPEG','PNG','WEBP','GIF'):
                raise ValueError('不支持的图片格式')
            im.verify()
        with Image.open(tmp) as im:
            im.seek(0)
            im.thumbnail((512,512))
            im.convert('RGB').save(thumb,'JPEG',quality=82)
        with tmp.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        size = tmp.stat().st_size
        if realtime:
            now = time.time()
        with store.tx() as c:
            current = rows(c, 'SELECT o.*,COALESCE(i.favorite,0) AS favorite FROM occurrences o LEFT JOIN images i ON i.id=o.image_id WHERE o.id=:id',id=task['id'])
            if not current or (current[0]['expires']<=now and not current[0]['favorite']):
                run(c, "UPDATE occurrences SET state='expired',lease=0,url='' WHERE id=:id", id=task['id'])
                return True
            old = rows(c, 'SELECT * FROM images WHERE id=:id',id=digest)
            if not old or old[0]['state']!='saved' or not all((store.media/(digest+s)).exists() for s in ('.original','.jpg')):
                os.replace(tmp,store.media/(digest+'.original'))
                os.replace(thumb,store.media/(digest+'.jpg'))
            run(c, 'INSERT OR IGNORE INTO images(id,format,width,height,size) VALUES(:id,:fmt,:w,:h,:size)',id=digest,fmt=fmt,w=width,h=height,size=size)
            run(c, "UPDATE images SET state='saved' WHERE id=:id",id=digest)
            run(c, "UPDATE occurrences SET image_id=:image,state='saved',error='',lease=0 WHERE id=:id",image=digest,id=task['id'])
        return True
    except Exception as exc:
        # URLs and stack traces can contain credentials; persist only safe diagnostics.
        message = str(exc) if isinstance(exc, ValueError) else '下载或图片校验失败（'+type(exc).__name__+'）'
        with store.tx() as c:
            run(c, 'UPDATE occurrences SET state=:state,error=:error,next_try=:next,lease=0 WHERE id=:id',state='failed' if task['attempts']>=2 or '容量不足' in message else 'waiting', error=message[:200],next=now+30*2**task['attempts'],id=task['id'])
        return True
    finally:
        tmp.unlink(missing_ok=True)
        thumb.unlink(missing_ok=True)
