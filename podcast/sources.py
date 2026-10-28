import csv
import html
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as ET

from .common import GateError, TAIPEI, now, request, save, sha

FEEDS = {
    'fed': ('macro', 'Federal Reserve', 'https://www.federalreserve.gov/feeds/press_all.xml'),
    'bls': ('macro', 'BLS', 'https://www.bls.gov/feed/bls_latest.rss'),
    'economy': ('macro', 'CNBC', 'https://www.cnbc.com/id/20910258/device/rss/rss.html'),
    'tech': ('tech', 'CNBC', 'https://www.cnbc.com/id/19854910/device/rss/rss.html'),
    'world': ('world', 'CNBC', 'https://www.cnbc.com/id/100727362/device/rss/rss.html'),
    'nvidia': ('tech', 'NVIDIA', 'https://nvidianews.nvidia.com/releases.xml'),
    'microsoft': ('tech', 'Microsoft', 'https://blogs.microsoft.com/feed/'),
    'ecb': ('world', 'ECB', 'https://www.ecb.europa.eu/rss/press.html'),
}
SYMBOLS = {'sp500': '^GSPC', 'nasdaq': '^IXIC', 'dow': '^DJI',
           'nikkei': '^N225', 'hsi': '^HSI', 'dax': '^GDAXI'}


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value or ''))).strip()


def fetch_source(key, url):
    if key.startswith('fred_'):
        # FRED's table pages respond to the stock requests client; the custom feed agent can stall.
        import requests
        try:
            response = requests.get(url, timeout=(10, 20))
            if response.status_code != 200:
                raise GateError(f'FRED table HTTP {response.status_code}')
            return response
        except requests.RequestException:
            raise GateError('FRED table unavailable') from None
    return request('GET', url)


def parse_date(value):
    try:
        d = parsedate_to_datetime(value)
    except (ValueError, TypeError):
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not d.tzinfo:
        raise GateError('Source publication timezone missing')
    return d


def fresh(date, cutoff, days):
    delta = cutoff - date
    return timedelta(0) <= delta <= timedelta(days=days)


def rss_records(raw, name, category, cutoff):
    root = ET.fromstring(raw)
    result = []
    for node in root.findall('.//item'):
        title = plain(node.findtext('title'))
        link = node.findtext('link', '')
        try:
            published = parse_date(node.findtext('pubDate', ''))
        except (ValueError, TypeError, GateError):
            continue
        if not fresh(published, cutoff, 7) or not link.startswith('https://'):
            continue
        description = plain(node.findtext('description'))[:900]
        result.append({'category': category, 'publisher': name, 'url': link,
                       'published_at': published.isoformat(),
                       'evidence': title + '\n' + description,
                       'scope': 'RSS headline and publisher-provided summary only; do not infer article details'})
    return result[:10]


def yahoo(raw, key, cutoff):
    result = json.loads(raw)['chart']['result'][0]
    tz = ZoneInfo(result['meta']['exchangeTimezoneName'])
    closes = result['indicators']['quote'][0]['close']
    points = [(datetime.fromtimestamp(t, tz), float(c))
              for t, c in zip(result['timestamp'], closes) if c is not None]
    # At Taiwan 05:17 the US local date is still yesterday: include its finished session.
    # Never discard a completed US session merely because the US calendar date hasn't changed.
    close_hour, close_minute = {'nikkei': (15, 30), 'hsi': (16, 0), 'dax': (17, 30)}.get(key, (16, 0))
    points = [(d, c) for d, c in points
              if d.replace(hour=close_hour, minute=close_minute) + timedelta(minutes=15) <= cutoff]
    if len(points) < 2:
        raise GateError('Insufficient completed market sessions')
    date, close = points[-1]
    if not fresh(date, cutoff, 5):
        raise GateError('Stale market observation')
    change = (close / points[-2][1] - 1) * 100
    return {'category': 'market', 'publisher': 'Yahoo Finance (unofficial public chart endpoint)',
            'published_at': date.isoformat(), 'evidence':
            f'{key} completed daily session {date.date()}: close {close:.2f}; daily change {change:+.2f}%. '
            'This is a previous completed session, not a live quote.', 'scope': 'Market daily close'}


def collect(work, cutoff=None):
    cutoff = cutoff or now()
    previous_path = work / 'sources.json'
    previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {'records': []}
    rawdir = work / 'raw'
    rawdir.mkdir(parents=True, exist_ok=True)
    tasks = {}
    for key, (category, name, url) in FEEDS.items():
        tasks[key] = (url, lambda raw, n=name, c=category: rss_records(raw, n, c, cutoff))
    for key, symbol in SYMBOLS.items():
        url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol) + '?range=10d&interval=1d'
        tasks[key] = (url, lambda raw, k=key: [yahoo(raw, k, cutoff)])
    twurl = 'https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX'

    def twse(raw):
        rows = json.loads(raw)
        row = next(x for x in rows if (x.get('指數') or x.get('Index')) == '發行量加權股價指數')
        value = row.get('日期') or row.get('Date')
        if not value:
            raise GateError('TWSE date field missing')
        digits = re.sub(r'\D', '', value)
        d = datetime(int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7]), 13, 30, tzinfo=TAIPEI)
        if not fresh(d, cutoff, 5):
            raise GateError('TWSE observation is stale or future')
        return [{'category': 'taiwan', 'publisher': 'TWSE', 'published_at': d.isoformat(),
                 'evidence': json.dumps(row, ensure_ascii=False), 'scope': 'Official previous Taiwan close'}]
    tasks['twse'] = (twurl, twse)

    def vix(raw):
        rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        valid = [(datetime.strptime(x['DATE'], '%m/%d/%Y').replace(hour=16, tzinfo=ZoneInfo('America/New_York')), x)
                 for x in rows]
        valid = [(d, x) for d, x in valid if d <= cutoff]
        d, row = valid[-1]
        if not fresh(d, cutoff, 5):
            raise GateError('CBOE VIX stale')
        return [{'category': 'risk', 'publisher': 'CBOE', 'published_at': d.isoformat(),
                 'evidence': f'VIX closing value on {d.date()}: {float(row["CLOSE"]):.2f}. '
                             'VIX measures option-implied expected volatility, not a directional prediction.',
                 'scope': 'Official daily VIX closing value'}]
    tasks['vix'] = ('https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv', vix)

    def calendar(raw):
        text = re.sub(r'\r?\n[ \t]', '', raw.decode('utf-8-sig'))
        events = []
        for block in text.split('BEGIN:VEVENT')[1:]:
            start = re.search(r'DTSTART([^:]*):([^\r\n]+)', block)
            title = re.search(r'SUMMARY:([^\r\n]+)', block)
            if not start or not title:
                continue
            value = start[2].strip()
            if value.endswith('Z'):
                d = datetime.strptime(value, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            else:
                zone = re.search(r'TZID=([^;:]+)', start[1])
                if not zone:
                    continue
                d = datetime.strptime(value, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(zone[1]))
            if d.astimezone(TAIPEI).date() == cutoff.date():
                events.append(f'{d.astimezone(TAIPEI).isoformat()}: {plain(title[1])}')
        # An empty verified calendar is evidence of no listed BLS event, not no global events.
        return [{'category': 'events', 'publisher': 'BLS schedule', 'published_at': cutoff.isoformat(),
                 'evidence': '\n'.join(events) if events else 'No BLS releases listed for this Taiwan calendar date. '
                 'This calendar does not cover all central bank, corporate or global events.',
                 'scope': 'BLS calendar only; use Taiwan time; no inference of unlisted events'}]
    tasks['calendar'] = ('https://www.bls.gov/schedule/news_release/bls.ics', calendar)
    # Independent official calendar fallback; do not treat a blocked calendar as an empty calendar.
    def fed_calendar(raw):
        body = raw.decode('utf-8')
        if 'id="article"' not in body or 'panel-body' not in body:
            raise GateError('Federal Reserve monthly calendar has no event body')
        events, recognized = [], 0
        for block in body.split('<div class="panel-body">')[1:]:
            cols = [re.search(r'<div class="col-xs-' + size + r'">(.*?)</div>', block, re.S)
                    for size in ['2', '7', '3']]
            if not all(cols):
                continue
            time_text, title, days = [plain(x[1]) for x in cols]
            clock = re.search(r'(\d{1,2}):(\d{2})\s*([ap])\.m\.', time_text, re.I)
            if not clock:
                continue
            recognized += 1
            hour = int(clock[1]) % 12 + (12 if clock[3].lower() == 'p' else 0)
            for day in re.findall(r'\b\d{1,2}\b', days):
                try:
                    dt = datetime(cutoff.year, cutoff.month, int(day), hour, int(clock[2]),
                                  tzinfo=ZoneInfo('America/New_York')).astimezone(TAIPEI)
                except ValueError:
                    continue
                if cutoff.date() <= dt.date() <= (cutoff + timedelta(days=1)).date():
                    events.append(dt.isoformat() + ': ' + title)
        if not recognized:
            raise GateError('Federal Reserve calendar time fields not recognized')
        text = '\n'.join(events) if events else 'No timed Federal Reserve calendar entries matched the target '
        if not events:
            text += 'Taiwan date and next date. Events without exact times were not included; '
            text += 'this is NOT evidence that no other events exist.'
        return [{'category': 'events', 'publisher': 'Federal Reserve official calendar',
                 'published_at': cutoff.isoformat(), 'evidence': text,
                 'scope': 'Calendar retrieved at cutoff, NOT publication timestamp. Only explicitly dated events '
                          'on the target Taiwan date may be called today; convert US Eastern time using DST. '
                          'Next-date events must be called tomorrow. Does not cover untimed events, corporate or all global events.'}]
    month_name = cutoff.strftime('%B').lower()
    tasks['fed_calendar'] = (f'https://www.federalreserve.gov/newsevents/{cutoff.year}-{month_name}.htm', fed_calendar)
    for series, label, max_age in [('DFF', 'Effective federal funds rate, percent (not the target range)', 10),
                                    ('DGS10', '10-year Treasury yield, percent', 10),
                                    ('CPIAUCSL', 'CPI all urban consumers, seasonally adjusted index', 65),
                                    ('PCEPILFE', 'Core PCE price index, seasonally adjusted index', 75)]:
        def fred(raw, s=series, label=label, age=max_age):
            text = raw.decode('utf-8-sig')
            if '<table' in text:
                pairs = re.findall(r'<th[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</th>\s*<td[^>]*>\s*([-\d.]+)\s*</td>', text)
                valid = [(datetime.fromisoformat(d).replace(tzinfo=TAIPEI), value)
                         for d, value in pairs if value not in ('.', '-')]
            else:
                rows = list(csv.DictReader(io.StringIO(text)))
                valid = [(datetime.fromisoformat(x.get('observation_date') or x.get('DATE')).replace(tzinfo=TAIPEI), x[s])
                         for x in rows if x.get(s) not in (None, '', '.')]
            valid = [(d, value) for d, value in valid if d <= cutoff]
            d, value = valid[-1]
            if not fresh(d, cutoff, age):
                raise GateError('Stale FRED observation: ' + s)
            return [{'category': 'macro', 'publisher': 'FRED / Federal Reserve Bank of St. Louis',
                     'published_at': cutoff.isoformat(), 'evidence': f'{s}: {label}. Latest observation period '
                     f'{d.date()}; value {value}. Observation date is NOT the announcement date. '
                     'Price index levels are NOT inflation percentages; no calculated inflation rate supplied.',
                     'scope': 'Retrieved at cutoff; observation is a period, not release timestamp; revisions possible.'}]
        tasks['fred_' + series] = (f'https://fred.stlouisfed.org/data/{series}.txt', fred)
    records, audit = [], []

    def run(key):
        url, parser = tasks[key]
        r = fetch_source(key, url)
        p = rawdir / (key + '.bin')
        items = parser(r.content)
        p.write_bytes(r.content)
        for index, item in enumerate(items):
            item.update(id=f'{key}-{index}', source_url=url, fetched_at=cutoff.isoformat(),
                        raw_file=p.name, raw_sha256=sha(p))
            item.setdefault('url', url)
        return items, {'source': key, 'status': 'OK', 'url': url, 'records': len(items), 'sha256': sha(p)}

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(run, key): key for key in tasks}
        for future in as_completed(futures):
            key = futures[future]
            try:
                items, result = future.result()
                records.extend(items)
                audit.append(result)
            except Exception as exc:
                cached = [r for r in previous['records'] if r['id'].rsplit('-', 1)[0] == key
                          and r.get('fetched_at', '')[:10] == cutoff.date().isoformat()
                          and (rawdir / r['raw_file']).exists()
                          and sha(rawdir / r['raw_file']) == r['raw_sha256']]
                if cached:
                    records.extend(cached)
                    audit.append({'source': key, 'status': 'CACHED_SAME_DAY', 'records': len(cached),
                                  'error': str(exc)[:250], 'original_fetched_at': cached[0]['fetched_at']})
                else:
                    audit.append({'source': key, 'status': 'FAILED', 'error': str(exc)[:250]})
    records.sort(key=lambda x: x['id'])
    bundle = {'cutoff': cutoff.isoformat(), 'records': records, 'audit': audit}
    save(work / 'sources.json', bundle)
    return bundle


def source_gate(bundle):
    records = bundle['records']
    categories = {r['category'] for r in records}
    required = {'market', 'taiwan', 'macro', 'tech', 'world', 'risk', 'events'}
    missing = sorted(required - categories)
    ids = {r['id'] for r in records}
    if not {'sp500-0', 'nasdaq-0'} <= ids:
        missing.append('US benchmarks')
    if not any(k in ids for k in ('nikkei-0', 'hsi-0', 'dax-0')):
        missing.append('global benchmark')
    if missing:
        raise GateError('SOURCE_GATE: missing ' + ', '.join(missing))


def verify_snapshots(bundle, work):
    for record in bundle['records']:
        path = work / 'raw' / record['raw_file']
        if path.name != record['raw_file'] or not path.exists() or sha(path) != record['raw_sha256']:
            raise GateError('SOURCE_GATE: raw snapshot missing or changed: ' + record['id'])
