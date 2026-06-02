# medicine-backend/main.py
# 실행방법

# 콘다 가상환경 실행 conda activate medi-env

# 서버 실행 uvicorn main:app --reload

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from api import diagnosis, user, medicines
from agents.loader import load_drugs, load_symptoms

app = FastAPI(title="의약품 통합 헬스케어 서버")

# CORS 허용 (React 포트 통신용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# RAG용 마스터 데이터를 서버 시작 시 로드
app.state.DRUGS = load_drugs("data/drugs.json")
app.state.SYMPTOMS = load_symptoms("data/symptoms.json")


app.include_router(diagnosis.router)
app.include_router(user.router)
app.include_router(medicines.router)

@app.get("/")
def read_root():
    return {"status": "running", "architecture": "Agentic-RAG Layered Architecture"}