#!/usr/bin/env bash
# ============================================================
# migrate.sh — migrations/V###__*.sql 을 순서대로 한 번씩 적용
# ============================================================
# 사용:
#   export APP_DB_HOST=… APP_DB_PORT=5433 APP_DB_NAME=drug_app APP_DB_SSLMODE=require
#   export APP_DB_MIGRATOR_USER=app_migrator APP_DB_MIGRATOR_PASSWORD=…   (실행할 때만, 파일에 저장 금지)
#   export APP_DB_RUNTIME_USER=app_runtime   # GRANT 대상 (테스트 DB면 app_test_runtime)
#   ./migrate.sh            # 적용
#   ./migrate.sh --status   # 적용 기록만 보기
#
# - 각 파일은 하나의 트랜잭션으로 적용 (실패하면 그 파일 전체 롤백)
# - app.schema_migrations 에 버전·체크섬 기록 → 이미 적용한 파일이 바뀌면 중단
# - 운영 rollback은 새 V### 파일로 앞으로 고치는 방식 (DROP/down migration 없음)
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

: "${APP_DB_HOST:?APP_DB_HOST 필요}"
: "${APP_DB_MIGRATOR_USER:=app_migrator}"
: "${APP_DB_RUNTIME_USER:=app_runtime}"
: "${APP_DB_MIGRATOR_PASSWORD:?APP_DB_MIGRATOR_PASSWORD 필요 (실행할 때만 export)}"
export PGHOST="$APP_DB_HOST" PGPORT="${APP_DB_PORT:-5433}" PGDATABASE="${APP_DB_NAME:-drug_app}"
export PGUSER="$APP_DB_MIGRATOR_USER" PGPASSWORD="$APP_DB_MIGRATOR_PASSWORD"
export PGSSLMODE="${APP_DB_SSLMODE:-require}" PGAPPNAME="drug_app_migrate" PGOPTIONS="-c client_min_messages=warning"

PSQL=(psql -X -q -v ON_ERROR_STOP=1 -At)

"${PSQL[@]}" -c "CREATE TABLE IF NOT EXISTS app.schema_migrations (
    version    text        PRIMARY KEY,
    checksum   char(64)    NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text        NOT NULL DEFAULT current_user)"

if [[ "${1:-}" == "--status" ]]; then
    "${PSQL[@]}" -F $'\t' -c "SELECT version, applied_at, applied_by FROM app.schema_migrations ORDER BY version"
    exit 0
fi

shopt -s nullglob
for f in migrations/V[0-9][0-9][0-9]__*.sql; do
    ver="$(basename "$f" .sql)"
    sum="$(sha256sum "$f" | cut -d' ' -f1)"
    applied="$("${PSQL[@]}" -c "SELECT checksum FROM app.schema_migrations WHERE version = '$ver'")"
    if [[ -n "$applied" ]]; then
        if [[ "$applied" != "$sum" ]]; then
            echo "❌ $ver 는 이미 적용됐는데 파일 내용이 바뀌었습니다 (적용된 파일은 고치지 말고 새 V### 파일로)" >&2
            exit 1
        fi
        echo "  - $ver (이미 적용)"
        continue
    fi
    echo "▶ $ver 적용"
    "${PSQL[@]}" -1 -v runtime_role="$APP_DB_RUNTIME_USER" -f "$f" \
        -c "INSERT INTO app.schema_migrations (version, checksum) VALUES ('$ver', '$sum')"
    echo "  ✅ $ver"
done
echo "완료"
