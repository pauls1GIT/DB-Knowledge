from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from kedb.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
