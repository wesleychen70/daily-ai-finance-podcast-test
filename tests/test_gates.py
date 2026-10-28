import copy
import hashlib
import json
import tempfile
import io
import zipfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from podcast.common import GateError
from podcast.editorial import TOPICS, audio_similarity, validate_script
from podcast.feed import build_feed
from podcast.hosting import probe_media
from podcast.sources import fresh, parse_date, rss_records, source_gate, yahoo


class Gates(unittest.TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 10, 28, 6, tzinfo=timezone(timedelta(hours=8)))

    def test_future_and_stale_sources_rejected(self):
        self.assertFalse(fresh(self.cutoff + timedelta(seconds=1), self.cutoff, 5))
        self.assertFalse(fresh(self.cutoff - timedelta(days=6), self.cutoff, 5))
        self.assertTrue(fresh(self.cutoff - timedelta(days=3), self.cutoff, 5))

    def test_rss_preserves_evidence_and_rejects_future(self):
        raw = b'<rss><channel><item><title>A &amp; B</title><link>https://example.org/a</link><pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate><description>Official summary</description></item><item><title>future</title><link>https://example.org/b</link><pubDate>Thu, 29 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        rows = rss_records(raw, 'Publisher', 'world', self.cutoff)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['evidence'], 'A & B\nOfficial summary')

    def test_undated_news_rejected(self):
        self.assertEqual(rss_records(b'<rss><item><title>undated</title></item></rss>', 'P', 'world', self.cutoff), [])

    def test_xxe_rejected(self):
        with self.assertRaises(Exception):
            rss_records(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]><rss><item><title>&x;</title></item></rss>', 'P', 'world', self.cutoff)

    def test_source_gate_requires_all_sections_and_us(self):
        with self.assertRaises(GateError):
            source_gate({'records': []})
        records = [{'category': x, 'id': x} for x in ['market', 'taiwan', 'macro', 'tech', 'world', 'risk', 'events']]
        records += [{'category': 'market', 'id': x} for x in ['sp500-0', 'nasdaq-0', 'dax-0']]
        source_gate({'records': records})

    def test_us_close_included_at_taiwan_morning(self):
        from zoneinfo import ZoneInfo
        eastern = ZoneInfo('America/New_York')
        dates = [datetime(2026, 10, d, 9, 30, tzinfo=eastern) for d in [26, 27]]
        data = {'chart': {'result': [{'meta': {'exchangeTimezoneName': 'America/New_York'},
                'timestamp': [int(x.timestamp()) for x in dates],
                'indicators': {'quote': [{'close': [100, 101]}]}}]}}
        row = yahoo(json.dumps(data), 'sp500', self.cutoff)
        self.assertIn('2026-10-27', row['evidence'])
        self.assertIn('+1.00%', row['evidence'])

    def valid_script(self):
        bundle = {'records': [{'id': 's1', 'evidence': 'The closing value was 17.52.'}]}
        text = '這裡是根據公開資料整理的市場觀察，相關資訊仍有其限制，請審慎閱讀。' * 23
        script = {'topics': TOPICS[:], 'sections': [
            {'topic': t, 'paragraphs': [{'text': text, 'source_ids': ['s1'],
                                        'evidence_quotes': ['closing value was 17.52']}]} for t in TOPICS]}
        return script, bundle

    def test_script_rejects_unknown_source(self):
        script, bundle = self.valid_script()
        script['sections'][0]['paragraphs'][0]['source_ids'] = ['invented']
        with self.assertRaisesRegex(GateError, 'uncited'):
            validate_script(script, bundle)

    def test_script_rejects_fabricated_quote(self):
        script, bundle = self.valid_script()
        script['sections'][0]['paragraphs'][0]['evidence_quotes'] = ['close was 99']
        with self.assertRaisesRegex(GateError, 'quote'):
            validate_script(script, bundle)

    def test_script_rejects_missing_topic(self):
        script, bundle = self.valid_script()
        script['topics'] = []
        with self.assertRaisesRegex(GateError, 'topics'):
            validate_script(script, bundle)

    def test_script_rejects_short_episode(self):
        script, bundle = self.valid_script()
        for s in script['sections']:
            s['paragraphs'][0]['text'] = '市場觀察。'
        with self.assertRaisesRegex(GateError, 'target'):
            validate_script(script, bundle)

    def test_audio_similarity_detects_changed_speech(self):
        self.assertEqual(audio_similarity('台股上漲。', '台股上漲！'), 1)
        self.assertLess(audio_similarity('台股上漲百分之一。', '美股重挫百分之八。'), .6)

    def test_feed_rejects_unverified_episode(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(GateError):
                build_feed([{'status': 'DRAFT', 'date': '2026-10-28'}], Path(d), 'https://example.org')

    def test_feed_escapes_xml_and_blocks_directory_submission(self):
        ep = {'status': 'VERIFIED_TEST', 'date': '2026-10-28', 'published_at': self.cutoff.isoformat(),
              'title': '測試 & <財經>', 'guid': 'urn:test:1', 'description': 'a & b', 'bytes': 160000,
              'audio_url': 'https://example.org/a.mp3', 'duration': 1200, 'transcript_url': 'https://example.org/a.txt'}
        with tempfile.TemporaryDirectory() as d:
            path = build_feed([ep], Path(d), 'https://example.org')
            root = ET.parse(path)
            self.assertEqual(root.findtext('./channel/item/title'), ep['title'])
            self.assertEqual(root.find('./channel/item/enclosure').get('length'), '160000')
            self.assertEqual(root.findtext('./channel/{http://www.itunes.com/dtds/podcast-1.0.dtd}block'), 'Yes')
            from PIL import Image
            with Image.open(Path(d) / 'cover.jpg') as image:
                self.assertEqual(image.size, (1600, 1600))

    def test_host_probe_requires_range_and_matching_hash(self):
        class Response:
            def __init__(self, code, headers, content=b''):
                self.status_code, self.headers, self.content, self.history = code, headers, content, []
        data = b'x' * 2048
        responses = [Response(200, {'Content-Length': '2048', 'Content-Type': 'audio/mpeg'}),
                     Response(206, {'Content-Range': 'bytes 0-1023/2048'}, data[:1024]), Response(200, {}, data)]
        with patch('podcast.hosting.request', side_effect=responses):
            self.assertEqual(probe_media('https://example.org/a.mp3', hashlib.sha256(data).hexdigest(), 2048)['status'], 'HTTP_COMPATIBILITY_PASSED')
        with patch('podcast.hosting.request', side_effect=[responses[0], Response(200, {}, data)]):
            with self.assertRaisesRegex(GateError, 'byte range'):
                probe_media('https://example.org/a.mp3', 'bad', 2048)

    def test_host_probe_rejects_html_and_auth_gate(self):
        class Response:
            status_code = 200
            headers = {'Content-Length': '2048', 'Content-Type': 'text/html'}
        with patch('podcast.hosting.request', return_value=Response()):
            with self.assertRaisesRegex(GateError, 'MIME'):
                probe_media('https://example.org/login', 'bad', 2048)

    def test_checkpoint_rejects_path_traversal(self):
        from podcast.checkpoint import restore
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w') as archive:
            archive.writestr('../stolen.txt', 'unexpected')
        class Release:
            status_code = 200
            def json(self):
                return {'assets': [{'name': 'checkpoint.zip', 'browser_download_url': 'https://example.org/cache'}]}
        class Download:
            content = memory.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            with patch('requests.get', return_value=Release()), patch('podcast.checkpoint.request', return_value=Download()):
                with self.assertRaisesRegex(GateError, 'Unsafe'):
                    restore(Path(directory), 'owner/repo')

    def test_snapshot_tampering_blocks_generation(self):
        from podcast.sources import verify_snapshots
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'raw').mkdir()
            (work / 'raw/source.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(GateError, 'snapshot'):
                verify_snapshots({'records': [{'id': 's', 'raw_file': 'source.bin', 'raw_sha256': 'incorrect'}]}, work)


if __name__ == '__main__':
    unittest.main()
