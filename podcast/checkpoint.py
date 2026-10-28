"""Resume a failed RSS deployment without paying for the same daily speech twice."""
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path

from .common import GateError, now, request, sha


def pack(work):
    archive = work / 'checkpoint.zip'
    paths = [work / name for name in ['sources.json', 'script.json', 'api-budget.json', 'editorial-check.json', 'audio-fidelity-check.json']]
    paths += list(work.glob('section-[0-9].json'))
    paths += [p for p in (work / 'chunks').glob('*') if re.fullmatch(r'\d{2}\.(mp3|json)', p.name)]
    bundle = json.loads((work / 'sources.json').read_text(encoding='utf-8'))
    paths += [work / 'raw' / name for name in {r['raw_file'] for r in bundle['records']}]
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        for p in paths:
            target.write(p, p.relative_to(work).as_posix())
    return archive


def restore(work, repo):
    headers = {'Accept': 'application/vnd.github+json'}
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    import requests
    r = requests.get(f'https://api.github.com/repos/{repo}/releases/tags/test-{now().date()}',
                     headers=headers, timeout=30)
    if r.status_code == 404:
        return False
    if r.status_code != 200:
        raise GateError('Cannot inspect daily checkpoint release')
    asset = next((x for x in r.json().get('assets', []) if x['name'] == 'checkpoint.zip'), None)
    if not asset:
        return False
    raw = request('GET', asset['browser_download_url']).content
    digest = asset.get('digest')
    if digest and digest != 'sha256:' + hashlib.sha256(raw).hexdigest():
        raise GateError('Checkpoint asset checksum mismatch')
    work.mkdir(parents=True, exist_ok=True)
    archive = work / 'checkpoint.zip'
    archive.write_bytes(raw)
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 300 or sum(x.file_size for x in source.infolist()) > 200_000_000:
            raise GateError('Checkpoint archive limits exceeded')
        for info in source.infolist():
            path = Path(info.filename)
            if path.is_absolute() or '..' in path.parts or ':' in info.filename or '\\' in info.filename:
                raise GateError('Unsafe checkpoint path')
            allowed = re.fullmatch(r'(sources|script|api-budget|editorial-check|audio-fidelity-check|section-[0-9])\.json|chunks/\d{2}\.(mp3|json)|raw/[a-zA-Z0-9_]+\.bin', info.filename)
            if not allowed:
                raise GateError('Unexpected checkpoint entry')
        source.extractall(work)
    print('Restored daily verified speech checkpoint; source/script/audio gates still run.')
    return True
