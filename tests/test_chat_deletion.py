import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.diagnosis import router
from api.user import router as user_router

class ChatDeletionTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        app.include_router(user_router)
        self.client = TestClient(app)

    def test_anonymous_cookie_cannot_delete_legacy_file(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = Path(directory) / 'user-a_chat-1.json'
            legacy.write_text('{}')
            self.client.cookies.set('user_id', 'user-a')
            self.assertEqual(self.client.delete(f'/api/diagnosis/{uuid4()}').status_code, 401)
            self.assertTrue(legacy.exists())

    def test_anonymous_cookie_cannot_send_or_read_settings(self):
        self.client.cookies.set('user_id', '../outside')
        self.assertEqual(self.client.post('/api/diagnosis', json={
            'content': 'test', 'chat_id': str(uuid4()), 'client_request_id': str(uuid4())}).status_code, 401)
        self.assertEqual(self.client.get('/api/user/setting/user_01').status_code, 410)
        self.assertEqual(self.client.post('/api/user/setting', json={'user_id': 'user_01'}).status_code, 410)
