"""A killable per-turn worker: the entire engine gets 90 seconds, no DB handles."""
import multiprocessing
import threading
import time
from fastapi import HTTPException

_capacity = threading.BoundedSemaphore(2)


def _run(pipe, state, content):
    try:
        from dataclasses import replace
        from agents.config import load_config
        from agents.chat_service import create_chat, send_message
        from agents.persistence import dict_to_session, session_to_dict
        from agents.state_codec import encode, decode
        bundle, _ = create_chat(replace(load_config(), show_reasoning=False, enable_agent_trace=False))
        bundle.session = dict_to_session(state)
        bundle.agent._last_pipeline_result = decode(state.get('_pipeline_result'))
        updated, reply, debug, sources, trace = send_message(bundle, content)
        updated.session.has_recommendation = updated.agent._last_pipeline_result is not None
        saved_state = session_to_dict(updated.session)
        saved_state['_pipeline_result'] = encode(updated.agent._last_pipeline_result)
        pipe.send({'state': saved_state, 'content': reply,
                   'metadata': {k: v for k, v in {'debug_trace': debug, 'data_sources': sources, 'reasoning_trace': trace}.items() if v is not None}})
    except Exception:
        pipe.send({'error': 'engine_failed'})
    finally:
        pipe.close()


def run_turn(state, content, timeout=90):
    if not _capacity.acquire(blocking=False):
        raise HTTPException(503, {'code': 'failed', 'message': '상담 서버가 사용 중입니다. 잠시 후 다시 실행해주세요.'})
    ctx = multiprocessing.get_context('spawn')
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_run, args=(send, state, content), daemon=True)
    started = False
    try:
        deadline = time.monotonic() + timeout
        process.start()
        started = True
        send.close()
        if not receive.poll(max(0, deadline-time.monotonic())):
            raise HTTPException(504, {'code': 'failed', 'message': '90초 안에 상담을 완료하지 못했습니다. 다시 실행해주세요.'})
        result = receive.recv()
        if result.get('error'):
            raise HTTPException(502, {'code': 'failed', 'message': '상담 응답 생성에 실패했습니다.'})
        return result
    except EOFError:
        raise HTTPException(502, {'code': 'failed', 'message': '상담 처리 연결이 종료되었습니다.'}) from None
    finally:
        if started:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join()
            process.close()
        receive.close()
        send.close()
        _capacity.release()
