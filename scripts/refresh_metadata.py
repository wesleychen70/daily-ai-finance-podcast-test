"""Update a verified feed's public metadata without generating new financial content or TTS."""
import json
import os
import sys
from pathlib import Path

from podcast.common import GateError, save
from podcast.feed import build_feed
from podcast.hosting import probe_media
from podcast.publish import restore_pages_media

directory = Path('public')
episodes = json.loads((directory / 'episodes.json').read_text(encoding='utf-8'))
if not episodes or any(x.get('status') != 'VERIFIED_TEST' for x in episodes):
    raise GateError('No verified episodes available for metadata-only deployment')
latest = max(episodes, key=lambda x: x['date'])
work = Path('build/metadata')
save(work / 'manifest.json', latest)
if len(sys.argv) < 2 or sys.argv[1] != 'verify':
    base = os.environ['PAGES_BASE_URL']
    restore_pages_media(directory, base)
    build_feed(episodes, directory, base, os.environ.get('PODCAST_OWNER_EMAIL', ''))
else:
    report = probe_media(latest['audio_url'], latest['sha256'], latest['bytes'])
    save(work / 'hosting-check.json', report)
    print('Existing verified MP3 still matches its published checksum.')
