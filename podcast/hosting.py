import hashlib
import re
from pathlib import Path

from .common import GateError, request, save


def probe_media(url, expected_sha, expected_size):
    # Absolutely no GitHub auth: imitate a public podcast fetch, following redirects.
    headers = {'User-Agent': 'PodcastMediaCompatibilityProbe/1.0', 'Accept-Encoding': 'identity'}
    head = request('HEAD', url, headers=headers, allow_redirects=True)
    if head.status_code != 200 or int(head.headers.get('Content-Length', -1)) != expected_size:
        raise GateError('HOST_GATE: HEAD size/status mismatch')
    if head.headers.get('Content-Type', '').split(';')[0] != 'audio/mpeg':
        raise GateError('HOST_GATE: MP3 MIME type mismatch')
    partial = request('GET', url, headers={**headers, 'Range': 'bytes=0-1023'})
    if partial.status_code != 206 or len(partial.content) != 1024:
        raise GateError('HOST_GATE: byte range requests failed')
    if partial.headers.get('Content-Range') != f'bytes 0-1023/{expected_size}':
        raise GateError('HOST_GATE: invalid Content-Range')
    full = request('GET', url, headers=headers)
    if len(full.content) != expected_size or hashlib.sha256(full.content).hexdigest() != expected_sha:
        raise GateError('HOST_GATE: full download checksum mismatch')
    return {'status': 'HTTP_COMPATIBILITY_PASSED', 'url': url,
            'head': head.status_code, 'range': partial.status_code, 'bytes': len(full.content),
            'sha256': expected_sha, 'redirects': len(full.history),
            'spotify_ingestion': 'NOT_RUN_REQUIRES_OWNER_AUTHORIZATION'}
