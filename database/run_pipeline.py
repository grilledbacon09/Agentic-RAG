"""DE 파이프라인 오케스트레이터.

사용 예:
    # 전체 실행 (MSD 소스 없으면 MSD 단계 자동 스킵)
    python run_pipeline.py

    # MSD 단계 명시적 스킵 (API 데이터만)
    python run_pipeline.py --skip-msd

    # 특정 단계부터 재개 (앞 단계는 이미 완료된 경우)
    python run_pipeline.py --from vectorizer

    # 단일 단계만 실행
    python run_pipeline.py --stage export_to_ai
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ── 부트스트랩: src/ 하위 패키지 경로 + .env 로드 ─────────────────────
_SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(_SRC))
import bootstrap  # noqa: E402

# ── 각 단계 구현 ──────────────────────────────────────────────────────

def _stage_preflight() -> None:
    from pipeline.preflight import main
    code = main()
    if code != 0:
        raise RuntimeError("preflight 실패 — 위 항목을 해결한 뒤 다시 실행하세요.")


def _stage_api_ingest() -> None:
    from collector.api_ingestion import main
    main()


def _stage_api_to_silver() -> None:
    from extractor.api_save_to_silver import main
    main()


def _stage_msd_links() -> None:
    from paths import MSD_SYMPTOMS_HTML
    if not MSD_SYMPTOMS_HTML.exists():
        print(f"[*] MSD HTML 소스 없음 ({MSD_SYMPTOMS_HTML.name}) → 스킵", flush=True)
        return
    from collector.msd_link_collector import main
    main()


def _stage_msd_to_silver() -> None:
    from paths import MSD_LINKS_CSV
    if not MSD_LINKS_CSV.exists():
        print(f"[*] links.csv 없음 → MSD Silver 적재 스킵", flush=True)
        return
    from extractor.msd_save_to_silver import main
    main()


def _stage_vectorizer() -> None:
    from vectordb.vectorizer import main
    main()


def _stage_export_to_ai() -> None:
    from extractor.export_silver_to_ai import main
    main()


# ── 단계 정의 ─────────────────────────────────────────────────────────
#  (name, fn, optional)
#  optional=True: 실패해도 파이프라인 계속 진행
STAGES: list[tuple[str, object, bool]] = [
    ("preflight",      _stage_preflight,      False),
    ("api_ingest",     _stage_api_ingest,     False),
    ("api_to_silver",  _stage_api_to_silver,  False),
    ("msd_links",      _stage_msd_links,      True),
    ("msd_to_silver",  _stage_msd_to_silver,  True),
    ("vectorizer",     _stage_vectorizer,     False),
    ("export_to_ai",   _stage_export_to_ai,   False),
]

STAGE_NAMES = [s[0] for s in STAGES]


# ── 실행기 ────────────────────────────────────────────────────────────

def _print_banner(text: str, width: int = 60) -> None:
    print(f"\n{'─' * width}", flush=True)
    print(f"  {text}", flush=True)
    print(f"{'─' * width}", flush=True)


def run(
    stages: list[tuple[str, object, bool]],
    skip_msd: bool = False,
) -> int:
    """지정된 단계 목록을 순차 실행. 실패 시 0이 아닌 값 반환."""
    results: list[tuple[str, str, float]] = []  # (name, status, elapsed)
    failed = False

    for name, fn, optional in stages:
        if skip_msd and name in ("msd_links", "msd_to_silver"):
            print(f"[SKIP] {name} (--skip-msd)", flush=True)
            results.append((name, "skipped", 0.0))
            continue

        _print_banner(f"STAGE: {name}")
        t0 = time.perf_counter()
        try:
            fn()
            elapsed = time.perf_counter() - t0
            print(f"[OK]   {name}  ({elapsed:.1f}s)", flush=True)
            results.append((name, "ok", elapsed))
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            if optional:
                print(f"[WARN] {name} 실패 (optional 단계, 계속 진행): {exc}", flush=True)
                results.append((name, "warn", elapsed))
            else:
                print(f"[FAIL] {name}: {exc}", flush=True)
                results.append((name, "fail", elapsed))
                failed = True
                break

    # ── 최종 요약 ────────────────────────────────────────────────────
    _print_banner("파이프라인 결과 요약")
    for name, status, elapsed in results:
        icon = {"ok": "✓", "warn": "△", "fail": "✗", "skipped": "–"}.get(status, "?")
        timing = f"  {elapsed:.1f}s" if elapsed > 0 else ""
        print(f"  {icon}  {name:<20}{status:<10}{timing}", flush=True)
    print(flush=True)

    return 1 if failed else 0


# ── CLI ───────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="DE 파이프라인 오케스트레이터",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            "단계 목록:",
            *[f"  {n}" for n in STAGE_NAMES],
        ]),
    )
    p.add_argument(
        "--skip-msd",
        action="store_true",
        help="MSD 크롤링 단계(msd_links, msd_to_silver)를 스킵",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--stage",
        choices=STAGE_NAMES,
        metavar="STAGE",
        help="단일 단계만 실행",
    )
    group.add_argument(
        "--from",
        dest="from_stage",
        choices=STAGE_NAMES,
        metavar="STAGE",
        help="지정 단계부터 끝까지 실행",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    if args.stage:
        # 단일 단계
        target = next(s for s in STAGES if s[0] == args.stage)
        selected = [target]
    elif args.from_stage:
        # 지정 단계부터
        idx = STAGE_NAMES.index(args.from_stage)
        selected = STAGES[idx:]
    else:
        # 전체
        selected = STAGES

    _print_banner(f"DE 파이프라인 시작 ({len(selected)}단계)")
    return run(selected, skip_msd=args.skip_msd)


if __name__ == "__main__":
    sys.exit(main())
