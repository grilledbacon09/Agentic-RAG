import os
from pathlib import Path

import boto3
import psycopg2
from dotenv import load_dotenv

_DE_ROOT = Path(__file__).resolve().parent.parent.parent
# graduation_project/.env  (_DE_ROOT → Agentic-RAG/ → graduation_project/)
_REPO_ROOT = _DE_ROOT.parent.parent
load_dotenv(_REPO_ROOT / ".env")

# 클라이언트 초기화 (S3/MinIO & Postgres)
s3 = boto3.client(
    's3',
    endpoint_url=os.getenv('MINIO_ENDPOINT'),
    aws_access_key_id=os.getenv('MINIO_ACCESS_KEY'),
    aws_secret_access_key=os.getenv('MINIO_SECRET_KEY')
)

def get_db_conn():
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )