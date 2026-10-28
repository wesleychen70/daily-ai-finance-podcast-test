"""Bound scheduled execution and idempotency to the Taiwan episode date."""
import json
import os
import subprocess
import sys
from pathlib import Path

from podcast.common import now

stamp = now()
date = stamp.date().isoformat()
output = Path(os.environ['GITHUB_OUTPUT'])
work = 'build/' + date
with output.open('a') as stream:
    stream.write(f'work={work}\ndate={date}\n')
episodes = Path('public/episodes.json')
exists = episodes.exists() and any(x['date'] == date for x in json.loads(episodes.read_text(encoding='utf-8')))
too_late = os.environ.get('GITHUB_EVENT_NAME') == 'schedule' and stamp.hour >= 7
if exists or too_late:
    with output.open('a') as stream:
        stream.write('skip=true\n')
    print('Already published today, or scheduled run arrived after 07:00 Taiwan time; skipping.')
else:
    with output.open('a') as stream:
        stream.write('skip=false\n')
