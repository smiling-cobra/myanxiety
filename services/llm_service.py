

import os
import anthropic
import traceback

claude_api_key = os.environ.get('CLAUDE_API_KEY')
client = anthropic.Anthropic(api_key=claude_api_key)


class LlmService():
    def get_response(self, prompt: str) -> str:
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=512,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            return response
        except Exception as e:
            print(f"An error occurred: {e}")
            traceback.print_exc()
            print(f"CLAUDE_API_KEY set: {bool(claude_api_key)}")
            print(f"Prompt: {prompt}")
            return ""
