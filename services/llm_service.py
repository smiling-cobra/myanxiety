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

    def get_psychological_guidance(self, mood_score: int, entry_text: str) -> str:
        if mood_score <= 2:
            techniques = (
                "DBT distress tolerance TIPP skills (Temperature — try cold water on your face or wrists; "
                "Intense exercise — 60 seconds of jumping jacks or running in place; "
                "Paced breathing — inhale 4 counts, hold 4, exhale 6; "
                "Progressive muscle relaxation — tense and release each muscle group) "
                "and ACT defusion (noticing thoughts without fusing with them: "
                "\"I notice I'm having the thought that...\")."
            )
        else:
            techniques = (
                "Behavioral Activation (identify one small, concrete action that historically lifts your mood), "
                "CBT thought-checking (gently examine whether an unhelpful thought holds up to scrutiny), "
                "and a mindfulness grounding exercise (5-4-3-2-1: name 5 things you can see, "
                "4 you can touch, 3 you can hear, 2 you can smell, 1 you can taste)."
            )
        prompt = (
            f"You are a supportive mental health companion trained in evidence-based psychological techniques.\n\n"
            f"The user rated their mood {mood_score}/10 and wrote:\n\"{entry_text}\"\n\n"
            f"Provide 3-4 concrete, compassionate coping suggestions tailored to what they shared.\n"
            f"Draw from: {techniques}\n\n"
            f"Format as a short numbered list. Each item: one sentence of context, then one specific action step.\n"
            f"Tone: warm, peer-to-peer, non-clinical. No diagnosis. No medical advice.\n"
            f"End with one short sentence of encouragement.\n"
            f"Do not include crisis hotlines — those are provided separately."
        )
        return self._call(prompt, max_tokens=600)

    def _call(self, prompt: str, max_tokens: int = 512) -> str:
        try:
            message = self._client.messages.create(
                model=_MODEL,
                max_tokens=max_tokens,
                messages=[{'role': 'user', 'content': prompt}]
            )
            return message.content[0].text
        except Exception as e:
            logger.error(f'LLM call failed: {e}')
            return "I'm having trouble responding right now. Please try again later."
