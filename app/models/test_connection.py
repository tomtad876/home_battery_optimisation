from sqlalchemy import create_engine
import os

url = os.getenv("DATABASE_URL")
print(url)