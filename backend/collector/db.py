import os
from pathlib import Path
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text

SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), days INTEGER NOT NULL DEFAULT 5, budget INTEGER NOT NULL DEFAULT 5368709120, password TEXT NOT NULL DEFAULT '');
INSERT OR IGNORE INTO settings(id) VALUES(1);
CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, external_id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, removed INTEGER NOT NULL DEFAULT 0, last_event REAL);
CREATE TABLE IF NOT EXISTS receipts (digest TEXT PRIMARY KEY, received REAL NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, digest TEXT UNIQUE NOT NULL, source_id INTEGER REFERENCES sources(id), received REAL NOT NULL, published REAL NOT NULL, sender TEXT, body TEXT);
CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, format TEXT NOT NULL, width INTEGER, height INTEGER, size INTEGER, favorite INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', state TEXT NOT NULL DEFAULT 'saved');
CREATE TABLE IF NOT EXISTS occurrences (id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL REFERENCES messages(id), position INTEGER NOT NULL, image_id TEXT REFERENCES images(id), received REAL NOT NULL, expires REAL NOT NULL, url TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'waiting', attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', UNIQUE(message_id,position));
CREATE INDEX IF NOT EXISTS occurrence_expiry ON occurrences(expires);
CREATE INDEX IF NOT EXISTS occurrence_image ON occurrences(image_id);
CREATE INDEX IF NOT EXISTS occurrence_task ON occurrences(state,next_try);
CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS runtime (id INTEGER PRIMARY KEY CHECK(id=1), heartbeat REAL NOT NULL DEFAULT 0, online INTEGER NOT NULL DEFAULT 0, worker REAL NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO runtime(id) VALUES(1);
'''

class Store:
    def __init__(self, root=None):
        self.root = Path(root or os.getenv('DATA_DIR', 'data')).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.media = self.root / 'media'
        self.media.mkdir(exist_ok=True)
        self.engine = create_engine('sqlite:///' + str(self.root / 'collector.db'), connect_args={'check_same_thread': False, 'timeout': 30})
        @event.listens_for(self.engine, 'connect')
        def setup(db, _):
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA busy_timeout=30000')

    def init(self):
        with self.engine.begin() as c:
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    c.exec_driver_sql(statement)

    @contextmanager
    def tx(self):
        with self.engine.connect() as c:
            c.exec_driver_sql('BEGIN IMMEDIATE')
            try:
                yield c
                c.commit()
            except BaseException:
                c.rollback()
                raise

def rows(c, sql, **params):
    return [dict(r) for r in c.execute(text(sql), params).mappings()]

def run(c, sql, **params):
    return c.execute(text(sql), params)

VISIBLE = "i.state='saved' AND (i.favorite=1 OR o.expires>:now)"
