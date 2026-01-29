"""Tests for the AI supervisor agentic loop."""

import unittest
from unittest.mock import patch, MagicMock


class TestSupervisor(unittest.TestCase):
    """Test the supervisor process function."""

    def _make_conversation(self, messages=None):
        return {
            'id': 'conv-123',
            'tenant_id': 'tenant-456',
            'contact_phone': '5511999999999',
            'contact_name': 'Luan',
            'stage': 'new',
            'messages': messages or [
                {'role': 'user', 'content': 'oi'},
            ],
            'lead': None,
        }

    def _make_agent_config(self):
        return {
            'system_prompt': 'Voce e Oliver, assistente da QuantrexNow.',
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 150,
            'max_history_messages': 10,
            'persona': {'name': 'Oliver'},
            'tools_enabled': '["web_search"]',
        }

    @patch('app.ai.supervisor.call_api')
    def test_simple_response(self, mock_api):
        """Claude responds without tool use."""
        mock_api.return_value = {
            'content': [{'type': 'text', 'text': 'Oi! Sou Oliver.'}],
            'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 20},
        }

        from app.ai.supervisor import process
        result = process(
            self._make_conversation(),
            self._make_agent_config(),
            language='pt',
        )

        self.assertEqual(result['text'], 'Oi! Sou Oliver.')
        self.assertEqual(result['input_tokens'], 100)
        self.assertEqual(result['output_tokens'], 20)
        self.assertEqual(result['model'], 'claude-sonnet-4-20250514')
        self.assertEqual(len(result['tool_calls']), 0)

    @patch('app.ai.supervisor.execute_tool')
    @patch('app.ai.supervisor.call_api')
    def test_tool_use_then_response(self, mock_api, mock_tool):
        """Claude uses a tool, then responds."""
        # First call: tool_use
        mock_api.side_effect = [
            {
                'content': [
                    {'type': 'text', 'text': ''},
                    {'type': 'tool_use', 'id': 'tool-1', 'name': 'web_search',
                     'input': {'query': 'quantrexnow precos'}},
                ],
                'stop_reason': 'tool_use',
                'usage': {'input_tokens': 100, 'output_tokens': 30},
            },
            # Second call: final response
            {
                'content': [{'type': 'text', 'text': 'Encontrei os precos!'}],
                'stop_reason': 'end_turn',
                'usage': {'input_tokens': 200, 'output_tokens': 15},
            },
        ]
        mock_tool.return_value = '- Plano Basic: R$99/mes'

        from app.ai.supervisor import process
        result = process(
            self._make_conversation(),
            self._make_agent_config(),
        )

        self.assertEqual(result['text'], 'Encontrei os precos!')
        self.assertEqual(result['input_tokens'], 300)
        self.assertEqual(result['output_tokens'], 45)
        self.assertEqual(len(result['tool_calls']), 1)
        self.assertEqual(result['tool_calls'][0]['name'], 'web_search')

    @patch('app.ai.supervisor.call_api')
    def test_max_iterations(self, mock_api):
        """Supervisor stops after max tool iterations."""
        # Always return tool_use
        mock_api.return_value = {
            'content': [
                {'type': 'tool_use', 'id': 'tool-x', 'name': 'web_search',
                 'input': {'query': 'test'}},
            ],
            'stop_reason': 'tool_use',
            'usage': {'input_tokens': 50, 'output_tokens': 10},
        }

        from app.ai.supervisor import process
        result = process(
            self._make_conversation(),
            self._make_agent_config(),
        )

        # Should get fallback because no text was ever returned
        self.assertIn(result['text'], ['perai, to verificando aqui',
                                        'um seg, ja volto', 'opa, da um momento'])

    @patch('app.ai.supervisor.call_api')
    def test_fallback_on_error(self, mock_api):
        """Supervisor returns fallback on API error."""
        mock_api.return_value = None

        from app.ai.supervisor import process
        result = process(
            self._make_conversation(),
            self._make_agent_config(),
            language='en',
        )

        self.assertIn(result['text'], [
            'one sec, checking here', 'hold on, be right back', 'just a moment',
        ])


if __name__ == '__main__':
    unittest.main()
