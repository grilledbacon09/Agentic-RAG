"""
pgvector 검색 테스트 스크립트
사용법: python scripts/test_vectordb.py
"""
import os
import json
import psycopg2
import numpy as np
from dotenv import load_dotenv
from pathlib import Path
from sentence_transformers import SentenceTransformer

load_dotenv(Path(__file__).parent.parent / "config" / ".env")

# ── DB 연결 설정 ─────────────────────────────────────────────
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DB   = os.getenv("PG_DB", "drug_rag")
PG_USER = os.getenv("PG_USER", "airflow")
PG_PASS = os.getenv("PG_PASSWORD", "airflow")

# ── doc_type 설명 ────────────────────────────────────────────
DOC_TYPE_DESC = {
    "drug_efficacy":    "약품 효능/적응증",
    "drug_usage":       "용법/용량/복용 스케줄",
    "drug_caution":     "주의사항/경고",
    "drug_side_effect": "부작용/이상반응",
    "dur_interaction":  "병용금기/임부금기 등",
    "symptom_info":     "질환 일반 정보",
    "symptom_redflag":  "위험 증상/병원 방문 필요",
}

VALID_DOC_TYPES = list(DOC_TYPE_DESC.keys()) + ["전체"]


def connect_db():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, dbname=PG_DB,
        user=PG_USER, password=PG_PASS
    )


def load_model():
    print("임베딩 모델 로딩 중... (첫 실행 시 시간 소요)")
    model = SentenceTransformer("intfloat/multilingual-e5-large")
    print("모델 로드 완료\n")
    return model


def search(conn, model, query: str, doc_type: str = None, top_k: int = 5) -> list:
    """벡터 유사도 검색 + 중복 제거"""
    q_emb = model.encode(f"query: {query}", normalize_embeddings=True).tolist()
    fetch_k = top_k * 10

    with conn.cursor() as cur:
        if doc_type and doc_type != "전체":
            cur.execute('''
                SELECT name, source_name, item_url, text, metadata,
                       1-(embedding <=> %s::vector) AS score
                FROM drug_documents
                WHERE doc_type = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            ''', (q_emb, doc_type, q_emb, fetch_k))
        else:
            cur.execute('''
                SELECT name, source_name, item_url, text, metadata,
                       1-(embedding <=> %s::vector) AS score
                FROM drug_documents
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            ''', (q_emb, q_emb, fetch_k))
        rows = cur.fetchall()

    # 중복 제거 (parent_doc_id 또는 name 기준)
    seen = set()
    results = []
    for name, source, url, text, meta, score in rows:
        meta_dict = json.loads(meta) if isinstance(meta, str) else (meta or {})
        dedup_key = meta_dict.get("parent_doc_id") or name
        if dedup_key not in seen:
            seen.add(dedup_key)
            results.append({
                "name":    name,
                "source":  source,
                "url":     url,
                "text":    text,
                "score":   score,
                "metadata": meta_dict,
            })
        if len(results) >= top_k:
            break

    return results


def print_results(results: list, query: str, doc_type: str):
    print(f"\n{'='*60}")
    print(f"쿼리: {query}")
    print(f"범위: {DOC_TYPE_DESC.get(doc_type, '전체')}")
    print(f"{'='*60}")

    if not results:
        print("검색 결과 없음")
        return

    for i, r in enumerate(results, 1):
        print(f"\n[{i}] 유사도: {r['score']:.3f}")
        print(f"  약품/질환명: {r['name']}")
        print(f"  출처: {r['source']}")
        if r['url']:
            print(f"  URL: {r['url']}")

        # structured_usage 있으면 출력
        su = r['metadata'].get('structured_usage', {})
        if su:
            print(f"  복용 정보:")
            if su.get('age_groups'):
                print(f"    대상: {', '.join(su['age_groups'])}")
            if su.get('dose'):
                d = su['dose']
                print(f"    1회 용량: {d.get('amount','')} {d.get('unit','')}")
            if su.get('frequency'):
                print(f"    1일 횟수: {su['frequency'].get('times_per_day','')}회")
            if su.get('timing'):
                timings = [f"{t['type']}{str(t.get('minutes','')+'분' if t.get('minutes') else '')}" for t in su['timing']]
                print(f"    복용 시기: {', '.join(timings)}")
            if su.get('max_days'):
                print(f"    최대 복용: {su['max_days'].get('max_days','')}일")

        # DUR 정보 있으면 출력
        if r['metadata'].get('dur_type'):
            print(f"  금기 유형: {r['metadata'].get('dur_desc','')}")
            if r['metadata'].get('ingredient_a'):
                print(f"  성분A: {r['metadata']['ingredient_a']}")
            if r['metadata'].get('ingredient_b'):
                print(f"  성분B: {r['metadata']['ingredient_b']}")
            if r['metadata'].get('reason'):
                print(f"  사유: {r['metadata']['reason']}")

        print(f"  내용: {r['text'][:150]}...")


def print_doc_types():
    print("\n사용 가능한 doc_type:")
    for dt, desc in DOC_TYPE_DESC.items():
        print(f"  {dt:<20} : {desc}")
    print(f"  {'전체':<20} : 모든 doc_type 검색")


def print_db_status(conn):
    """DB 현황 출력"""
    with conn.cursor() as cur:
        cur.execute('''
            SELECT doc_type, COUNT(*)
            FROM drug_documents
            GROUP BY doc_type
            ORDER BY COUNT(*) DESC
        ''')
        rows = cur.fetchall()

    print("\n=== DB 현황 ===")
    total = 0
    for doc_type, cnt in rows:
        desc = DOC_TYPE_DESC.get(doc_type, "")
        print(f"  {doc_type:<20} {cnt:>8,}건  ({desc})")
        total += cnt
    print(f"  {'합계':<20} {total:>8,}건")


def main():
    print("=" * 60)
    print("  pgvector 검색 테스트")
    print("=" * 60)

    # DB 연결
    try:
        conn = connect_db()
        print("✅ DB 연결 성공")
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return

    # DB 현황
    print_db_status(conn)

    # 모델 로드
    model = load_model()

    # 대화형 검색
    print("\n검색을 시작합니다. 종료: 'q' 입력")
    print_doc_types()

    while True:
        print("\n" + "-" * 40)
        query = input("검색어 입력: ").strip()
        if query.lower() in ("q", "quit", "exit"):
            print("종료합니다.")
            break
        if not query:
            continue

        # doc_type 선택
        print_doc_types()
        doc_type_input = input("doc_type 입력 (Enter = 전체): ").strip()
        doc_type = doc_type_input if doc_type_input in VALID_DOC_TYPES else "전체"

        # 결과 수
        top_k_input = input("결과 수 입력 (Enter = 5): ").strip()
        try:
            top_k = int(top_k_input) if top_k_input else 5
        except ValueError:
            top_k = 5

        # 검색 실행
        try:
            results = search(conn, model, query, doc_type, top_k)
            print_results(results, query, doc_type)
        except Exception as e:
            conn.rollback()
            print(f"❌ 검색 오류: {e}")

    conn.close()


if __name__ == "__main__":
    main()
