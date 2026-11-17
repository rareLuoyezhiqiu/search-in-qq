import argparse
import getpass
import sqlite3
import shutil
from pathlib import Path
from .db import Store, run, rows
from .service import cleanup

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['init','password','cleanup','backup'])
    parser.add_argument('--output')
    args=parser.parse_args()
    store=Store()
    if args.command in ('init','password'):
        from .api import passwords
        if args.command=='init':
            from alembic import command
            from alembic.config import Config
            command.upgrade(Config('alembic.ini'),'head')
        password=getpass.getpass('管理员密码（至少 12 位）: ')
        if len(password)<12:
            raise SystemExit('密码至少 12 位')
        with store.tx() as c:
            run(c,'UPDATE settings SET password=:p',p=passwords.hash(password))
            run(c,'DELETE FROM sessions')
    elif args.command=='cleanup':
        cleanup(store)
    else:
        if not args.output:
            raise SystemExit('请指定新的 --output 目录')
        out=Path(args.output)
        out.mkdir(parents=True,exist_ok=False)
        (out/'media').mkdir()
        # Freeze mutations while a separate read connection takes a consistent WAL snapshot.
        with store.tx() as c:
            source=sqlite3.connect(store.root/'collector.db')
            target=sqlite3.connect(out/'collector.db')
            source.backup(target)
            source.close()
            target.close()
            for i in rows(c,'SELECT id FROM images WHERE favorite=1'):
                for suffix in ('.original','.jpg'):
                    shutil.copy2(store.media/(i['id']+suffix),out/'media'/(i['id']+suffix))
        # Strip ordinary metadata and credentials from the exported database.
        backup=Store(out)
        with backup.tx() as c:
            run(c,'DELETE FROM occurrences WHERE image_id IS NULL OR image_id IN (SELECT id FROM images WHERE favorite=0)')
            run(c,'DELETE FROM images WHERE favorite=0')
            run(c,'DELETE FROM messages WHERE NOT EXISTS(SELECT 1 FROM occurrences WHERE message_id=messages.id)')
            run(c,'DELETE FROM sessions')
        backup.engine.dispose()
        print('收藏备份完成；请复制到服务器外并按日期轮换。')
if __name__=='__main__':
    main()
