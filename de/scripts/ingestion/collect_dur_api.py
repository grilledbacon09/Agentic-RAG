"""
[수집 2] 식약처 DURPrdlstInfoService03 - 의약품 안전사용 금기 정보
라이선스: 공공누리 1유형 (상업적 이용 가능)
저장경로: s3://bucket/bronze/api/dur/YYYY-MM-DD/

확인된 유효 오퍼레이션 (2026-08-30 기준):
  - getUsjntTabooInfoList03      병용금기    797,458건
  - getPwnmTabooInfoList03       임부금기     16,079건
  - getCpctyAtentInfoList03      용량주의      6,621건
  - getOdsnAtentInfoList03       노인주의      1,983건
  - getEfcyDplctInfoList03       효능군중복    7,064건
  - getSpcifyAgrdeTabooInfoList03 특정연령대금기2,682건
  - getMdctnPdAtentInfoList03    투여기간주의    644건
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
BASE_URL = "https://apis.data.go.kr/1471000/DURPrdlstInfoService03"
NUM_OF_ROWS = 100

DUR_TYPES = {
    "combination_ban": {
        "op": "getUsjntTabooInfoList03",
        "desc": "병용금기",
    },
    "pregnancy_ban": {
        "op": "getPwnmTabooInfoList03",
        "desc": "임부금기",
    },
    "dose_caution": {
        "op": "getCpctyAtentInfoList03",
        "desc": "용량주의",
    },
    "elderly_caution": {
        "op": "getOdsnAtentInfoList03",
        "desc": "노인주의",
    },
    "effect_duplicate": {
        "op": "getEfcyDplctInfoList03",
        "desc": "효능군중복",
    },
    "age_specific_ban": {
        "op": "getSpcifyAgrdeTabooInfoList03",
        "desc": "특정연령대금기",
    },
    "dosing_period_caution": {
        "op": "getMdctnPdAtentInfoList03",
        "desc": "투여기간주의",
    },
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
def fetch_page(op: str, page_no: int) -> dict:
    url = f"{BASE_URL}/{op}"
    res = requests.get(url, params={
        "serviceKey": API_KEY,
        "pageNo": page_no,
        "numOfRows": NUM_OF_ROWS,
        "type": "json",
    }, timeout=30)
    res.raise_for_status()
    data = res.json()

    # 서비스 폐기 응답 감지 (200이지만 에러인 경우)
    if "OpenAPI_ServiceResponse" in data:
        err = data["OpenAPI_ServiceResponse"]["cmmMsgHeader"]
        raise ValueError(f"API 오류: {err.get('returnAuthMsg')}")

    return data


def collect_dur_type(type_key: str, info: dict) -> int:
    logger.info(f"▶ [{info['desc']}] 수집 시작")

    # 1페이지로 전체 건수 확인
    try:
        first = fetch_page(info["op"], 1)
    except Exception as e:
        logger.warning(f"  ⚠️ [{info['desc']}] 스킵 (API 미지원): {e}")
        return 0

    total_count = first.get("body", {}).get("totalCount", 0)
    total_pages = (total_count // NUM_OF_ROWS) + 1
    logger.info(f"  전체: {total_count}건 / {total_pages}페이지")

    collected = 0
    for page_no in range(1, total_pages + 1):
        s3_key = bronze_key("api/dur", f"{type_key}_p{page_no:04d}.json")

        if key_exists(s3_key):
            logger.debug(f"  스킵 (이미 존재): p{page_no}")
            continue

        try:
            data = fetch_page(info["op"], page_no) if page_no > 1 else first
        except Exception as e:
            logger.error(f"  ❌ 페이지 {page_no} 실패: {e}")
            continue

        items = data.get("body", {}).get("items", [])
        if not items:
            break

        payload = {
            "source": "DURPrdlstInfoService03_식약처",
            "license": "공공누리1유형",
            "type": type_key,
            "description": info["desc"],
            "page_no": page_no,
            "total_count": total_count,
            "num_items": len(items),
            "items": items,
        }

        upload_json(payload, s3_key)
        collected += len(items)
        logger.info(f"  📄 [{info['desc']}] p{page_no}/{total_pages}: {len(items)}건 (누적: {collected}건)")

        time.sleep(0.3)

    logger.info(f"  ✅ [{info['desc']}] 완료: {collected}건")
    return collected


def main():
    logger.info("=" * 50)
    logger.info("DUR 의약품 금기 정보 수집 시작")
    logger.info("=" * 50)

    if not API_KEY:
        logger.error("PUBLIC_API_KEY 환경변수가 없습니다.")
        sys.exit(1)

    total = 0
    results = {}
    for type_key, info in DUR_TYPES.items():
        count = collect_dur_type(type_key, info)
        results[type_key] = count
        total += count

    logger.info("=" * 50)
    logger.info("수집 결과 요약")
    logger.info("=" * 50)
    for type_key, count in results.items():
        desc = DUR_TYPES[type_key]["desc"]
        logger.info(f"  {desc}: {count}건")
    logger.info(f"  전체 합계: {total}건")


if __name__ == "__main__":
    main()