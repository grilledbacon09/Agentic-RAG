-- ============================================================
-- reclaim_leases.sql — 멈춘 처리 중 요청 정리 (10분마다, cron)
-- ============================================================
-- 실행: psql -p 5433 -d drug_app -v ON_ERROR_STOP=1 -q -f reclaim_leases.sql
-- lease 규칙 (WEB 회신 B7, DE 제안값):
--   LLM 타임아웃 90초, 최초 lease 120초(lease_expires_at = 시작 + 120초), 갱신 없음
--   1차 회수: API — 같은 상담방에 새 요청이 오면 만료된 lease를 바로 failed로 바꾸고 진행
--   2차 회수: 이 파일 — lease 만료 후 10분 지난 요청을 failed로 (새 요청이 없는 상담방용 안전장치)
--   "10분"은 정리 유예 시간이며 LLM 실행 시간과는 별개
-- 늦게 끝난 worker 차단: 여기서 lease_token을 NULL로 바꾸므로,
--   API가 결과를 저장할 때 WHERE id = ? AND lease_token = ? 조건으로 0건이 되면 롤백 → 저장되지 않음
-- finished_at은 트리거가 지금 시각으로 기록 → 이 시각부터 30일 보관
-- ============================================================
\set grace '10 minutes'

WITH target AS (
    SELECT id FROM app.chat_requests
    WHERE status = 'processing' AND lease_expires_at < now() - :'grace'::interval
    FOR UPDATE SKIP LOCKED
), u AS (
    UPDATE app.chat_requests r
    SET status = 'failed', lease_token = NULL, lease_expires_at = NULL
    FROM target t
    WHERE r.id = t.id AND r.status = 'processing' AND r.lease_expires_at < now() - :'grace'::interval
    RETURNING 1)
SELECT now() AS at, 'processing → failed' AS job, count(*) FROM u;
