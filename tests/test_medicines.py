"""Web catalog contract tests; no live DB or AI model is used."""
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.medicines import router
from services.medicines import (
    MedicineDatabaseUnavailable, MedicineRepository, database_settings, medicine_repository,
)


def row(**overrides):
    return dict(dict(item_seq='200402374', name='제품 A', manufacturer='제조사',
                     metadata={'main_ingr_raw': '성분 A'}, is_otc=True, is_active=True,
                     data_version='2026-10-22', doc_type='drug_permit', section='summary',
                     text='허가 원문', source_name='식약처', source_url='https://example.org/source',
                     item_url=None, chunk_index=0, doc_id='permit-0'), **overrides)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.repository = MedicineRepository(self.connection)

    def test_search_pagination_and_literal_bound_query(self):
        self.cursor.fetchall.return_value = [row(), row(item_seq='200000913')]
        result = self.repository.search("%'_", 1, 20)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['next_offset'], 21)
        self.assertEqual(result['data_sources'], ['postgresql'])
        sql, params = self.cursor.execute.call_args.args
        self.assertNotIn("%'_", sql)
        self.assertEqual(params[1], "%\\%'\\_%")
        self.assertIn('DISTINCT ON (item_seq)', sql)
        self.assertIn("is_active IS TRUE", sql)
        self.assertEqual(params[-2:], (2, 20))

    def test_empty_search_is_success_not_unavailable(self):
        self.cursor.fetchall.return_value = []
        self.assertEqual(self.repository.search('없는약', 20, 0)['items'], [])
        self.assertIsNone(self.repository.search('', 20, 0)['next_offset'])

    def test_detail_preserves_sources_and_missing_sections(self):
        self.cursor.fetchall.return_value = [
            row(), row(doc_type='drug_usage', section='usage', text='첫 조각'),
            row(doc_type='drug_usage', section='usage', text='다음 조각', chunk_index=1),
            row(doc_type='drug_usage', section='usage', text='별도 원문', source_name='다른 출처'),
        ]
        result = self.repository.detail('200402374')
        usage = [d for d in result['documents'] if d['section'] == 'usage']
        self.assertEqual(len(usage), 2)
        self.assertEqual(usage[0]['text'], '첫 조각\n\n다음 조각')
        self.assertEqual(result['missing_sections'], ['efficacy', 'caution', 'side_effect'])
        self.assertEqual(result['interaction_status'], 'not_assessed')
        self.assertNotIn('updated_date', result)
        self.assertEqual(self.cursor.execute.call_args.args[1][0], '200402374')

    def test_missing_detail_returns_none(self):
        self.cursor.fetchall.return_value = []
        self.assertIsNone(self.repository.detail('000000000'))


class ApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.repository = MagicMock()
        self.repository.search.return_value = {'items': [], 'next_offset': None, 'data_sources': ['postgresql']}
        self.repository.detail.return_value = {'drug_id': '200402374', 'documents': []}

        @contextmanager
        def fake_repository():
            yield self.repository
        self.patcher = patch('api.medicines.medicine_repository', fake_repository)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_search_contract(self):
        response = self.client.get('/api/medicines?search=%20성분%20&offset=20&limit=20')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'], [])
        self.repository.search.assert_called_once_with('성분', 20, 20)

    def test_detail_and_not_found(self):
        self.assertEqual(self.client.get('/api/medicines/200402374').status_code, 200)
        self.repository.detail.return_value = None
        self.assertEqual(self.client.get('/api/medicines/200402374').status_code, 404)

    def test_invalid_inputs(self):
        for url in ['/api/medicines?limit=51', '/api/medicines?offset=-1',
                    '/api/medicines/not-an-id', '/api/medicines?search=' + 'a' * 201]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 422)

    def test_validation_does_not_open_database(self):
        with patch('api.medicines.medicine_repository') as factory:
            self.assertEqual(self.client.get('/api/medicines/not-an-id').status_code, 422)
            self.assertEqual(self.client.get('/api/medicines?limit=0').status_code, 422)
            factory.assert_not_called()

    def test_database_failure_is_503_and_does_not_expose_secrets(self):
        self.repository.search.side_effect = MedicineDatabaseUnavailable('password=PRIVATE')
        response = self.client.get('/api/medicines')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('PRIVATE', response.text)


class ConnectionTests(unittest.TestCase):
    @patch('services.medicines.dotenv_values', return_value={})
    @patch.dict('os.environ', {}, clear=True)
    def test_missing_settings_fail_explicitly(self, _values):
        with self.assertRaises(MedicineDatabaseUnavailable):
            database_settings()

    @patch.dict('os.environ', {'PG_HOST': 'process-host', 'PG_PORT': '5433',
                              'PG_USER': 'reader', 'PG_PASSWORD': 'secret'}, clear=True)
    @patch('services.medicines.dotenv_values', side_effect=[{'PG_HOST': 'root'}, {'PG_HOST': 'config'}])
    def test_environment_precedence_and_readonly(self, _values):
        settings = database_settings()
        self.assertEqual(settings['host'], 'process-host')
        self.assertIn('default_transaction_read_only=on', settings['options'])
        self.assertIn('statement_timeout', settings['options'])

    @patch('services.medicines.database_settings', return_value={})
    @patch('psycopg2.connect')
    def test_connection_closed_on_success_and_http_error(self, connect, _settings):
        from fastapi import HTTPException
        connection = connect.return_value
        with medicine_repository():
            pass
        connection.close.assert_called_once()
        connection.reset_mock()
        with self.assertRaises(HTTPException):
            with medicine_repository():
                raise HTTPException(404)
        connection.close.assert_called_once()

    @patch('services.medicines.database_settings', return_value={})
    @patch('psycopg2.connect')
    def test_query_failure_closes_connection(self, connect, _settings):
        import psycopg2
        with self.assertRaises(MedicineDatabaseUnavailable):
            with medicine_repository():
                raise psycopg2.OperationalError('private DSN')
        connect.return_value.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
