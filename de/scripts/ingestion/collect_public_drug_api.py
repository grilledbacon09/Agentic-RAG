"""
[수집 1] 공공데이터포털 - 의약품 개요정보 (e약은요)
라이선스: 공공누리 1유형 (상업적 이용 가능)
저장경로: s3://bucket/bronze/api/public_data/YYYY-MM-DD/
"""
import os
import sys
import time
from pathlib import Path

import requests
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

sys.path.insert(0, str(Path(__file__).parent.parent))
from utils_s3 import bronze_key, upload_json, key_exists

API_KEY = os.getenv("PUBLIC_API_KEY")
BASE_URL = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
NUM_OF_ROWS = 100


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
def fetch_page(page_no: int) -> dict:
    params = {
        "serviceKey": API_KEY,
        "pageNo": page_no,
        "numOfRows": NUM_OF_ROWS,
        "type": "json",
    }
    res = requests.get(BASE_URL, params=params, timeout=30)
    res.raise_for_status()
    return res.json()


def main():
    logger.info("=" * 50)
    logger.info("공공데이터 의약품 정보 수집 시작 (전체 수집)")
    logger.info("=" * 50)

    if not API_KEY:
        logger.error("PUBLIC_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    # 1페이지로 전체 건수 먼저 확인
    first = fetch_page(1)
    total_count = first.get("body", {}).get("totalCount", 0)
    total_pages = (total_count // NUM_OF_ROWS) + 1
    logger.info(f"전체 데이터: {total_count}건 / {total_pages}페이지")

    collected = 0
    for page_no in range(1, total_pages + 1):
        s3_key = bronze_key("api/public_data", f"all_p{page_no:04d}.json")

        if key_exists(s3_key):
            logger.debug(f"  스킵 (이미 존재): p{page_no}")
            continue

        try:
            data = fetch_page(page_no) if page_no > 1 else first
        except Exception as e:
            logger.error(f"  ❌ 페이지 {page_no} 실패: {e}")
            continue

        items = data.get("body", {}).get("items", [])
        if not items:
            break

        payload = {
            "source": "e약은요_공공데이터포털",
            "license": "공공누리1유형",
            "page_no": page_no,
            "total_count": total_count,
            "num_items": len(items),
            "items": items,
        }

        upload_json(payload, s3_key)
        collected += len(items)
        logger.info(f"  📄 페이지 {page_no}/{total_pages}: {len(items)}건 (누적: {collected}건)")

        time.sleep(0.5)

    logger.info(f"\n✅ 수집 완료: {collected}건")


if __name__ == "__main__":
    main()