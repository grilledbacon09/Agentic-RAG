"""공공데이터포털 API 키 조회."""

from __future__ import annotations

import os


def get_drug_api_key() -> str:
    """e약은요(DrbEasyDrugInfoService) serviceKey."""
    for name in ("API_KEY_1", "PUBLIC_DATA_API_KEY", "DATA_GO_KR_API_KEY"):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def get_dur_api_key() -> str:
    """DUR 병용금기 API serviceKey."""
    for name in ("API_KEY_2", "PUBLIC_DATA_API_KEY_DUR", "PUBLIC_DATA_API_KEY"):
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def require_drug_api_key() -> str:
    key = get_drug_api_key()
    if not key:
        raise RuntimeError(
            "e약은요 API 키가 없습니다. DE/.env에 API_KEY_1 또는 "
            "PUBLIC_DATA_API_KEY 를 설정하세요. "
            "(공공데이터포털 DrbEasyDrugInfoService)"
        )
    return key
