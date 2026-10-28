import json
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .common import GateError, now, save, sha

ITUNES = 'http://www.itunes.com/dtds/podcast-1.0.dtd'
ATOM = 'http://www.w3.org/2005/Atom'
PODCAST = 'https://podcastindex.org/namespace/1.0'
for prefix, uri in [('itunes', ITUNES), ('atom', ATOM), ('podcast', PODCAST)]:
    ET.register_namespace(prefix, uri)


def cover(dest):
    if Path(dest).exists():
        with Image.open(dest) as existing:
            if existing.size == (1600, 1600):
                return
    image = Image.new('RGB', (1600, 1600), '#101f35')
    draw = ImageDraw.Draw(image)
    for y in range(800, 1500, 100):
        draw.line((120, y, 1480, y), fill='#243c59', width=2)
    draw.line([(120, 1250), (400, 1100), (640, 1200), (920, 880), (1180, 960), (1480, 650)],
              fill='#54dec4', width=20)
    fonts = [Path('C:/Windows/Fonts/msjh.ttc'), Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    fontfile = next((p for p in fonts if p.exists()), None)
    font = ImageFont.truetype(str(fontfile), 138) if fontfile else ImageFont.load_default(size=100)
    draw.text((115, 160), 'AI 財經早報' if fontfile else 'AI FINANCE', font=font, fill='white')
    small = ImageFont.truetype(str(fontfile), 64) if fontfile else ImageFont.load_default(size=64)
    draw.text((120, 390), '測試節目' if fontfile else 'TEST PODCAST', font=small, fill='#54dec4')
    image.save(dest)


def build_feed(episodes, directory, base_url, email=''):
    if not base_url.startswith('https://'):
        raise GateError('RSS requires public HTTPS base URL')
    directory.mkdir(parents=True, exist_ok=True)
    root = ET.Element('rss', version='2.0')
    channel = ET.SubElement(root, 'channel')
    for tag, text in [('title', '每日 AI 財經早報｜測試'), ('link', base_url + '/'),
                      ('description', '自動化系統測試。AI 生成的繁體中文財經摘要，非投資建議。'),
                      ('language', 'zh-TW'), ('lastBuildDate', format_datetime(now())),
                      (f'{{{ITUNES}}}author', 'AI 財經早報測試'), (f'{{{ITUNES}}}explicit', 'false'),
                      (f'{{{ITUNES}}}type', 'episodic')]:
        ET.SubElement(channel, tag).text = text
    ET.SubElement(channel, f'{{{ATOM}}}link', href=base_url + '/rss-test.xml', rel='self', type='application/rss+xml')
    ET.SubElement(channel, f'{{{ITUNES}}}image', href=base_url + '/cover.jpg')
    category = ET.SubElement(channel, f'{{{ITUNES}}}category', text='News')
    ET.SubElement(category, f'{{{ITUNES}}}category', text='Business News')
    ET.SubElement(channel, f'{{{ITUNES}}}block').text = 'Yes'  # No directory submission before owner approval.
    if email:
        owner = ET.SubElement(channel, f'{{{ITUNES}}}owner')
        ET.SubElement(owner, f'{{{ITUNES}}}name').text = 'AI 財經早報測試'
        ET.SubElement(owner, f'{{{ITUNES}}}email').text = email
    for ep in sorted(episodes, key=lambda x: x['date'], reverse=True):
        if ep.get('status') != 'VERIFIED_TEST':
            raise GateError('RSS_GATE: unverified episode refused')
        item = ET.SubElement(channel, 'item')
        ET.SubElement(item, 'title').text = ep['title']
        ET.SubElement(item, 'guid', isPermaLink='false').text = ep['guid']
        ET.SubElement(item, 'pubDate').text = format_datetime(datetime.fromisoformat(ep['published_at']))
        ET.SubElement(item, 'description').text = ep['description']
        ET.SubElement(item, 'enclosure', url=ep['audio_url'], length=str(ep['bytes']), type='audio/mpeg')
        ET.SubElement(item, f'{{{ITUNES}}}duration').text = str(round(ep['duration']))
        ET.SubElement(item, f'{{{ITUNES}}}explicit').text = 'false'
        ET.SubElement(item, f'{{{PODCAST}}}transcript', url=ep['transcript_url'], type='text/plain')
    ET.indent(root)
    ET.ElementTree(root).write(directory / 'rss-test.xml', encoding='utf-8', xml_declaration=True)
    cover(directory / 'cover.jpg')
    (directory / '.nojekyll').touch()
    (directory / 'robots.txt').write_text('User-agent: *\nDisallow: /\n', encoding='utf-8')
    players = ''.join('<article><h2>' + html.escape(ep['title']) + '</h2><audio controls preload="none" src="'
                      + html.escape(ep['audio_url'], quote=True) + '"></audio><p><a href="'
                      + html.escape(ep['audio_url'], quote=True) + '">下載測試 MP3</a> · <a href="'
                      + html.escape(ep['transcript_url'], quote=True) + '">逐字稿</a></p></article>'
                      for ep in sorted(episodes, key=lambda x: x['date'], reverse=True)[:5])
    (directory / 'index.html').write_text('''<!doctype html><html lang="zh-Hant"><meta charset="utf-8">
<meta name="robots" content="noindex"><title>每日 AI 財經早報｜測試</title>
<style>body{max-width:760px;margin:4rem auto;padding:1rem;font:20px/1.7 system-ui;background:#101f35;color:#fff}a{color:#54dec4}</style>
<h1>每日 AI 財經早報｜測試</h1><p>這是技術測試頻道，尚未提交 Spotify，不是正式節目。</p>
<p>內容由 AI 自動生成並經程式與模型輔助檢查；不構成投資建議。</p>
<a href="rss-test.xml">測試 RSS</a><p>逐字稿、來源與驗證記錄請見 GitHub Releases。</p>'''
                                        + players + '</html>', encoding='utf-8')
    return directory / 'rss-test.xml'
