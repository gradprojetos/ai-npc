import psycopg
import os

conn = psycopg.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD")
)

cur = conn.cursor()
cur.execute("SELECT version()")

print("PostgreSQL version:", cur.fetchone())

conn.close()
