-- ============================================================
-- cleanup.sql — 보관 기간이 지난 기록 삭제 (하루 1회, cron)
-- ============================================================
-- 실행: psql -p 5433 -d drug_app -v ON_ERROR_STOP=1 -f cleanup.sql
-- 보관 정책 (WEB 회신 B13 확정):
--   로그인 세션 : 실제로 끝난 시각 + 7일 후 삭제
--                 끝난 시각 = 미사용 만료(last_seen_at + 30분)·절대 만료(expires_at)·폐기(revoked_at) 중 가장 이른 값
--                 아직 유효한 세션은 대상 아님
--   상담 요청   : completed/failed 된 시각(finished_at) + 30일 후 삭제
--                 메시지가 참조하는 요청은 상담이 삭제될 때까지 보존 (기간과 무관)
--                 processing 요청은 대상 아님 (reclaim_leases.sql이 failed로 바꾼 뒤부터 30일)
--   상담 삭제·회원 탈퇴는 기간과 무관하게 API에서 CASCADE 삭제
-- 동시 실행: 지울 행을 FOR UPDATE SKIP LOCKED로 잡습니다.
--   API가 처리 중인 행은 건너뛰고(다음 날 다시 확인), 잡은 행은 삭제 시점에 조건을 한 번 더 확인합니다.
-- ============================================================
\set idle_timeout '30 minutes'
\set session_keep '7 days'
\set request_keep '30 days'

BEGIN;

WITH target AS (
    SELECT id FROM app.auth_sessions
    WHERE LEAST(last_seen_at + :'idle_timeout'::interval, expires_at, COALESCE(revoked_at, 'infinity'))
          < now() - :'session_keep'::interval
    FOR UPDATE SKIP LOCKED
), d AS (
    DELETE FROM app.auth_sessions s USING target t
    WHERE s.id = t.id
      AND LEAST(s.last_seen_at + :'idle_timeout'::interval, s.expires_at, COALESCE(s.revoked_at, 'infinity'))
          < now() - :'session_keep'::interval
    RETURNING 1)
SELECT 'auth_sessions 삭제' AS job, count(*) FROM d;

WITH target AS (
    SELECT r.id FROM app.chat_requests r
    WHERE r.status IN ('completed', 'failed')
      AND r.finished_at < now() - :'request_keep'::interval
      AND NOT EXISTS (SELECT 1 FROM app.chat_messages m WHERE m.request_id = r.id AND m.chat_id = r.chat_id)
    FOR UPDATE OF r SKIP LOCKED
), d AS (
    DELETE FROM app.chat_requests r USING target t
    WHERE r.id = t.id
      AND r.status IN ('completed', 'failed')
      AND r.finished_at < now() - :'request_keep'::interval
      AND NOT EXISTS (SELECT 1 FROM app.chat_messages m WHERE m.request_id = r.id AND m.chat_id = r.chat_id)
    RETURNING 1)
SELECT 'chat_requests 삭제' AS job, count(*) FROM d;

COMMIT;
