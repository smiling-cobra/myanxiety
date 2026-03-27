import logging
import os

import anthropic

logger = logging.getLogger(__name__)

_MODEL = 'claude-sonnet-4-20250514'


class LlmService:
    def __init__(self):
        api_key = os.environ.get('CLAUDE_API_KEY')
        if not api_key:
            raise ValueError('CLAUDE_API_KEY is not set in environment variables')
        self._client = anthropic.Anthropic(api_key=api_key)

    def get_empathetic_response(self, mood_score: int, entry_text: str) -> str:
        prompt = (
            f"You are a compassionate, private journal assistant helping someone process anxiety.\n\n"
            f"The user rated their mood {mood_score}/10 and wrote:\n\"{entry_text}\"\n\n"
            f"Respond empathetically in 2-3 short paragraphs. Acknowledge their feelings, "
            f"offer a gentle reframe or observation if appropriate, and end with a brief encouraging note. "
            f"Be warm but not saccharine. Do not give medical advice."
        )
        return self._call(prompt)

    def extract_tags(self, entry_text: str) -> list:
        prompt = (
            f"Extract 1-5 short tags (1-2 words each) from this journal entry that capture "
            f"the main themes or triggers. Return only a comma-separated list, nothing else.\n\n"
            f"Entry: \"{entry_text}\""
        )
        raw = self._call(prompt)
        return [t.strip().lower() for t in raw.split(',') if t.strip()][:5]

    def get_weekly_summary(self, entries: list) -> str:
        formatted = '\n'.join(
            [f"- Mood {e['mood_score']}/10: {e['text']}" for e in entries]
        )
        prompt = (
            f"Based on these journal entries from the past week, write a brief (3-4 sentences) "
            f"compassionate summary that highlights patterns, recurring themes, and any positive changes. "
            f"Be encouraging.\n\nEntries:\n{formatted}"
        )
        return self._call(prompt)

    def _call(self, prompt: str) -> str:
        try:
            message = self._client.messages.create(
                model=_MODEL,
                max_tokens=512,
                messages=[{'role': 'user', 'content': prompt}]
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f'LLM call failed: {e}')
            return "I'm having trouble responding right now. Please try again later."
