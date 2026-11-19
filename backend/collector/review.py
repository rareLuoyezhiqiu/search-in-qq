import hashlib
import os
import time
from datetime import datetime, timedelta, timezone

from .db import VISIBLE, rows, run
from .service import remove_image_records
from .vision import VisionError

BEIJING = timezone(timedelta(hours=8))
DAY = 86400


def configured():
    return bool(os.getenv('DEEPSEEK_API_KEY', '').strip())


def _settings(c):
    return rows(c, 'SELECT enabled,daily_time,prompt,auto_favorite,changed_at FROM ai_settings WHERE id=1')[0]


def _latest_slot(daily_time, now):
    local = datetime.fromtimestamp(now, BEIJING)
    hour, minute = map(int, daily_time.split(':'))
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()
    return slot if slot <= now else slot - DAY


def _due(c, settings, now):
    slot = _latest_slot(settings['daily_time'], now)
    if slot >= settings['changed_at'] and not rows(c, 'SELECT id FROM ai_batches WHERE cutoff=:slot', slot=slot):
        return slot
    return slot + DAY


def _batch_report(c, kind):
    found = rows(c, 'SELECT id,started,cutoff FROM ai_batches WHERE kind=:kind ORDER BY id DESC LIMIT 1', kind=kind)
    if not found:
        return None
    batch = found[0]
    batch['counts'] = {
        row['status']: row['count']
        for row in rows(c, 'SELECT status,COUNT(*) AS count FROM ai_items WHERE batch_id=:id GROUP BY status', id=batch['id'])
    }
    batch['items'] = rows(c, '''
        SELECT image_id,status,decision,reason FROM ai_items WHERE batch_id=:id
        ORDER BY CASE status WHEN 'deleted' THEN 0 WHEN 'failed' THEN 1 ELSE 2 END,image_id
        LIMIT 12
    ''', id=batch['id'])
    return batch


def status(store, now=None):
    now = time.time() if now is None else now
    with store.tx() as c:
        settings = _settings(c)
        next_run = _due(c, settings, now) if settings['enabled'] else None
        settings.pop('changed_at')
        return {
            **settings,
            'key_configured': configured(),
            'next_run': next_run,
            'scheduled': _batch_report(c, 'scheduled'),
            'preview': _batch_report(c, 'preview'),
        }


def change_settings(store, config, now=None):
    now = time.time() if now is None else now
    with store.tx() as c:
        previous = _settings(c)
        if all(previous[key] == value for key, value in config.items()):
            return
        run(c, '''
            UPDATE ai_settings SET enabled=:enabled,daily_time=:daily_time,prompt=:prompt,
                auto_favorite=:auto_favorite,changed_at=:now WHERE id=1
        ''', **config, now=now)
        run(c, '''
            UPDATE ai_items SET status='skipped',lease=0,reason='识别设置已更改'
            WHERE status IN ('pending','running') AND
                  batch_id IN (SELECT id FROM ai_batches WHERE kind='scheduled')
        ''')


def _enqueue(c, kind, now, prompt, auto_favorite, cutoff=None):
    rule_key = hashlib.sha256(f'{int(auto_favorite)}:{prompt}'.encode()).hexdigest()
    batch = run(c, '''
        INSERT INTO ai_batches(kind,cutoff,started,prompt,rule_key,auto_favorite)
        VALUES(:kind,:cutoff,:now,:prompt,:rule,:auto)
    ''', kind=kind, cutoff=cutoff, now=now, prompt=prompt, rule=rule_key, auto=auto_favorite).lastrowid
    run(c, '''
        INSERT INTO ai_items(batch_id,image_id)
        SELECT :batch,i.id FROM images i JOIN occurrences o ON o.image_id=i.id
        WHERE ''' + VISIBLE + '''
          AND o.state='saved' AND (:cutoff IS NULL OR o.received<=:cutoff)
          AND (:cutoff IS NULL OR NOT EXISTS (
              SELECT 1 FROM ai_items previous JOIN ai_batches b ON b.id=previous.batch_id
              WHERE previous.image_id=i.id AND b.kind='scheduled' AND b.rule_key=:rule
                AND previous.status IN ('kept','uncertain','protected')
          ))
        GROUP BY i.id ORDER BY MAX(o.received) DESC,i.id
        LIMIT :limit
    ''', batch=batch, cutoff=cutoff, now=now, rule=rule_key, limit=6 if kind=='preview' else -1)
    return batch


def preview(store, prompt, now=None):
    now = time.time() if now is None else now
    with store.tx() as c:
        if rows(c, '''
            SELECT 1 FROM ai_items a JOIN ai_batches b ON b.id=a.batch_id
            WHERE b.kind='preview' AND a.status IN ('pending','running') LIMIT 1
        '''):
            return None
        return _enqueue(c, 'preview', now, prompt, False)


def _visible(c, image_id, now, cutoff):
    return rows(c, '''
        SELECT i.favorite FROM images i JOIN occurrences o ON o.image_id=i.id
        WHERE i.id=:image AND ''' + VISIBLE + '''
          AND o.state='saved' AND (:cutoff IS NULL OR o.received<=:cutoff) LIMIT 1
    ''', image=image_id, now=now, cutoff=cutoff)


def _finish(c, job, outcome, reason, decision=None):
    run(c, '''
        UPDATE ai_items SET status=:outcome,lease=0,reason=:reason,decision=:decision
        WHERE batch_id=:batch AND image_id=:image
    ''', outcome=outcome, reason=reason, decision=decision, batch=job['batch_id'], image=job['image_id'])


def _claim(store, now):
    with store.tx() as c:
        settings = _settings(c)
        if settings['enabled']:
            cutoff = _due(c, settings, now)
            if cutoff <= now and not rows(c, '''
                SELECT 1 FROM ai_items a JOIN ai_batches b ON b.id=a.batch_id
                WHERE b.kind='scheduled' AND a.status IN ('pending','running') LIMIT 1
            '''):
                _enqueue(c, 'scheduled', now, settings['prompt'], settings['auto_favorite'], cutoff)
        jobs = rows(c, '''
            SELECT a.batch_id,a.image_id,b.kind,b.cutoff,b.prompt,b.auto_favorite FROM ai_items a
            JOIN ai_batches b ON b.id=a.batch_id
            WHERE a.status='pending' OR (a.status='running' AND a.lease<=:now)
            ORDER BY (b.kind='preview') DESC,b.id,a.image_id LIMIT 1
        ''', now=now)
        if not jobs:
            return None, None
        job = jobs[0]
        if not _visible(c, job['image_id'], now, job['cutoff']):
            _finish(c, job, 'skipped', '图片已删除或过期')
            return job, None
        try:
            image = (store.media / (job['image_id'] + '.jpg')).read_bytes()
        except OSError:
            _finish(c, job, 'failed', '缩略图无法读取')
            return job, None
        job['lease'] = now + 180
        run(c, '''
            UPDATE ai_items SET status='running',lease=:lease WHERE batch_id=:batch AND image_id=:image
        ''', lease=job['lease'], batch=job['batch_id'], image=job['image_id'])
        return job, image


def process_review(store, classify, clock=time.time):
    job, image = _claim(store, clock())
    if not job or image is None:
        return job is not None

    failure = decision = None
    try:
        decision = classify(job['prompt'], image)
    except VisionError as exc:
        failure = exc

    with store.tx() as c:
        if not rows(c, '''
            SELECT 1 FROM ai_items WHERE batch_id=:batch AND image_id=:image AND
                status='running' AND lease=:lease
        ''', batch=job['batch_id'], image=job['image_id'], lease=job['lease']):
            return True
        if failure:
            _finish(c, job, 'failed', str(failure))
            if failure.stop_batch:
                run(c, '''
                    UPDATE ai_items SET status='failed',reason=:reason
                    WHERE batch_id=:batch AND status='pending'
                ''', batch=job['batch_id'], reason=str(failure))
            return True

        current = _visible(c, job['image_id'], clock(), job['cutoff'])
        if not current:
            _finish(c, job, 'skipped', '图片已删除或过期')
            return True
        verdict = decision.verdict
        if job['kind']=='preview':
            outcome = 'previewed'
        elif verdict=='delete' and not current[0]['favorite']:
            # Commit the catalog and its audit entry together. Periodic cleanup
            # removes orphaned files without leaving a broken visible image.
            remove_image_records(c, job['image_id'])
            outcome = 'deleted'
        elif verdict=='keep':
            if job['auto_favorite']:
                run(c, 'UPDATE images SET favorite=1 WHERE id=:id', id=job['image_id'])
            outcome = 'kept'
        else:
            outcome = 'protected' if verdict=='delete' else 'uncertain'
        _finish(c, job, outcome, decision.reason, verdict)
    return True
