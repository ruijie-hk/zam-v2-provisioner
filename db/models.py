from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class Device(Base):
    __tablename__ = "devices"
    
    sn = Column(String, primary_key=True)
    mac = Column(String, unique=True, nullable=True)
    ip = Column(String, nullable=True)
    template_id = Column(String, nullable=True)
    last_seen = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="registered")

class Template(Base):
    __tablename__ = "templates"
    
    id = Column(String, primary_key=True)
    name = Column(String)
    description = Column(Text)
    base_config = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class DeviceOverride(Base):
    __tablename__ = "device_overrides"
    
    sn = Column(String, primary_key=True)
    config = Column(JSON)
    updated_at = Column(DateTime, default=datetime.utcnow)

class Deployment(Base):
    __tablename__ = "deployments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    sn = Column(String)
    template_id = Column(String, nullable=True)
    config_hash = Column(String)
    status = Column(String)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    switch_report = Column(JSON, nullable=True)

# SQLite for PoC
engine = create_engine("sqlite:///./zam.db")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
