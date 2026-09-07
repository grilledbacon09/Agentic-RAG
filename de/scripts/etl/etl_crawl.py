"""
[ETL 3] 크롤링 데이터 Bronze → Silver
입력:
  - s3://bucket/bronze/crawl/health_portal/
  - s3://bucket/bronze/crawl/health_kr/
출력:
  - s3://bucket/silver/symptoms/
  - s3://bucket/silver/drugs/crawl_drug/

수정 이력:
  v2: 필터링 강화
      - content 길이 최소값 적용 (100자 이하 제외)
      - URL에 gnrlzHealthInfoDtl 패턴 없으면 제외
      - 중복 이름 제거
      - 파일 크기 기반 필터 (실질 내용 없는 파일 제외)
"""
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / "config" / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils_s3 import list_keys, download_json, upload_json, silver_key

SOURCE_META = {
    "health_portal": {
        "source_name": "국가건강정보포털",
        "source_url": "https://health.kdca.go.kr",
        "license": "공공누리",
        "provider": "질병관리청",
    },
    "health_kr_disease": {
        "source_name": "약학정보원 질병정보",
        "source_url": "https://www.health.kr/researchInfo/disease.asp",
        "license": "비상업적 참조 목적",
        "provider": "약학정보원",
    },
    "health_kr_drug": {
        "source_name": "약학정보원 의약품정보",
        "source_url": "https://www.health.kr/searchDrug/search_detail.asp",
        "license": "비상업적 참조 목적",
        "provider": "약학정보원",
    },
}

# 유효한 질환 상세 URL 패턴
VALID_PORTAL_URL_KEYWORDS = ["gnrlzHealthInfoDtl"]

# 제외할 이름 패턴
SKIP_NAMES = {
    "FAQ", "뉴스레터", "카드뉴스", "이용안내", "소개",
    "사이트맵", "공지사항", "저작권", "개인정보", "관련링크",
    "이미지자료실", "동영상자료실", "OpenAPI", "건강담기",
    "검진기관", "병원약국", "노인 건강정보", "청소년 건강정보",
    "생애주기별 건강정보", "자료실", "건강소식",
}

MIN_CONTENT_LENGTH = 100  # 최소 내용 길이


def clean_text(text) -> str:
    if not text:
        return ""
    return " ".join(str(text).split()).strip()


def merge_content(content: dict) -> str:
    if not content:
        return ""
    parts = []
    for section, text in content.items():
        cleaned = clean_text(text)
        if cleaned:
            parts.append(f"[{section}] {cleaned}")
    return " | ".join(parts)


def is_valid_portal_item(data: dict) -> bool:
    """국가건강정보포털 항목 유효성 검사"""
    # 오류 항목 제외
    if "error" in data:
        return False

    # URL 패턴 검사 (질환 상세 페이지만)
    url = data.get("url", "")
    if not any(kw in url for kw in VALID_PORTAL_URL_KEYWORDS):
        return False

    # 이름 필터
    name = clean_text(data.get("name", ""))
    if not name or name in SKIP_NAMES:
        return False

    # 내용 최소 길이
    content = data.get("content", {})
    merged = merge_content(content)
    if len(merged) < MIN_CONTENT_LENGTH:
        return False

    return True


# ── 국가건강정보포털 ────────────────────────────────────────
def etl_health_portal() -> int:
    """
    v3: redflag_content 필드 처리 추가
    content → symptom_disease
    redflag_content → symptom_disease (has_redflag=True)
    """
    logger.info("▶ [국가건강정보포털] 정제 시작 (v3)")
    keys = [k for k in list_keys("bronze/crawl/health_portal/") if k.endswith(".json")]
    logger.info(f"  전체 파일: {len(keys)}개")

    transformed = []
    skipped = 0
    seen_names = set()

    for key in keys:
        try:
            data = download_json(key)
        except Exception as e:
            logger.warning(f"  스킵 [{key}]: {str(e)[:60]}")
            skipped += 1
            continue

        # 오류 항목 제외
        if "error" in data:
            skipped += 1
            continue

        name = clean_text(data.get("name", ""))
        if not name or name in SKIP_NAMES:
            skipped += 1
            continue

        # 이름 기준 중복 제거
        if name in seen_names:
            skipped += 1
            continue
        seen_names.add(name)

        content = data.get("content", {})
        redflag_content = data.get("redflag_content", {})
        has_redflag = data.get("has_redflag", False)

        # 일반 내용 병합
        merged = merge_content(content)
        # redflag 내용 병합
        merged_redflag = merge_content(redflag_content)

        # 내용 최소 길이 필터
        if len(merged) < MIN_CONTENT_LENGTH and len(merged_redflag) < MIN_CONTENT_LENGTH:
            skipped += 1
            continue

        base_meta = {
            "name": name,
            "system_code": data.get("system_code", ""),
            "system_name": data.get("system_name", ""),
            "item_url": data.get("url", ""),
            "brd_sid": data.get("brd_sid", ""),
            **SOURCE_META["health_portal"],
            "etl_at": datetime.now().isoformat(),
        }

        # 일반 내용 저장
        if len(merged) >= MIN_CONTENT_LENGTH:
            transformed.append({
                "doc_id": f"portal_{data.get('system_code','')}_{name}_info",
                "doc_type": "symptom_disease",
                "text": f"질환명: {name} | {merged}",
                "metadata": {**base_meta, "has_redflag": False},
            })

        # Red flag 내용 별도 저장
        if len(merged_redflag) >= MIN_CONTENT_LENGTH:
            transformed.append({
                "doc_id": f"portal_{data.get('system_code','')}_{name}_redflag",
                "doc_type": "symptom_disease",
                "text": f"질환명: {name} | {merged_redflag}",
                "metadata": {**base_meta, "has_redflag": True},
            })

    logger.info(f"  변환: {len(transformed)}건 / 스킵: {skipped}건")

    saved = 0
    for i in range(0, len(transformed), 100):
        batch = transformed[i:i+100]
        s_key = silver_key("symptoms/health_portal", f"batch_{i//100:04d}.json")
        upload_json({"count": len(batch), "items": batch}, s_key)
        saved += len(batch)

    logger.info(f"  ✅ {saved}건 저장")
    return saved


# ── 약학정보원 질병정보 ─────────────────────────────────────
def etl_health_kr_disease() -> int:
    logger.info("▶ [약학정보원 질병정보] 정제 시작")
    keys = [k for k in list_keys("bronze/crawl/health_kr/")
            if "disease_" in k and k.endswith(".json")]
    logger.info(f"  전체 파일: {len(keys)}개")

    transformed, skipped = [], 0

    for key in keys:
        try:
            data = download_json(key)
        except Exception as e:
            logger.warning(f"  스킵 [{key}]: {str(e)[:60]}")
            skipped += 1
            continue

        if not data or "error" in data:
            skipped += 1
            continue

        content = data.get("content", {})
        basic_info = data.get("basic_info", {})
        merged = merge_content(content)

        # 최소 내용 길이 필터
        if len(merged) < MIN_CONTENT_LENGTH and not basic_info:
            skipped += 1
            continue

        name = clean_text(data.get("name", ""))
        text = f"질환명: {name}"
        korean_name = basic_info.get("질환명 (한글)", "")
        if korean_name:
            text += f" ({clean_text(korean_name)})"
        if merged:
            text += f" | {merged}"

        transformed.append({
            "doc_id": f"disease_{data.get('idx', '')}",
            "doc_type": "symptom_disease",
            "text": text,
            "metadata": {
                "name": name,
                "idx": data.get("idx"),
                "item_url": data.get("url", ""),
                "basic_info": {k: clean_text(v) for k, v in basic_info.items() if v},
                **SOURCE_META["health_kr_disease"],
                "etl_at": datetime.now().isoformat(),
            }
        })

    logger.info(f"  변환: {len(transformed)}건 / 스킵: {skipped}건")

    saved = 0
    for i in range(0, len(transformed), 100):
        batch = transformed[i:i+100]
        s_key = silver_key("symptoms/health_kr_disease", f"batch_{i//100:04d}.json")
        upload_json({"count": len(batch), "items": batch}, s_key)
        saved += len(batch)

    logger.info(f"  ✅ {saved}건 저장")
    return saved


# ── 약학정보원 일반의약품 ───────────────────────────────────
def etl_health_kr_drug() -> int:
    logger.info("▶ [약학정보원 일반의약품] 정제 시작")
    keys = [k for k in list_keys("bronze/crawl/health_kr/")
            if "drug_" in k and k.endswith(".json")]
    logger.info(f"  전체 파일: {len(keys)}개")

    transformed, skipped = [], 0
    seen_names = set()

    for key in keys:
        try:
            data = download_json(key)
        except Exception as e:
            logger.warning(f"  스킵 [{key}]: {str(e)[:60]}")
            skipped += 1
            continue

        if not data:
            skipped += 1
            continue

        content = data.get("content", {})
        name = clean_text(data.get("name", ""))

        if not name or not content:
            skipped += 1
            continue

        if name in seen_names:
            skipped += 1
            continue
        seen_names.add(name)

        parts = [f"약품명: {name}"]
        field_labels = {
            "효능효과": "효능",
            "용법용량": "용법",
            "주의사항": "주의사항",
            "부작용": "부작용",
            "성분함량": "성분",
            "보관방법": "보관",
        }
        for field, label in field_labels.items():
            val = clean_text(content.get(field, ""))
            if val:
                parts.append(f"{label}: {val}")

        text = " | ".join(parts)

        # 최소 내용 길이 필터
        if len(text) < MIN_CONTENT_LENGTH:
            skipped += 1
            continue

        transformed.append({
            "doc_id": f"drug_kr_{name}",
            "doc_type": "drug_info",
            "text": text,
            "metadata": {
                "name": name,
                "item_url": data.get("url", ""),
                "images": data.get("images", []),
                **SOURCE_META["health_kr_drug"],
                "etl_at": datetime.now().isoformat(),
            }
        })

    logger.info(f"  변환: {len(transformed)}건 / 스킵: {skipped}건")

    saved = 0
    for i in range(0, len(transformed), 200):
        batch = transformed[i:i+200]
        s_key = silver_key("drugs/health_kr_drug", f"batch_{i//200:04d}.json")
        upload_json({"count": len(batch), "items": batch}, s_key)
        saved += len(batch)

    logger.info(f"  ✅ {saved}건 저장")
    return saved


def main():
    logger.info("=" * 50)
    logger.info("[ETL 3] 크롤링 데이터 정제 시작 (v2 - 필터링 강화)")
    logger.info("=" * 50)

    total = 0
    total += etl_health_portal()
    # total += etl_health_kr_disease()
    # total += etl_health_kr_drug()

    logger.info("=" * 50)
    logger.info(f"전체 완료: {total}건")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()