"""Engine and transaction boundary."""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

def make_engine(url=None,**kwargs):
    url=url or os.getenv("EFS_DATABASE_URL")
    if not url: raise RuntimeError("EFS_DATABASE_URL must be configured")
    return create_engine(url,pool_pre_ping=True,**kwargs)

@contextmanager
def unit_of_work(engine):
    factory=sessionmaker(engine,expire_on_commit=False)
    with factory.begin() as session:
        yield session
