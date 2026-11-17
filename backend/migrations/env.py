from alembic import context
from collector.db import Store
store=Store()
with store.engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
