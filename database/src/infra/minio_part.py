"""MinIO 로컬 볼륨 part.1 파일에서 JSON 추출.

MinIO는 객체 앞에 bitrot 헤더가 붙고, 대용량 파일 중간에 바이너리가 섞일 수 있습니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _loads_from_offset(raw: bytes, start: int) -> Any:
    text = raw[start:].decode("utf-8", errors="replace")
    text = text.strip("\x00").strip()
    return json.loads(text)


def _candidate_offsets(raw: bytes) -> list[int]:
    markers = (
        b'{"metadata"',
        b'{"items"',
        b'{"api_name"',
        b'{"body"',
        b"{",
        b"[",
    )
    offsets: list[int] = []
    seen: set[int] = set()
    for marker in markers:
        start = 0
        while True:
            idx = raw.find(marker, start)
            if idx < 0:
                break
            if idx not in seen:
                seen.add(idx)
                offsets.append(idx)
            start = idx + 1
    return sorted(offsets, key=lambda i: (
        0 if raw[i:i + 12] == b'{"metadata"' else 1,
        i,
    ))


def _extract_bronze_drug_items(raw: bytes) -> list[dict]:
    """bronze drug_info part.1: items 배열을 항목 단위로 복구."""
    text = raw.decode("utf-8", errors="replace")
    anchor = text.find('"items": [')
    if anchor < 0:
        anchor = text.find('"items":[')
    if anchor < 0:
        return []

    content = text[anchor:]
    open_idx = content.find("[")
    if open_idx < 0:
        return []
    content = content[open_idx + 1 :]

    close_idx = content.rfind("]")
    if close_idx > 0:
        content = content[:close_idx]

    splitter = '}, {"entpName"'
    parts = content.split(splitter)
    items: list[dict] = []

    for i, part in enumerate(parts):
        chunk = part.strip()
        if not chunk:
            continue
        if i == 0:
            obj_text = chunk
            if not obj_text.startswith("{"):
                obj_text = "{" + obj_text
        else:
            obj_text = '{"entpName"' + chunk
        if not obj_text.endswith("}"):
            obj_text = obj_text + "}"
        try:
            obj = json.loads(obj_text)
            if isinstance(obj, dict) and obj.get("itemSeq"):
                items.append(obj)
        except json.JSONDecodeError:
            seq = re.search(r'"itemSeq"\s*:\s*"([^"]+)"', obj_text)
            name = re.search(r'"itemName"\s*:\s*"([^"]*)"', obj_text)
            if seq:
                items.append({
                    "itemSeq": seq.group(1),
                    "itemName": name.group(1) if name else "",
                    "efcyQesitm": _field(obj_text, "efcyQesitm"),
                    "useMethodQesitm": _field(obj_text, "useMethodQesitm"),
                    "atpnWarnQesitm": _field(obj_text, "atpnWarnQesitm"),
                    "atpnQesitm": _field(obj_text, "atpnQesitm"),
                    "intrcQesitm": _field(obj_text, "intrcQesitm"),
                    "seQesitm": _field(obj_text, "seQesitm"),
                    "entpName": _field(obj_text, "entpName"),
                })

    return items


def _field(text: str, key: str) -> str:
    match = re.search(rf'"{key}"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    return match.group(1) if match else ""


def extract_json_from_part(path: Path) -> Any:
    """part.1 또는 일반 .json 파일에서 JSON 객체/배열을 추출합니다."""
    path = Path(path)
    raw = path.read_bytes()

    if raw[:1] in (b"[", b"{"):
        return json.loads(raw.decode("utf-8"))

    last_error: Exception | None = None
    for idx in _candidate_offsets(raw):
        try:
            return _loads_from_offset(raw, idx)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            continue

    text = raw.decode("utf-8", errors="replace")
    for pattern in (r'(\{"metadata"[\s\S]*\})', r"(\[[\s\S]*\])", r"(\{[\s\S]*\})"):
        match = re.search(pattern, text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError as exc:
                last_error = exc
                continue

    detail = f" ({last_error})" if last_error else ""
    raise ValueError(f"JSON을 추출할 수 없습니다: {path}{detail}")


def extract_items_from_part(path: Path) -> list[dict]:
    """Bronze drug_info / taboo 저장 포맷에서 item 리스트를 반환합니다."""
    raw = Path(path).read_bytes()

    if b'"items":' in raw or b'"items" :' in raw:
        bronze_items = _extract_bronze_drug_items(raw)
        if bronze_items:
            return bronze_items

    try:
        data = extract_json_from_part(path)
    except ValueError:
        bronze_items = _extract_bronze_drug_items(raw)
        if bronze_items:
            return bronze_items
        raise

    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return [row for row in data["items"] if isinstance(row, dict)]
        body = data.get("body") or {}
        if isinstance(body.get("items"), list):
            return [row for row in body["items"] if isinstance(row, dict)]
        response = data.get("response") or {}
        body2 = response.get("body") or {}
        items = body2.get("items")
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)]
        if isinstance(items, dict) and isinstance(items.get("item"), list):
            return [row for row in items["item"] if isinstance(row, dict)]
    return []


def find_latest_part(root: Path, *, filename: str = "part.1") -> Path | None:
    """하위 폴더 중 수정 시각이 가장 최근인 part.1 경로를 찾습니다."""
    root = Path(root)
    if not root.exists():
        return None
    candidates = sorted(
        root.rglob(filename),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None
