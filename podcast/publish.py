import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote

from .common import GateError, now, request, save, sha
from .feed import build_feed
from .hosting import probe_media


def restore_pages_media(directory, base_url):
    state = directory / 'episodes.json'
    if not state.exists():
        return
    episodes = sorted(json.loads(state.read_text(encoding='utf-8')), key=lambda x: x['date'], reverse=True)[:20]
    media = directory / 'media'
    media.mkdir(parents=True, exist_ok=True)
    for ep in episodes:
        if not ep.get('audio_url', '').startswith(base_url.rstrip('/') + '/media/'):
            continue
        import re
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', ep['date']):
            raise GateError('Invalid episode date')
        path = media / ('test-' + ep['date'] + '.mp3')
        if path.exists() and sha(path) == ep['sha256']:
            continue
        raw = request('GET', ep['audio_url']).content
        import hashlib
        if hashlib.sha256(raw).hexdigest() != ep['sha256']:
            raise GateError('Existing Pages episode download checksum mismatch')
        path.write_bytes(raw)


def github(method, path, **kwargs):
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if not token:
        raise GateError('GitHub token is missing')
    return request(method, 'https://api.github.com' + path,
                   headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}, **kwargs)


def publish(work, repo, base_url, fallback_base=''):
    if os.environ.get('PUBLIC_TEST_ENABLED') != 'true':
        raise GateError('Public test publication is disabled')
    if not repo or not base_url:
        raise GateError('Repository and Pages URL required')
    manifest = json.loads((work / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['status'] != 'VERIFIED_TEST' or sha(work / 'episode.mp3') != manifest['sha256']:
        raise GateError('PUBLISH_GATE: manifest or audio changed')
    # Bind every verified artifact to its exact reviewed bytes.
    for name, digest in manifest['files'].items():
        if sha(work / name) != digest:
            raise GateError('PUBLISH_GATE: reviewed artifact modified: ' + name)
    tag = 'test-' + manifest['date']
    url = f'https://github.com/{repo}/releases/download/{tag}/episode.mp3'
    releases = github('GET', f'/repos/{repo}/releases?per_page=100').json()
    release = next((x for x in releases if x['tag_name'] == tag), None)
    if not release:
        release = github('POST', f'/repos/{repo}/releases', json={
            'tag_name': tag, 'name': manifest['title'], 'draft': True, 'prerelease': True,
            'body': '技術測試，非正式節目。來源與逐字稿附於附件；未提交 Spotify。'}).json()
    upload = release['upload_url'].split('{')[0]
    token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
    existing = {a['name']: a for a in release.get('assets', [])}
    from .checkpoint import pack
    pack(work)
    names = ['episode.mp3', 'transcript.txt', 'sources.json', 'script.json', 'editorial-check.json', 'audio-check.json', 'audio-fidelity-check.json', 'manifest.json', 'checkpoint.zip']
    if (work / 'pilot-audio-assembly.json').exists():
        names.append('pilot-audio-assembly.json')
    for name in names:
        p = work / name
        if name in existing:
            # Public releases are immutable in this pipeline. Never silently replace media under same GUID.
            if not release['draft']:
                continue
            github('DELETE', f'/repos/{repo}/releases/assets/{existing[name]["id"]}')
        mime = 'audio/mpeg' if name.endswith('.mp3') else 'application/zip' if name.endswith('.zip') else 'application/json' if name.endswith('.json') else 'text/plain; charset=utf-8'
        request('POST', upload + '?name=' + quote(name), headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': mime}, data=p.read_bytes())
    if release['draft']:
        github('PATCH', f'/repos/{repo}/releases/{release["id"]}', json={'draft': False})
    try:
        report = probe_media(url, manifest['sha256'], manifest['bytes'])
        fallback = False
    except GateError:
        # Simplest no-account fallback: serve a bounded rolling set of MP3s on Pages.
        # Deploy/probe before including the URL in RSS; pages-publish does this phase.
        if not fallback_base:
            raise GateError('Release hosting failed; RSS unchanged. Configure Pages media fallback and re-run.') from None
        url = fallback_base.rstrip('/') + f'/media/{tag}.mp3'
        report = probe_media(url, manifest['sha256'], manifest['bytes'])
        fallback = True
    save(work / 'hosting-check.json', report)
    directory = Path('public')
    statepath = directory / 'episodes.json'
    episodes = json.loads(statepath.read_text(encoding='utf-8')) if statepath.exists() else []
    episode = dict(manifest, audio_url=url,
                   transcript_url=f'https://github.com/{repo}/releases/download/{tag}/transcript.txt')
    episodes = [x for x in episodes if x['guid'] != episode['guid']] + [episode]
    if fallback:
        restore_pages_media(directory, base_url)
        episodes = sorted(episodes, key=lambda x: x['date'], reverse=True)[:20]
        keep = {'test-' + x['date'] + '.mp3' for x in episodes}
        media = directory / 'media'
        if media.exists():
            for path in media.glob('test-*.mp3'):
                if path.name not in keep:
                    path.unlink()
    save(statepath, episodes)
    build_feed(episodes, directory, base_url, os.environ.get('PODCAST_OWNER_EMAIL', ''))
    return report
