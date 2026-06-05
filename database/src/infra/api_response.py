"""공공데이터포털 API JSON 응답 정규화."""

from __future__ import annotations

from typing import Any


def _unwrap_body(data: dict[str, Any]) -> dict[str, Any]:
    if "body" in data:
        return data.get("body") or {}
    response = data.get("response")
    if isinstance(response, dict):
        return response.get("body") or {}
    return {}


def extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """API 응답에서 item 리스트를 추출합니다."""
    body = _unwrap_body(data)
    items = body.get("items")
    if items is None:
        return []

    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]

    if isinstance(items, dict):
        item = items.get("item")
        if item is None:
            return []
        if isinstance(item, list):
            return [row for row in item if isinstance(row, dict)]
        if isinstance(item, dict):
            return [item]

    return []


def extract_total_count(data: dict[str, Any]) -> int:
    body = _unwrap_body(data)
    try:
        return int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        return 0
