"""전체 파이프라인 실행 전 환경 점검."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import create_vectordb
import set_client
from api_keys import get_drug_api_key, get_dur_api_key
from paths import MSD_LINKS_CSV, MSD_SYMPTOMS_HTML


def main() -> int:
    ok = True
    print("[*] DE full pipeline preflight", flush=True)

    try:
        hb = create_vectordb.get_client().heartbeat()
        print(f"[+] ChromaDB OK (heartbeat={hb})", flush=True)
    except Exception as exc:
        print(f"[!] ChromaDB 연결 실패: {exc}", flush=True)
        ok = False

    try:
        set_client.s3.list_buckets()
        print("[+] MinIO OK", flush=True)
    except Exception as exc:
        print(f"[!] MinIO 연결 실패: {exc}", flush=True)
        ok = False

    try:
        conn = set_client.get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        print("[+] PostgreSQL OK", flush=True)
    except Exception as exc:
        print(f"[!] PostgreSQL 연결 실패: {exc}", flush=True)
        ok = False

    drug_key = get_drug_api_key()
    if drug_key:
        print("[+] e약은요 API 키 설정됨", flush=True)
    else:
        print(
            "[!] e약은요 API 키 없음 → DE/.env 에 API_KEY_1 또는 PUBLIC_DATA_API_KEY 필요",
            flush=True,
        )
        ok = False

    dur_key = get_dur_api_key()
    if dur_key:
        print("[+] DUR API 키 설정됨", flush=True)
    else:
        print("[*] DUR API 키 없음 (taboo 수집은 스킵 가능)", flush=True)

    if MSD_SYMPTOMS_HTML.exists():
        print(f"[+] MSD 소스 있음: {MSD_SYMPTOMS_HTML}", flush=True)
    else:
        print(
            f"[*] MSD 소스 없음: {MSD_SYMPTOMS_HTML} "
            "(증상 DB는 API/시드 데이터만 사용)",
            flush=True,
        )

    if MSD_LINKS_CSV.exists():
        print(f"[+] MSD links.csv 있음: {MSD_LINKS_CSV}", flush=True)
    else:
        print("[*] MSD links.csv 없음 (msd_save_to_silver 스킵 가능)", flush=True)

    if ok:
        print("[PASS] preflight", flush=True)
        return 0

    print("[FAIL] preflight - 위 항목을 해결한 뒤 다시 실행하세요.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
