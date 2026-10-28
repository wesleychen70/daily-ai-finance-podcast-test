import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TAIPEI = ZoneInfo('Asia/Taipei')


class GateError(RuntimeError):
    pass


def now():
    return datetime.now(TAIPEI)


def load_env():
    p = Path('.env')
    if p.exists():
        for line in p.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def request(method, url, **kwargs):
    # Keys are headers, never URL query parameters or log output.
    headers = {'User-Agent': 'DailyFinancePodcast/0.1 (+source verification)'}
    headers.update(kwargs.pop('headers', {}))
    for attempt in range(3):
        try:
            timeout = kwargs.pop('timeout', (15, 180) if method == 'POST' else (10, 30))
            r = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
            if r.status_code == 429:
                try:
                    details = r.json().get('error', {}).get('details', [])
                    violations = [v for detail in details for v in detail.get('violations', [])]
                    message = str(r.json().get('error', {}).get('message', '')).lower()
                    if any('PerDay' in v.get('quotaId', '') for v in violations) or 'requests per day' in message:
                        raise GateError('FREE_TIER_DAILY_QUOTA_EXHAUSTED; no billing upgrade attempted')
                except (ValueError, AttributeError):
                    pass
            if r.status_code == 429 or r.status_code >= 500:
                if attempt < 2:
                    retry = r.headers.get('Retry-After', '')
                    delay = float(retry) if retry.isdigit() else (30 if r.status_code == 429 else 5 * 2**attempt)
                    time.sleep(min(60, delay))
                    continue
            if not r.ok:
                raise GateError(f'HTTP {r.status_code}: {url.split("?")[0]}')
            return r
        except requests.RequestException as exc:
            if attempt == 2:
                raise GateError(f'Network failure: {url.split("?")[0]} ({type(exc).__name__})') from None
            time.sleep(3 * 2**attempt)
    raise GateError('Request retries exhausted')
