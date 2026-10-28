import json
import os
import sys
import time
from pathlib import Path
from defusedxml import ElementTree as ET

from podcast.common import GateError, request, save

work = Path(sys.argv[1])
manifest = json.loads((work / 'manifest.json').read_text(encoding='utf-8'))
url = os.environ['PAGES_BASE_URL'] + '/rss-test.xml'
for attempt in range(6):
    response = request('GET', url, headers={'Cache-Control': 'no-cache'})
    root = ET.fromstring(response.content)
    if any(x.text == manifest['guid'] for x in root.findall('./channel/item/guid')):
        expected_email = os.environ.get('PODCAST_OWNER_EMAIL', '')
        if expected_email and root.findtext('./channel/{http://www.itunes.com/dtds/podcast-1.0.dtd}owner/{http://www.itunes.com/dtds/podcast-1.0.dtd}email') != expected_email:
            raise GateError('Public RSS owner email readback mismatch')
        save(work / 'pages-check.json', {'status': 'LIVE_RSS_READBACK_PASSED', 'url': url,
                                        'guid': manifest['guid'], 'spotify_ingestion': 'NOT_RUN'})
        save(work / 'status.json', {'status': 'TEST_DEPLOYED_VERIFIED', 'rss': url,
                                   'guid': manifest['guid'], 'spotify_ingestion': 'NOT_RUN',
                                   'human_listening': 'NOT_RUN'})
        print('Live RSS verified: ' + url)
        break
    if attempt == 5:
        raise GateError('Live RSS does not contain the verified episode')
    time.sleep(10)
