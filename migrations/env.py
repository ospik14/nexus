from alembic import context

from nexus.config import Settings
from nexus.database import database_url, make_engine
from nexus.models import Base

settings = Settings()

if context.is_offline_mode():
    context.configure(url=database_url(settings), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    settings.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    engine = make_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
