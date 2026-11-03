"""Alembic environment: runs migrations on the connection `conveyor.storage.migrate` passes in.

There is no `alembic.ini` and no offline (SQL script) mode: migrations always run inside the
caller's transaction, on the connection stored in `config.attributes["connection"]`.
"""

# ruff: noqa: INP001 -- Alembic runs env.py by path; migrations/ is a script folder, not a package

from alembic import context
from sqlalchemy import Connection

from conveyor.storage.schema import Base

connection: Connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    # SQLite cannot ALTER most constraints; batch mode rebuilds the table instead.
    render_as_batch=True,
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
