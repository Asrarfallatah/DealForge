# backend/db/database.py

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please add it to your .env file.")

engine = create_engine(
    DATABASE_URL,
    echo=False,       
    pool_pre_ping=True 
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


def get_db():
  
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    
    from db import models  # مهم عشان SQLAlchemy يعرف كل المودلز

    Base.metadata.create_all(bind=engine)