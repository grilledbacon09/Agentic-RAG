#!/bin/bash
set -e

DATE=$(date +%Y%m%d_%H%M%S)
OUTPUT="data/dumps/backup_${DATE}.sql.gz"

# 1. 덤프 추출
echo "▶ 덤프 중..."
docker exec my_postgres pg_dump -U postgres mydb | gzip > "$OUTPUT"

# 2. DVC 등록 → .dvc 포인터 파일 생성됨
echo "▶ DVC 등록..."
dvc add "$OUTPUT"

# 3. S3 업로드
echo "▶ S3 업로드..."
dvc push

# 4. 포인터 파일만 Git 커밋
echo "▶ Git 커밋..."
git add "data/dumps/backup_${DATE}.sql.gz.dvc"
git commit -m "DB snapshot: $DATE"
git push

echo " 완료"