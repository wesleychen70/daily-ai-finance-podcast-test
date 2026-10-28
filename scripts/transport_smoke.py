import os
from pathlib import Path

from podcast.common import request, save, sha
from podcast.feed import build_feed
from podcast.hosting import probe_media

base = os.environ['PAGES_BASE_URL']
directory = Path('public')
if os.environ.get('SMOKE_STAGE') == 'prepare':
    import json
    state = directory / 'episodes.json'
    if state.exists() and json.loads(state.read_text(encoding='utf-8')):
        raise RuntimeError('Refusing to replace an existing podcast with the one-off empty smoke feed.')
    build_feed([], directory, base)
    media = directory / 'media'
    media.mkdir(exist_ok=True)
    raw = request('GET', 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] +
                  '/releases/download/transport-smoke-test/voice-test.mp3').content
    path = media / 'voice-test.mp3'
    path.write_bytes(raw)
    save('build/transport-expected.json', {'sha256': sha(path), 'bytes': len(raw)})
else:
    import json
    metadata = json.loads(Path('build/transport-expected.json').read_text())
    report = probe_media(base + '/media/voice-test.mp3', metadata['sha256'], metadata['bytes'])
    save('build/transport-pages-check.json', report)
    print(report)
