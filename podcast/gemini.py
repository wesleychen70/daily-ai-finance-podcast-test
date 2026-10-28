import base64
import json
import os
from pathlib import Path

from .common import GateError, now, request, save


class Gemini:
    def __init__(self, work):
        self.key = os.environ.get('GEMINI_API_KEY')
        if not self.key:
            raise GateError('GEMINI_API_KEY is missing')
        self.work = Path(work)
        self.ledger = self.work / 'api-budget.json'
        self.model = os.environ.get('GEMINI_TEXT_MODEL', 'gemini-2.5-flash')
        self.tts_model = os.environ.get('GEMINI_TTS_MODEL', 'gemini-3.8-flash-lite-tts')

    def call(self, url, body):
        if os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and (now().hour, now().minute) >= (6, 55):
            raise GateError('Scheduled generation cutoff reached; do not publish late')
        budget = json.loads(self.ledger.read_text()) if self.ledger.exists() else {'calls': 0}
        # Includes HTTP retries in a conservative upper bound. Never upgrade billing.
        if budget['calls'] + 3 > 210:
            raise GateError('Daily API request budget exhausted')
        budget['calls'] += 3
        save(self.ledger, budget)
        return request('POST', 'https://generativelanguage.googleapis.com/v1beta/' + url,
                       headers={'x-goog-api-key': self.key}, json=body).json()

    def json(self, prompt, audio=None):
        parts = [{'text': prompt}]
        if audio:
            parts.append({'inlineData': {'mimeType': 'audio/mpeg',
                                        'data': base64.b64encode(Path(audio).read_bytes()).decode()}})
        r = self.call(f'models/{self.model}:generateContent', {
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'temperature': 0.1, 'responseMimeType': 'application/json',
                                 'maxOutputTokens': 24000}})
        candidates = r.get('candidates', [])
        if not candidates or candidates[0].get('finishReason') != 'STOP':
            raise GateError('Gemini output blocked or truncated')
        return json.loads(''.join(p.get('text', '') for p in candidates[0]['content']['parts']))

    def speech(self, text, dest):
        r = self.call('interactions', {
            'model': self.tts_model,
            'input': [{'type': 'user_input', 'content': [{
                'type': 'text', 'text': text,
                'annotations': [{'type': 'speech_metadata', 'style':
                    '繁體中文，台灣國語口音，台灣財經廣播主持人。自然、清晰、溫暖，不誇張，'
                    '每分鐘約二百六十至三百個中文字。逐字朗讀，不加內容，不讀出指示。'}]}]}],
            'response_format': {'type': 'audio'},
            'generation_config': {'speech_config': [{'voice': 'Kore'}]}})
        audio = [c for step in r.get('steps', []) for c in step.get('content', [])
                 if c.get('type') == 'audio' and c.get('data')]
        if not audio:
            raise GateError('Gemini TTS returned no audio')
        raw = base64.b64decode(audio[-1]['data'], validate=True)
        if not raw.startswith(b'RIFF'):
            raise GateError('Expected WAV response from current TTS API')
        Path(dest).write_bytes(raw)
