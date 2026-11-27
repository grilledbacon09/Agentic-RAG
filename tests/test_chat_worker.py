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


def test_recommendation_survives_a_new_worker(monkeypatch):
    import json
    from agents.models import ConversationPhase, UserInput
    for key in ['USE_LLM', 'USE_DE_GRAPH', 'USE_DE_VECTOR', 'USE_CHROMA', 'SHOW_REASONING']:
        monkeypatch.setenv(key, 'false')
    session = ConversationSession(phase=ConversationPhase.COLLECTING,
        user_input=UserInput(symptoms=['두통'], age=35),
        confirmed_slots={'symptoms', 'current_meds', 'allergies', 'conditions'})
    result = run_turn(session_to_dict(session), '약 추천해주세요', timeout=30)
    assert result['state']['_pipeline_result'] is not None
    assert result['state']['has_recommendation']
    from repositories.chats import display_metadata, validate_output
    display = display_metadata(result['metadata'])
    validate_output(result['content'], display)
    assert len(json.dumps(display, ensure_ascii=False, separators=(',', ':'))) <= 8000
    followup = run_turn(result['state'], '왜 이 약인가요?', timeout=30)
    assert followup['state']['_pipeline_result'] is not None
    assert '아직 추천 결과가 없습니다' not in followup['content']
    reset = run_turn(followup['state'], 'reset', timeout=30)
    assert reset['state']['_pipeline_result'] is None
    assert len(reset['state']['turns']) == 1
