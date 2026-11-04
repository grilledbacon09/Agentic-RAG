import unittest
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.interaction_graph import router
from agents.integrations.graph_client import LiveGraphClient, MockGraphClient
from agents.interaction_graph import build_interaction_graph


class GraphAvailabilityTests(unittest.TestCase):
    def test_query_failure_is_unavailable_not_missing_product(self):
        graph = LiveGraphClient()
        graph._graph = Mock()
        graph._graph.check_status.side_effect = ConnectionError('private connection info')
        result = build_interaction_graph(drug_ids=['200402374'], drug_names=[], catalog=[], graph=graph)
        self.assertFalse(result['ok'])
        self.assertEqual(result['backend'], 'unavailable')
        self.assertEqual(result['mapping'][0]['graph_status'], 'UNAVAILABLE')
        self.assertEqual(result['nodes'][0]['item_seq'], '200402374')
        self.assertTrue(result['errors'])
        self.assertNotIn('private connection info', str(result))

    def test_missing_product_retains_id_and_not_found(self):
        graph = MockGraphClient(status_map={'200402374': 'NOT_FOUND'})
        result = build_interaction_graph(drug_ids=['200402374'], drug_names=[], catalog=[], graph=graph)
        self.assertEqual(result['nodes'][0]['item_seq'], '200402374')
        self.assertEqual(result['nodes'][0]['graph_status'], 'NOT_FOUND')

    def test_lazy_connection_failure_returns_503(self):
        graph = LiveGraphClient()
        def fail():
            graph._connect_error = 'ModuleNotFoundError'
            return False
        app = FastAPI()
        app.include_router(router)
        with patch.object(graph, '_ensure', side_effect=fail), patch('api.interaction_graph.create_graph_client', return_value=graph):
            response = TestClient(app).post('/api/drug-interaction-graph', json={'drug_ids':['200402374']})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail']['mapping'][0]['mapping_status'], 'UNAVAILABLE')
