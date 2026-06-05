"""공공데이터포털 API 전체 페이지 수집 → Bronze MinIO.

실행 (DE 루트):
    python src/collector/api_ingestion.py
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import bootstrap  # noqa: E402
import requests
import set_client
from api_keys import get_drug_api_key, get_dur_api_key, require_drug_api_key
from api_response import extract_items, extract_total_count

NUM_OF_ROWS = int(os.getenv("API_PAGE_SIZE", "100"))
MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "5"))
INGEST_TABOO = os.getenv("INGEST_TABOO", "true").lower() in {"1", "true", "yes"}


def _api_config() -> list[dict]:
    configs = [
        {
            "name": "drug_info",
            "source": "drug_info",
            "url": "https://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList",
            "service_key": get_drug_api_key(),
        },
    ]
    if INGEST_TABOO:
        dur_key = get_dur_api_key()
        if dur_key:
            configs.append({
                "name": "taboo_info",
                "source": "taboo_info",
                "url": "https://apis.data.go.kr/1471000/DURPrdlstInfoService03/getUsjntTabooInfoList03",
                "service_key": dur_key,
            })
        else:
            print(
                "[!] DUR(taboo) 수집 스킵: API_KEY_2 또는 PUBLIC_DATA_API_KEY_DUR 없음",
                flush=True,
            )
    return [c for c in configs if c.get("service_key")]


def ingest_api(api_info: dict) -> None:
    api_name = api_info["name"]
    base_url = api_info["url"]
    service_key = api_info["service_key"]
    all_items: list[dict] = []
    page_no = 1
    total_count = 0

    print(f"[*] Starting full ingestion: {api_name}", flush=True)

    while True:
        params = {
            "serviceKey": service_key,
            "type": "json",
            "numOfRows": NUM_OF_ROWS,
            "pageNo": page_no,
        }
        success = False
        items: list[dict] = []

        for attempt in range(MAX_RETRIES):
            try:
                response = requests.get(base_url, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()
                items = extract_items(data)
                total_count = extract_total_count(data) or total_count

                if items:
                    all_items.extend(items)

                total_pages = (
                    math.ceil(total_count / NUM_OF_ROWS) if total_count > 0 else "?"
                )
                print(
                    f"    -> Progress: Page {page_no}/{total_pages} "
                    f"({len(all_items)}/{total_count} items collected)",
                    flush=True,
                )
                success = True
                break
            except Exception as exc:
                print(
                    f"    [!] Attempt {attempt + 1} failed for page {page_no}: {exc}",
                    flush=True,
                )
                time.sleep(2 ** attempt)

        if not success:
            print(f"[!] Error ingesting {api_name} at page {page_no}", flush=True)
            break

        if total_count and len(all_items) >= total_count:
            break
        if not items:
            break

        page_no += 1
        time.sleep(float(os.getenv("API_PAGE_DELAY", "0.2")))

    if all_items:
        save_to_bronze(api_info, all_items)
    else:
        print(f"[!] No data collected for {api_name}.", flush=True)


def save_to_bronze(api_info: dict, items: list[dict]) -> None:
    api_name = api_info["name"]
    source = api_info["source"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_key = f"{api_name}/{timestamp}.json"
    bucket_name = "bronze"

    storage_data = {
        "metadata": {
            "api_name": api_name,
            "collected_at": timestamp,
            "total_count": len(items),
        },
        "items": items,
    }

    set_client.s3.put_object(
        Bucket=bucket_name,
        Key=file_key,
        Body=json.dumps(storage_data, ensure_ascii=False),
    )

    conn = set_client.get_db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bronze_metadata (
            source, bucket, file_key, row_count, status, collected_at
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (source, bucket_name, file_key, len(items), "success", datetime.now()),
    )
    conn.commit()
    cur.close()
    conn.close()

    print(
        f"[+] Successfully ingested ALL {len(items)} records for {api_name}",
        flush=True,
    )


def main() -> None:
    require_drug_api_key()

    try:
        set_client.s3.create_bucket(Bucket="bronze")
    except Exception:
        pass

    configs = _api_config()
    if not configs:
        raise RuntimeError("실행 가능한 API 설정이 없습니다. API 키를 확인하세요.")

    for api in configs:
        ingest_api(api)


if __name__ == "__main__":
    main()
