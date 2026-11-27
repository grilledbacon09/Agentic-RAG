-- 회원 DB 동작 확인. 기대대로면 'PASS', 아니면 'FAIL'
-- 테스트용 DB에서만 실행 (데이터를 넣고 지움). superuser로 접속 → 실제 검사는 app_runtime 권한으로 수행
--   psql -U postgres -d drug_app_test -v runtime=app_test_runtime -f tests/test_v001.sql   (runtime 생략 시 app_runtime)
-- 운영 DB에서는 실행하지 마세요.
\set QUIET on
\if :{?runtime}
\else
  \set runtime app_runtime
\endif
SET client_min_messages = warning;
CREATE TEMP TABLE r (name text, ok boolean);
-- want: 오류 메시지에 들어 있어야 할 제약 이름·권한 문구 (다른 이유로 실패하면 FAIL)
CREATE OR REPLACE FUNCTION pg_temp.expect_fail(name text, want text, q text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE q; INSERT INTO r VALUES (name || ' — 거부되지 않음', false);
  EXCEPTION WHEN others THEN
    INSERT INTO r VALUES (name || ' — ' || SQLERRM, (SQLSTATE LIKE '23%' OR SQLSTATE = '42501') AND SQLERRM LIKE '%' || want || '%'); END;
END $$;
CREATE OR REPLACE FUNCTION pg_temp.expect_ok(name text, q text) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  BEGIN EXECUTE q; INSERT INTO r VALUES (name, true);
  EXCEPTION WHEN others THEN INSERT INTO r VALUES (name || ' — ' || SQLERRM, false); END;
END $$;
GRANT SELECT, INSERT ON r TO :"runtime";
TRUNCATE app.users, app.deleted_users CASCADE;   -- 테스트 DB 전용: 이전 실행 흔적 제거
\o /dev/null
SET ROLE :"runtime";   -- 여기부터 백엔드 계정 권한

-- 고정 id
\set u1 '''00000000-0000-0000-0000-000000000001'''
\set c1 '''00000000-0000-0000-0000-0000000000c1'''
\set h  '''aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'''

-- 권한
SELECT pg_temp.expect_fail('runtime DDL 불가', 'permission denied', 'CREATE TABLE app.x (i int)');
SELECT pg_temp.expect_fail('runtime DROP 불가', 'must be owner', 'DROP TABLE app.users');
SELECT pg_temp.expect_fail('runtime schema_migrations 쓰기 불가', 'permission denied', $q$INSERT INTO app.schema_migrations VALUES ('V999','x')$q$);
SELECT pg_temp.expect_fail('runtime deleted_users 삭제 불가', 'permission denied', 'DELETE FROM app.deleted_users');

-- users
SELECT pg_temp.expect_ok('users 정상', format($q$INSERT INTO app.users (id,email,email_normalized,password_hash) VALUES (%L,' A@b.com ','a@b.com','$argon2id$v=19$x')$q$, :u1));
SELECT pg_temp.expect_fail('email_normalized 대문자 거부', 'users_email_normalized_form', $q$INSERT INTO app.users (email,email_normalized,password_hash) VALUES ('B@b.com','B@b.com','$argon2id$x')$q$);
SELECT pg_temp.expect_fail('email_normalized 중복 거부', 'users_email_normalized_key', $q$INSERT INTO app.users (email,email_normalized,password_hash) VALUES ('A@B.COM','a@b.com','$argon2id$x')$q$);
SELECT pg_temp.expect_fail('email과 다른 email_normalized 거부', 'users_email_normalized_form', $q$INSERT INTO app.users (email,email_normalized,password_hash) VALUES ('z@b.com','y@b.com','$argon2id$x')$q$);
SELECT pg_temp.expect_fail('평문 비밀번호 거부', 'users_password_hash_argon2id', $q$INSERT INTO app.users (email,email_normalized,password_hash) VALUES ('c@b.com','c@b.com','plain')$q$);
SELECT pg_temp.expect_fail('status 값 제한', 'users_status_check', format($q$UPDATE app.users SET status='deleted' WHERE id=%L$q$, :u1));

-- profiles
SELECT pg_temp.expect_ok('profile 기본값', format('INSERT INTO app.user_profiles (user_id) VALUES (%L)', :u1));
SELECT pg_temp.expect_fail('age만 있고 기록시각 없음 거부', 'user_profiles_age_pair', format('UPDATE app.user_profiles SET age=30 WHERE user_id=%L', :u1));
SELECT pg_temp.expect_fail('age 121 거부', 'user_profiles_age_range', format('UPDATE app.user_profiles SET age=121, age_recorded_at=now() WHERE user_id=%L', :u1));
SELECT pg_temp.expect_ok('age+기록시각 정상', format('UPDATE app.user_profiles SET age=30, age_recorded_at=now(), version=version+1 WHERE user_id=%L', :u1));

-- 알레르기·복용약
SELECT pg_temp.expect_ok('알레르기 추가', format($q$INSERT INTO app.user_allergies (user_id,name,name_normalized) VALUES (%L,'페니실린','페니실린')$q$, :u1));
SELECT pg_temp.expect_fail('알레르기 중복 거부', 'user_allergies_user_name_key', format($q$INSERT INTO app.user_allergies (user_id,name,name_normalized) VALUES (%L,'페니실린 ','페니실린')$q$, :u1));
SELECT pg_temp.expect_ok('복용약 item_seq', format($q$INSERT INTO app.user_medications (user_id,drug_id,name) VALUES (%L,'200000001','타이레놀')$q$, :u1));
SELECT pg_temp.expect_ok('전문의약품도 저장 허용', format($q$INSERT INTO app.user_medications (user_id,drug_id,name) VALUES (%L,'201500123','처방약')$q$, :u1));
SELECT pg_temp.expect_fail('같은 drug_id 중복 거부', 'user_medications_user_drug_key', format($q$INSERT INTO app.user_medications (user_id,drug_id,name) VALUES (%L,'200000001','타이레놀정')$q$, :u1));
SELECT pg_temp.expect_fail('drug_id 없음 거부', 'drug_id', format($q$INSERT INTO app.user_medications (user_id,name) VALUES (%L,'타이레놀')$q$, :u1));
SELECT pg_temp.expect_fail('바코드(13자리) 거부', 'user_medications_drug_id_item_seq', format($q$INSERT INTO app.user_medications (user_id,drug_id,name) VALUES (%L,'8806469007251','x')$q$, :u1));
SELECT pg_temp.expect_fail('이름을 drug_id로 거부', 'user_medications_drug_id_item_seq', format($q$INSERT INTO app.user_medications (user_id,drug_id,name) VALUES (%L,'타이레놀','x')$q$, :u1));

-- 세션·동의
SELECT pg_temp.expect_ok('세션 정상', format($q$INSERT INTO app.auth_sessions (user_id,token_hash,csrf_token_hash,expires_at) VALUES (%L,%L,%L,now()+interval '7 days')$q$, :u1, :h, :h));
SELECT pg_temp.expect_fail('토큰 해시 대문자 거부', 'auth_sessions_token_hash_hex', format($q$INSERT INTO app.auth_sessions (user_id,token_hash,csrf_token_hash,expires_at) VALUES (%L,upper(%L),%L,now()+interval '1 day')$q$, :u1, :h, :h));
SELECT pg_temp.expect_fail('만료가 생성보다 앞 거부', 'auth_sessions_expires_after_created', format($q$INSERT INTO app.auth_sessions (user_id,token_hash,csrf_token_hash,expires_at) VALUES (%L,repeat('b',64),%L,now()-interval '1 s')$q$, :u1, :h));
SELECT pg_temp.expect_ok('동의 기록', format($q$INSERT INTO app.user_consents (user_id,consent_type,policy_version,accepted_at) VALUES (%L,'health_data','2026-11',now())$q$, :u1));
SELECT pg_temp.expect_fail('동의 유형 제한', 'user_consents_type_check', format($q$INSERT INTO app.user_consents (user_id,consent_type,policy_version,accepted_at) VALUES (%L,'marketing','2026-11',now())$q$, :u1));

-- 상담
SELECT pg_temp.expect_ok('상담방', format($q$INSERT INTO app.chats (id,user_id,session_state) VALUES (%L,%L,'{}')$q$, :c1, :u1));
SELECT pg_temp.expect_fail('session_state 배열 거부', 'chats_session_state_object', format($q$INSERT INTO app.chats (user_id,session_state) VALUES (%L,'[]')$q$, :u1));
SELECT pg_temp.expect_ok('요청 processing', format($q$INSERT INTO app.chat_requests (chat_id,client_request_id,payload_hash,lease_token,lease_expires_at) VALUES (%L,gen_random_uuid(),%L,gen_random_uuid(),now()+interval '1 min')$q$, :c1, :h));
SELECT pg_temp.expect_fail('같은 방 processing 2개 거부', 'chat_requests_one_processing_per_chat', format($q$INSERT INTO app.chat_requests (chat_id,client_request_id,payload_hash,lease_token,lease_expires_at) VALUES (%L,gen_random_uuid(),%L,gen_random_uuid(),now()+interval '1 min')$q$, :c1, :h));
SELECT pg_temp.expect_fail('processing인데 lease 없음 거부', 'chat_requests_lease_matches_status', format($q$UPDATE app.chat_requests SET lease_token=NULL WHERE chat_id=%L$q$, :c1));
SELECT pg_temp.expect_ok('completed 전환(lease 해제)', format($q$UPDATE app.chat_requests SET status='completed', lease_token=NULL, lease_expires_at=NULL WHERE chat_id=%L$q$, :c1));
SELECT pg_temp.expect_ok('완료 시 finished_at 기록', format($q$DO $d$ BEGIN
  IF (SELECT finished_at FROM app.chat_requests WHERE chat_id=%L) IS NULL THEN RAISE 'no finished_at'; END IF; END $d$$q$, :c1));
SELECT pg_temp.expect_ok('다른 컬럼 수정은 finished_at 유지', format($q$DO $d$ DECLARE f timestamptz; BEGIN
  SELECT finished_at INTO f FROM app.chat_requests WHERE chat_id=%L;
  PERFORM pg_sleep(0.01);
  UPDATE app.chat_requests SET finished_at = now() + interval '1 day', payload_hash = repeat('b',64) WHERE chat_id=%L;
  IF (SELECT finished_at FROM app.chat_requests WHERE chat_id=%L) <> f THEN RAISE 'finished_at changed'; END IF; END $d$$q$, :c1, :c1, :c1));
SELECT pg_temp.expect_ok('processing 재전환 시 finished_at 비움', format($q$DO $d$ BEGIN
  UPDATE app.chat_requests SET status='processing', lease_token=gen_random_uuid(), lease_expires_at=now()+interval '2 min' WHERE chat_id=%L;
  IF (SELECT finished_at FROM app.chat_requests WHERE chat_id=%L) IS NOT NULL THEN RAISE 'not cleared'; END IF;
  UPDATE app.chat_requests SET status='completed', lease_token=NULL, lease_expires_at=NULL WHERE chat_id=%L; END $d$$q$, :c1, :c1, :c1));
SELECT pg_temp.expect_ok('메시지 저장(요청 참조)', format($q$INSERT INTO app.chat_messages (chat_id,request_id,sequence,role,content) SELECT chat_id,id,1,'user','두통' FROM app.chat_requests WHERE chat_id=%L$q$, :c1));
SELECT pg_temp.expect_ok('본문 8,000자 허용', format($q$INSERT INTO app.chat_messages (chat_id,sequence,role,content) VALUES (%L,2,'assistant',repeat('가',8000))$q$, :c1));
SELECT pg_temp.expect_fail('본문 8,001자 거부', 'chat_messages_content_length', format($q$INSERT INTO app.chat_messages (chat_id,sequence,role,content) VALUES (%L,3,'assistant',repeat('가',8001))$q$, :c1));
SELECT pg_temp.expect_fail('sequence 중복 거부', 'chat_messages_chat_sequence_key', format($q$INSERT INTO app.chat_messages (chat_id,sequence,role,content) VALUES (%L,1,'assistant','x')$q$, :c1));
SELECT pg_temp.expect_fail('다른 방 요청 참조 거부(지연 FK, 커밋 시점)', 'chat_messages_request_fk', format($q$
  WITH c2 AS (INSERT INTO app.chats (user_id,session_state) VALUES (%L,'{}') RETURNING id)
  INSERT INTO app.chat_messages (chat_id,request_id,sequence,role,content)
  SELECT c2.id,(SELECT id FROM app.chat_requests WHERE chat_id=%L),1,'user','x' FROM c2;
  SET CONSTRAINTS ALL IMMEDIATE$q$, :u1, :c1));
SELECT pg_temp.expect_fail('메시지가 참조 중인 요청 단독 삭제 거부', 'chat_messages_request_fk', format($q$DELETE FROM app.chat_requests WHERE chat_id=%L; SET CONSTRAINTS ALL IMMEDIATE$q$, :c1));

-- updated_at 트리거
SELECT pg_temp.expect_ok('updated_at 자동 갱신', format($q$DO $d$ BEGIN
  UPDATE app.chats SET updated_at = '2000-01-01' WHERE id=%L;
  IF (SELECT updated_at FROM app.chats WHERE id=%L) < now() - interval '1 min' THEN RAISE 'not touched'; END IF; END $d$$q$, :c1, :c1));

-- 탈퇴: 상담방 통째 CASCADE (지연 FK가 있어도 한 트랜잭션에서 성공)
SELECT pg_temp.expect_ok('탈퇴 CASCADE', format($q$INSERT INTO app.deleted_users (user_id) VALUES (%L); DELETE FROM app.users WHERE id=%L; SET CONSTRAINTS ALL IMMEDIATE$q$, :u1, :u1));
SELECT pg_temp.expect_ok('하위 데이터 0건', $q$DO $d$ BEGIN
  IF (SELECT count(*) FROM app.user_profiles)+(SELECT count(*) FROM app.user_medications)+(SELECT count(*) FROM app.chats)
     +(SELECT count(*) FROM app.chat_messages)+(SELECT count(*) FROM app.chat_requests)+(SELECT count(*) FROM app.auth_sessions) > 0
  THEN RAISE 'left over'; END IF; END $d$$q$);

\o
\set QUIET off
RESET ROLE;
SELECT CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS result, name FROM r;
SELECT count(*) FILTER (WHERE ok) AS pass, count(*) FILTER (WHERE NOT ok) AS fail FROM r;
