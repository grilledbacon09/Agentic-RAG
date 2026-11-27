import json
import unittest
from unittest.mock import patch
from fastapi import HTTPException
from api.user import ProfileUpdate
from agents.models import ConversationSession, ConversationPhase, UserInput, ConversationTurn
from agents.persistence import dict_to_session, session_to_dict
from repositories.chats import validate_output
from services.auth import csrf_for, digest, hasher, verify_password
from services.users import validate_medications
from api.user import Medication


class MemberUnitTests(unittest.TestCase):
    def test_pipeline_state_codec_preserves_types_and_rejects_unknown(self):
        from agents.state_codec import encode, decode
        from agents.models import PipelineResult
        from agents.recommendation_agent import RecommendationDecision
        from agents.validator import ValidationResult
        from agents.integrations.types import DataProvenance, DataBackend
        result = PipelineResult(UserInput(symptoms=['두통']), [], RecommendationDecision(), ValidationResult(True),
            data_provenance=DataProvenance(retrieval=DataBackend.POSTGRESQL))
        restored = decode(json.loads(json.dumps(encode(result))))
        self.assertEqual(restored, result)
        self.assertIs(restored.data_provenance.retrieval, DataBackend.POSTGRESQL)
        with self.assertRaises(ValueError):
            decode({'kind': 'record', 'type': 'arbitrary_code', 'fields': {}})

    def test_all_session_fields_roundtrip(self):
        session = ConversationSession(user_input=UserInput(symptoms=['두통'], age=35),
            phase=ConversationPhase.FOLLOW_UP, turns=[ConversationTurn('user', '질문')],
            confirmed_slots={'allergies', 'current_meds'}, pending_slot='conditions',
            turn_count=3, last_pipeline_summary='summary', has_recommendation=True)
        self.assertEqual(session, dict_to_session(json.loads(json.dumps(session_to_dict(session)))))

    def test_status_lists_and_age_contract(self):
        base = dict(allergy_status='none', medication_status='none', version=1)
        for patch_values in [dict(age=121), dict(age=20.5), dict(allergies=['약']), dict(medication_status='known'), dict(age=True)]:
            with self.assertRaises(ValueError):
                ProfileUpdate(**(base | patch_values))
        self.assertEqual(ProfileUpdate(**(base | dict(age=0))).age, 0)

    def test_unicode_and_metadata_whole_json_limits(self):
        validate_output('😀'*8000, {})
        with self.assertRaises(HTTPException):
            validate_output('😀'*8001, {})
        validate_output('ok', {'x': '가'*7992})  # 8 characters of JSON structure.
        with self.assertRaises(HTTPException):
            validate_output('ok', {'x': '가'*7993})

    def test_password_and_csrf(self):
        encoded = hasher.hash('long-test-password')
        self.assertTrue(encoded.startswith('$argon2id$'))
        self.assertTrue(verify_password(encoded, 'long-test-password'))
        self.assertFalse(verify_password(encoded, 'wrong'))
        self.assertNotEqual(csrf_for('token-a'), csrf_for('token-b'))
        self.assertEqual(len(digest(csrf_for('token-a'))), 64)

    def test_medication_id_exact_match_and_snapshot(self):
        with patch('services.users.search_medications', return_value=[{'drug_id': '123456789', 'name': '서버 제품명'}]):
            rows = validate_medications([Medication(drug_id='123456789', name='변조 이름')])
            self.assertEqual(rows[0]['name'], '서버 제품명')
            with self.assertRaises(HTTPException):
                validate_medications([Medication(drug_id='987654321')])
