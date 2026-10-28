"""Stage media with existing RSS unchanged; probe only after Pages deployment."""
import json
import os
import shutil
import sys
from pathlib import Path

from podcast.common import GateError, save
from podcast.feed import build_feed
from podcast.hosting import probe_media
from podcast.publish import restore_pages_media

work = Path(sys.argv[1])
manifest = json.loads((work / 'manifest.json').read_text(encoding='utf-8'))
repo = os.environ['GITHUB_REPOSITORY']
url = f'https://github.com/{repo}/releases/download/test-{manifest["date"]}/episode.mp3'
needed = False
try:
    probe_media(url, manifest['sha256'], manifest['bytes'])
except GateError:
    needed = True
    directory = Path('public')
    directory.mkdir(exist_ok=True)
    if not (directory / 'rss-test.xml').exists():
        build_feed([], directory, os.environ['PAGES_BASE_URL'])
    restore_pages_media(directory, os.environ['PAGES_BASE_URL'])
    media = directory / 'media'
    media.mkdir(exist_ok=True)
    shutil.copyfile(work / 'episode.mp3', media / f'test-{manifest["date"]}.mp3')
    # Maximum 20 episodes (~450 MB at 23 minutes, 128 kbps); only deployed data, not build caches.
    keep = sorted(media.glob('test-*.mp3'), reverse=True)[:20]
    # Old public files stay in staging until the final feed has been pruned.
    save(work / 'fallback-retention.json', {'keep': [p.name for p in keep]})
with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
    stream.write('needed=' + str(needed).lower() + '\n')
