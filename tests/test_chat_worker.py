import multiprocessing
from fastapi import HTTPException
import pytest
from agents.models import ConversationSession
from agents.persistence import session_to_dict
from services.chat_worker import run_turn


def test_real_spawned_worker_and_hard_deadline(monkeypatch):
    for key in ['USE_LLM', 'USE_DE_GRAPH', 'USE_DE_VECTOR', 'USE_CHROMA', 'SHOW_REASONING']:
        monkeypatch.setenv(key, 'false')
    before = {p.pid for p in multiprocessing.active_children()}
    state = session_to_dict(ConversationSession())
    result = run_turn(state, '안녕하세요', timeout=30)
    assert result['content'] and result['state']['turns']
    assert {p.pid for p in multiprocessing.active_children()} == before
    with pytest.raises(HTTPException) as error:
        run_turn(state, '안녕하세요', timeout=0)
    assert error.value.status_code == 504
    assert {p.pid for p in multiprocessing.active_children()} == before
