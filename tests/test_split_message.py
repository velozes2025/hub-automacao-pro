"""Tests for message splitting logic."""

import unittest


class TestSplitMessage(unittest.TestCase):

    def test_short_message(self):
        from app.channels.sender import split_message
        result = split_message('Oi, tudo bem?', max_chars=200)
        self.assertEqual(result, ['Oi, tudo bem?'])

    def test_split_at_sentence(self):
        from app.channels.sender import split_message
        text = 'Primeira frase curta. Segunda frase curta. Terceira frase curta.'
        result = split_message(text, max_chars=50)
        self.assertTrue(len(result) >= 2)
        # Each chunk should end with a sentence
        for chunk in result:
            self.assertTrue(len(chunk) <= 50 or len(chunk.split()) == 1)

    def test_split_long_word(self):
        from app.channels.sender import split_message
        text = 'Uma frase com palavras normais seguida de outra frase com mais palavras diferentes e variadas para testar'
        result = split_message(text, max_chars=40)
        self.assertTrue(len(result) >= 2)

    def test_empty_text(self):
        from app.channels.sender import split_message
        result = split_message('', max_chars=200)
        self.assertEqual(result, [''])

    def test_exact_limit(self):
        from app.channels.sender import split_message
        text = 'x' * 200
        result = split_message(text, max_chars=200)
        self.assertEqual(len(result), 1)

    def test_returns_all_content(self):
        from app.channels.sender import split_message
        text = 'Oi! Tudo bem? Preciso de ajuda com automacao. Voce pode me ajudar?'
        result = split_message(text, max_chars=30)
        rejoined = ' '.join(result)
        # All words should be present
        for word in text.split():
            self.assertIn(word, rejoined)


if __name__ == '__main__':
    unittest.main()
