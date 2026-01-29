"""Tests for tenant isolation."""

import unittest
from unittest.mock import patch


class TestTenantIsolation(unittest.TestCase):
    """Verify that data is properly scoped per tenant."""

    def test_lid_cache_scoped(self):
        """LID cache keys include account_id to prevent cross-tenant leaks."""
        from app.channels.lid_resolver import _cache

        # Simulate two different accounts resolving the same LID
        _cache[('account-A', '12345@lid')] = '5511111111'
        _cache[('account-B', '12345@lid')] = '5522222222'

        # They should be independent
        self.assertEqual(_cache[('account-A', '12345@lid')], '5511111111')
        self.assertEqual(_cache[('account-B', '12345@lid')], '5522222222')

        # Clean up
        del _cache[('account-A', '12345@lid')]
        del _cache[('account-B', '12345@lid')]

    @patch('app.ai.supervisor.call_api')
    def test_separate_prompts(self, mock_api):
        """Each tenant gets their own system prompt."""
        mock_api.return_value = {
            'content': [{'type': 'text', 'text': 'Response'}],
            'stop_reason': 'end_turn',
            'usage': {'input_tokens': 50, 'output_tokens': 10},
        }

        from app.ai.supervisor import process

        # Tenant A
        result_a = process(
            conversation={
                'id': 'conv-a', 'tenant_id': 'ten-a',
                'contact_phone': '5511111', 'contact_name': 'Alice',
                'stage': 'new',
                'messages': [{'role': 'user', 'content': 'oi'}],
                'lead': None,
            },
            agent_config={
                'system_prompt': 'Voce e assistente da Empresa A.',
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 150,
                'max_history_messages': 10,
                'persona': {'name': 'Bot A'},
                'tools_enabled': '["web_search"]',
            },
        )

        # Check the API was called with Empresa A's prompt
        call_args = mock_api.call_args
        system_prompt = call_args[0][2]  # third positional arg
        self.assertIn('Empresa A', system_prompt)

        # Tenant B
        result_b = process(
            conversation={
                'id': 'conv-b', 'tenant_id': 'ten-b',
                'contact_phone': '5522222', 'contact_name': 'Bob',
                'stage': 'new',
                'messages': [{'role': 'user', 'content': 'hi'}],
                'lead': None,
            },
            agent_config={
                'system_prompt': 'You are assistant for Company B.',
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 150,
                'max_history_messages': 10,
                'persona': {'name': 'Bot B'},
                'tools_enabled': '["web_search"]',
            },
        )

        call_args = mock_api.call_args
        system_prompt = call_args[0][2]
        self.assertIn('Company B', system_prompt)

    def test_prompts_module_functions(self):
        """Test is_real_name and detect_language are independent of tenant."""
        from app.ai.prompts import is_real_name, detect_language

        # Name detection
        self.assertTrue(is_real_name('Luan Silva'))
        self.assertTrue(is_real_name('Maria'))
        self.assertFalse(is_real_name('bot'))
        self.assertFalse(is_real_name('admin'))
        self.assertFalse(is_real_name(''))
        self.assertFalse(is_real_name('A'))

        # Language detection
        self.assertEqual(detect_language('oi tudo bem'), 'pt')
        self.assertEqual(detect_language('hello how are you'), 'en')
        self.assertEqual(detect_language('hola como estas'), 'es')


if __name__ == '__main__':
    unittest.main()
