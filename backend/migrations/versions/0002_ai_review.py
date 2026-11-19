from alembic import op
from collector.db import AI_SCHEMA

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    for statement in AI_SCHEMA.split(';'):
        if statement.strip():
            op.execute(statement)


def downgrade():
    raise RuntimeError('为保护识别设置和历史记录，请使用备份恢复')
