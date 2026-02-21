# app/models/base.py
from sqlalchemy.orm import declarative_base

# Create a base class that all ORM models will inherit from
Base = declarative_base()