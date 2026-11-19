import argparse
import getpass
import sqlite3
import shutil
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from .db import Store, run, rows
from .service import cleanup

def backup_favorites(store, out):
    if out.exists() or out.is_symlink():
        raise FileExistsError(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.shitu-backup-', dir=out.parent) as temp:
        staged = Path(temp) / 'backup'
        media = staged / 'media'
        media.mkdir(parents=True)
        # Keep the database snapshot and both files of each favorite in sync.
        with store.tx() as c:
            with closing(sqlite3.connect(store.root / 'collector.db')) as source, \
                 closing(sqlite3.connect(staged / 'collector.db')) as target:
                source.backup(target)
            for image in rows(c, 'SELECT id, size FROM images WHERE favorite=1'):
                for suffix in ('.original', '.jpg'):
                    name = image['id'] + suffix
                    original = store.media / name
                    expected = image['size'] if suffix == '.original' else original.stat().st_size
                    shutil.copy2(original, media / name)
                    if not expected or (media / name).stat().st_size != expected:
                        raise OSError(f'收藏文件大小校验失败：{name}')

        backup = Store(staged)
        try:
            with backup.tx() as c:
                run(c, 'DELETE FROM occurrences WHERE image_id IS NULL OR image_id IN (SELECT id FROM images WHERE favorite=0)')
                run(c, 'DELETE FROM images WHERE favorite=0')
                run(c, 'DELETE FROM messages WHERE NOT EXISTS(SELECT 1 FROM occurrences WHERE message_id=messages.id)')
                run(c, 'DELETE FROM sessions')
                run(c, 'DELETE FROM ai_batches')
                run(c, 'UPDATE ai_settings SET enabled=0 WHERE id=1')
        finally:
            backup.engine.dispose()
        staged.rename(out)

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
        backup_favorites(store, Path(args.output))
        print('收藏备份完成；请复制到服务器外并按日期轮换。')
if __name__=='__main__':
    main()
