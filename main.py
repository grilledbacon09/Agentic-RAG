# medicine-backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 💡 외부 파일로 완벽하게 격리시킨 라우터와 로더만 가져옵니다.
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

# 💡 AI 담당자가 구축한 진짜 RAG용 마스터 데이터를 서버 시작 시 로드합니다.
app.state.DRUGS = load_drugs("data/drugs.json")
app.state.SYMPTOMS = load_symptoms("data/symptoms.json")

# 💡 완벽하게 격리된 기능 경로 주소들만 허브(Hub)처럼 연결합니다.
app.include_router(diagnosis.router)
app.include_router(user.router)
app.include_router(medicines.router)

@app.get("/")
def read_root():
    return {"status": "running", "architecture": "Agentic-RAG Layered Architecture"}