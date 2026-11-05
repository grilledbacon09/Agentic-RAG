"""
[DIAG] "postgres 검색 실패, DE 미사용" 원인 단계별 확인
AI 서버(챗봇 백엔드)가 돌아가는 환경에서 그대로 실행하세요.
  python de/scripts/diag_vector_conn.py            # 접속~테이블~권한까지
  python de/scripts/diag_vector_conn.py --search   # + 임베딩 모델로 실제 검색 1회
"""
import os, socket, sys, time, traceback
from pathlib import Path

def step(n, msg): print(f"\n[{n}] {msg}")
def ok(m): print(f"   OK  {m}")
def ng(m): print(f"   FAIL {m}"); sys.exit(1)

step(1, ".env 로드 위치 / 실제 접속 정보")
env_file = None
try:
    from dotenv import load_dotenv
    for p in Path(__file__).resolve().parents:
        if (p / "config" / ".env").exists():
            env_file = p / "config" / ".env"; load_dotenv(env_file); break
except ImportError:
    print("   (python-dotenv 없음 → OS 환경변수만 사용)")
host = os.getenv("PG_HOST", "localhost"); port = int(os.getenv("PG_PORT", "5432"))
db = os.getenv("VECTOR_DB", "drug_rag"); user = os.getenv("PG_USER", "airflow")
print(f"   .env = {env_file}\n   → {user}@{host}:{port}/{db}  (PG_DB가 아니라 VECTOR_DB 를 읽음)")
if host in ("localhost", "127.0.0.1"):
    print("   ※ localhost = 로컬 docker postgres. 공용 서버는 43.200.194.39:5433 / drug_reader")

step(2, "TCP 연결 (EC2 보안그룹 / 서버 꺼짐 확인)")
try:
    socket.create_connection((host, port), timeout=5).close(); ok(f"{host}:{port} 열림")
except Exception as e:
    ng(f"{host}:{port} 연결 안 됨 → {e}\n   EC2 인스턴스 상태·퍼블릭 IP 변경·보안그룹 인바운드(내 IP) 확인")

step(3, "PostgreSQL 로그인")
try:
    import psycopg2
except ImportError:
    ng("psycopg2 미설치 → pip install psycopg2-binary")
try:
    conn = psycopg2.connect(host=host, port=port, dbname=db, user=user,
                            password=os.getenv("PG_PASSWORD", "airflow"), connect_timeout=5)
    conn.autocommit = True; cur = conn.cursor(); ok("로그인 성공")
except Exception as e:
    ng(f"{type(e).__name__}: {e}".strip())

step(4, "pgvector 확장")
cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
r = cur.fetchone(); ok(f"vector {r[0]}") if r else ng(f"DB '{db}'에 pgvector 없음 (DB 이름 확인)")

step(5, "테이블 존재 / 조회 권한 / 건수")
for t in ("drug_documents_v2", "drug_documents", "langchain_pg_embedding"):
    cur.execute("SELECT to_regclass(%s)", (f"public.{t}",))
    if not cur.fetchone()[0]:
        print(f"   -    {t:24} 없음"); continue
    cur.execute("SELECT has_table_privilege(current_user, %s, 'SELECT')", (t,))
    if not cur.fetchone()[0]:
        print(f"   FAIL {t:24} 있음, 그러나 {user} 조회 권한 없음"); continue
    cur.execute(f"SELECT count(*) FROM {t}"); print(f"   OK   {t:24} {cur.fetchone()[0]:,}건")
print("   ※ DE 공식 테이블은 drug_documents_v2 (vector_tools.TABLE). "
      "LangChain PGVector(collection_name=...)는 langchain_pg_embedding을 찾으므로 이 DB에선 결과 없음/에러")

cur.execute("SELECT doc_type, count(*) FROM drug_documents_v2 GROUP BY 1 ORDER BY 1")
for d, n in cur.fetchall(): print(f"        {d:18} {n:>8,}")

if "--search" in sys.argv:
    step(6, "임베딩 모델 + 실제 검색 (vector_tools.DrugVectorDB)")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from vector_tools import DrugVectorDB
        t0 = time.time()
        with DrugVectorDB() as v:
            rows = v.search_drugs(["머리가 아프고 열이 나요", "두통 발열 해열진통제"], top_k=3)
        ok(f"{len(rows)}건, {time.time()-t0:.1f}s → " + ", ".join(r["name"] for r in rows))
    except Exception:
        traceback.print_exc(); ng("검색 단계 실패 (위 traceback이 AI 쪽 except에 가려진 진짜 원인)")
print("\n모든 단계 통과 → DE 쪽은 정상. AI 코드의 except 블록에서 예외를 출력해 확인 필요")
