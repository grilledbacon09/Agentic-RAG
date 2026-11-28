"""Member database only. No migrations or memory fallback at application startup."""
import logging
import os
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool
from fastapi import HTTPException

_pool = None
_slots = None
_lock = threading.Lock()


def get_pool():
    global _pool, _slots
    with _lock:
        if _pool is None:
            required = ('HOST', 'NAME', 'USER', 'PASSWORD')
            if any(not os.getenv('APP_DB_' + key) for key in required):
                raise HTTPException(503, '회원 DB 연결 설정이 필요합니다.')
            maximum = int(os.getenv('APP_DB_POOL_MAX', '4'))
            if not 1 <= maximum <= 4:
                raise HTTPException(503, '회원 DB 연결 상한은 1~4입니다.')
            _pool = ThreadedConnectionPool(
                1, maximum, host=os.environ['APP_DB_HOST'],
                port=int(os.getenv('APP_DB_PORT', '5433')),
                dbname=os.environ['APP_DB_NAME'], user=os.environ['APP_DB_USER'],
                password=os.environ['APP_DB_PASSWORD'],
                sslmode=os.getenv('APP_DB_SSLMODE', 'require'), connect_timeout=8,
                application_name='member_api',
                options='-c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=30000',
            )
            _slots = threading.BoundedSemaphore(maximum)
    return _pool, _slots


@contextmanager
def transaction():
    connection = None
    acquired = False
    slots = None
    pool = None
    try:
        pool, slots = get_pool()
        acquired = slots.acquire(timeout=5)
        if not acquired:
            raise HTTPException(503, '회원 DB가 사용 중입니다. 잠시 후 다시 시도해주세요.')
        connection = pool.getconn()
        with connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
    except psycopg2.IntegrityError:
        raise HTTPException(409, '중복 데이터 또는 변경 충돌입니다.') from None
    except psycopg2.Error as exc:
        stage = 'connect' if connection is None else 'transaction'
        reason = type(exc).__name__
        if stage == 'connect':
            message = str(exc).lower()
            for marker in ('timeout', 'timed out', 'connection refused', 'password authentication failed',
                           'no pg_hba.conf entry', 'does not exist', 'could not translate host name',
                           'too many clients', 'ssl'):
                if marker in message:
                    reason = marker
                    break
        logging.getLogger(__name__).error('Member DB failure: stage=%s reason=%s sqlstate=%s',
                                         stage, reason, exc.pgcode or 'unavailable')
        raise HTTPException(503, '회원 DB를 사용할 수 없습니다. 저장되지 않았습니다.') from None
    finally:
        if connection is not None:
            pool.putconn(connection, close=bool(connection.closed))
        if acquired:
            slots.release()


def close_pool():
    global _pool, _slots
    with _lock:
        if _pool is not None:
            _pool.closeall()
            _pool = _slots = None
