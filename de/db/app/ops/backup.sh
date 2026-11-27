#!/usr/bin/env bash
# ============================================================
# backup.sh — 회원 DB(drug_app) 일일 백업 → S3 (EC2에서 postgres 계정 cron으로 실행)
# ============================================================
# 설치 (EC2, 1회):
#   sudo mkdir -p /opt/drug_app && sudo cp backup.sh cleanup.sql reclaim_leases.sql /opt/drug_app/
#   sudo chown -R postgres: /opt/drug_app && sudo chmod 700 /opt/drug_app/backup.sh
#   sudo crontab -u postgres -e  →  아래 4줄 추가 (서버 시간 UTC 기준. 18:30 = 한국 03:30)
#     30 18 * * * BACKUP_BUCKET=<버킷> /opt/drug_app/backup.sh >> /var/log/postgresql/drug_app_backup.log 2>&1
#     50 18 * * * psql -p 5433 -d drug_app -v ON_ERROR_STOP=1 -f /opt/drug_app/cleanup.sql >> /var/log/postgresql/drug_app_cleanup.log 2>&1
#     */10 * * * * psql -p 5433 -d drug_app -v ON_ERROR_STOP=1 -qAt -f /opt/drug_app/reclaim_leases.sql >> /var/log/postgresql/drug_app_reclaim.log 2>&1
#     */10 * * * * psql -p 5433 -d drug_app_test -v ON_ERROR_STOP=1 -qAt -f /opt/drug_app/reclaim_leases.sql >> /var/log/postgresql/drug_app_test_reclaim.log 2>&1
#   테스트 DB(drug_app_test)는 백업하지 않습니다. cleanup은 필요하면 같은 방식으로 추가
#
# S3 권한: EC2에 IAM 역할(s3:PutObject on <버킷>/backup/drug_app/*)을 붙이는 방식 권장.
#   키 파일을 서버에 두지 않기 위해서입니다. aws CLI 필요 (sudo apt install awscli 또는 snap).
# 보관: 서버에는 최근 3개만, S3는 버킷 수명주기 규칙으로 30일 (콘솔에서 설정).
#
# 복원 (새 DB에 풀어 보고 확인 후 교체):
#   aws s3 cp s3://<버킷>/backup/drug_app/drug_app_<시각>.dump .
#   sudo -u postgres createdb -p 5433 drug_app_restore
#   sudo -u postgres pg_restore -p 5433 -d drug_app_restore --no-owner --role=app_migrator drug_app_<시각>.dump
#   → 확인 후 ops/reapply_deletions.sql 실행
# ============================================================
set -euo pipefail
PORT="${PGPORT:-5433}"
DIR="${BACKUP_DIR:-/var/backups/drug_app}"
: "${BACKUP_BUCKET:?BACKUP_BUCKET 필요}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$DIR/drug_app_$TS.dump"

umask 077
mkdir -p "$DIR"
pg_dump -p "$PORT" -d drug_app -Fc -Z 6 -f "$FILE"
pg_restore -l "$FILE" > /dev/null          # 덤프가 읽히는지 확인
aws s3 cp "$FILE" "s3://$BACKUP_BUCKET/backup/drug_app/$(basename "$FILE")" \
    --sse AES256 --only-show-errors
ls -1t "$DIR"/drug_app_*.dump | tail -n +4 | xargs -r rm -f
echo "$(date -u +%FT%TZ) OK $(basename "$FILE") $(du -h "$FILE" | cut -f1)"
