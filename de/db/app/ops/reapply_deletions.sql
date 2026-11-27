-- ============================================================
-- reapply_deletions.sql — 백업 복원 직후 탈퇴 회원 재삭제
-- ============================================================
-- 백업 시점 이후 탈퇴한 회원이 복원으로 되살아나는 것을 막습니다.
-- 순서:
--   1) 복원 전에 운영 DB의 탈퇴 목록을 따로 받아 둠
--        psql ... -c "\copy app.deleted_users TO 'deleted_users.csv' CSV"
--   2) 백업 복원 (ops/backup.sh 의 restore 안내 참고)
--   3) 이 파일 실행 (app_migrator)
--        psql ... -v ON_ERROR_STOP=1 -v csv=deleted_users.csv -f ops/reapply_deletions.sql
-- 신규 회원 데이터는 건드리지 않고, 목록에 있는 id만 지웁니다 (CASCADE로 하위 데이터 함께 삭제).
-- ============================================================
BEGIN;
CREATE TEMP TABLE _gone (user_id uuid PRIMARY KEY, deleted_at timestamptz) ON COMMIT DROP;
\set copycmd '\\copy _gone FROM ' :'csv' ' CSV'
:copycmd

INSERT INTO app.deleted_users (user_id, deleted_at)
SELECT user_id, deleted_at FROM _gone
ON CONFLICT (user_id) DO NOTHING;

WITH d AS (
    DELETE FROM app.users u USING app.deleted_users g
    WHERE u.id = g.user_id
    RETURNING 1)
SELECT '탈퇴 회원 재삭제' AS job, count(*) FROM d;
COMMIT;
