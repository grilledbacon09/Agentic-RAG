import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.diagnosis import router


class ChatDeletionTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def test_deletes_only_current_users_session_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            own = root / 'user-a_chat-1.json'
            other = root / 'user-b_chat-1.json'
            own.write_text('{}')
            other.write_text('{}')
            cache = {'user-a_chat-1': object(), 'user-b_chat-1': object()}
            with patch('agents.persistence.SESSION_DIR', root), patch('api.diagnosis.SESSION_DB', cache):
                self.client.cookies.set('user_id', 'user-a')
                for _ in range(2):
                    self.assertEqual(self.client.delete('/api/diagnosis/chat-1').status_code, 204)
                self.assertFalse(own.exists())
                self.assertTrue(other.exists())
                self.assertNotIn('user-a_chat-1', cache)
                self.assertIn('user-b_chat-1', cache)

    def test_missing_cookie_and_invalid_identifiers(self):
        with patch('api.diagnosis.delete_session_file') as delete:
            self.assertEqual(self.client.delete('/api/diagnosis/chat-1').status_code, 204)
            delete.assert_not_called()
            self.client.cookies.set('user_id', '../outside')
            self.assertEqual(self.client.delete('/api/diagnosis/chat-1').status_code, 400)
            delete.assert_not_called()

    def test_failed_disk_deletion_retains_cache(self):
        self.client.cookies.set('user_id', 'user-a')
        cache = {'user-a_chat-1': object()}
        with patch('api.diagnosis.SESSION_DB', cache), patch('api.diagnosis.delete_session_file', side_effect=OSError):
            self.assertEqual(self.client.delete('/api/diagnosis/chat-1').status_code, 500)
            self.assertIn('user-a_chat-1', cache)
