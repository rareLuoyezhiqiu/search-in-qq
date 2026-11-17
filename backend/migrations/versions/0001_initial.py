from alembic import op
from collector.db import SCHEMA
revision='0001'
down_revision=None
branch_labels=None
depends_on=None

def upgrade():
    for statement in SCHEMA.split(';'):
        if statement.strip():
            op.execute(statement)

def downgrade():
    raise RuntimeError('为保护持久数据，请使用备份恢复而不是破坏性降级')
