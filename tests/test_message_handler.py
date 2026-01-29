"""Tests for the message handler pipeline."""

import unittest
from unittest.mock import patch, MagicMock


class TestMessageHandler(unittest.TestCase):

    @patch('app.services.message_handler.sender')
    @patch('app.services.message_handler.supervisor')
    @patch('app.services.message_handler.conv_db')
    @patch('app.services.message_handler.leads_db')
    @patch('app.services.message_handler.lead_service')
    @patch('app.services.message_handler.consumption_db')
    @patch('app.services.message_handler.tenants_db')
    def test_happy_path(self, mock_tenants, mock_consumption, mock_lead_svc,
                        mock_leads, mock_conv, mock_supervisor, mock_sender):
        """Full happy path: message in -> AI response -> message out."""
        mock_tenants.get_whatsapp_account_by_instance.return_value = {
            'id': 'acc-1',
            'tenant_id': 'ten-1',
            'instance_name': 'test-inst',
            'config': '{}',
            'tenant_anthropic_key': None,
        }
        mock_tenants.get_active_agent_config.return_value = {
            'system_prompt': 'You are Oliver.',
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 150,
            'max_history_messages': 10,
            'persona': {},
            'tools_enabled': '["web_search"]',
        }
        mock_conv.get_or_create_conversation.return_value = {
            'id': 'conv-1', 'tenant_id': 'ten-1',
            'contact_phone': '5511999', 'contact_name': None,
            'stage': 'new',
        }
        mock_conv.get_message_history.return_value = [
            {'role': 'user', 'content': 'oi'},
        ]
        mock_leads.get_lead.return_value = None

        mock_supervisor.process.return_value = {
            'text': 'Oi! Sou Oliver.',
            'input_tokens': 100, 'output_tokens': 20,
            'model': 'claude-sonnet-4-20250514', 'cost': 0.0006,
            'tool_calls': [],
        }
        mock_sender.send_split_messages.return_value = True

        from app.services.message_handler import handle_webhook
        handle_webhook({
            'event': 'messages.upsert',
            'instance': 'test-inst',
            'data': {
                'key': {'remoteJid': '5511999@s.whatsapp.net', 'fromMe': False},
                'message': {'conversation': 'oi'},
                'pushName': 'Luan',
            },
        })

        # Verify AI was called
        mock_supervisor.process.assert_called_once()
        # Verify message was sent
        mock_sender.send_split_messages.assert_called_once()
        # Verify consumption was logged
        mock_consumption.log_usage.assert_called_once()

    @patch('app.services.message_handler.tenants_db')
    def test_unknown_instance(self, mock_tenants):
        """Messages from unknown instances are ignored."""
        mock_tenants.get_whatsapp_account_by_instance.return_value = None

        from app.services.message_handler import handle_webhook
        handle_webhook({
            'event': 'messages.upsert',
            'instance': 'unknown-inst',
            'data': {
                'key': {'remoteJid': '5511999@s.whatsapp.net', 'fromMe': False},
                'message': {'conversation': 'oi'},
                'pushName': 'Test',
            },
        })
        # No error raised — just silently ignored


class TestExtractContent(unittest.TestCase):

    def test_text_message(self):
        from app.services.message_handler import _extract_content
        text, source = _extract_content({
            'message': {'conversation': 'Ola!'},
        }, 'inst')
        self.assertEqual(text, 'Ola!')
        self.assertEqual(source, 'text')

    def test_extended_text(self):
        from app.services.message_handler import _extract_content
        text, source = _extract_content({
            'message': {'extendedTextMessage': {'text': 'Mensagem longa'}},
        }, 'inst')
        self.assertEqual(text, 'Mensagem longa')
        self.assertEqual(source, 'text')

    def test_unsupported_type(self):
        from app.services.message_handler import _extract_content
        text, source = _extract_content({
            'message': {'imageMessage': {}},
        }, 'inst')
        self.assertIsNone(text)
        self.assertEqual(source, 'unsupported')

    @patch('app.services.message_handler.transcriber')
    def test_audio_message(self, mock_transcriber):
        mock_transcriber.transcribe_audio.return_value = 'Texto transcrito'
        from app.services.message_handler import _extract_content
        text, source = _extract_content({
            'message': {'audioMessage': {'seconds': 5}},
        }, 'inst')
        self.assertEqual(text, 'Texto transcrito')
        self.assertEqual(source, 'audio')


if __name__ == '__main__':
    unittest.main()
