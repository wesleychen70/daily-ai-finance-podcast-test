import argparse
import json
import os
import sys
from pathlib import Path

from .audio import synthesize
from .common import GateError, load_env, now, save, sha
from .editorial import create_script, transcript, validate_script, verify_script
from .gemini import Gemini
from .sources import collect, source_gate, verify_snapshots


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['collect', 'generate', 'publish', 'preflight'])
    parser.add_argument('--work', default='build/' + now().date().isoformat())
    args = parser.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == 'preflight':
            print(Gemini(work).json('Return JSON {"ok":true,"message":"繁體中文測試"}'))
            return
        if args.command == 'publish':
            from .publish import publish
            publish(work, os.environ.get('GITHUB_REPOSITORY'), os.environ.get('PAGES_BASE_URL'),
                    os.environ.get('FALLBACK_MEDIA_BASE', ''))
            return
        sources_path = work / 'sources.json'
        if args.command == 'collect' or not sources_path.exists():
            bundle = collect(work)
        else:
            bundle = json.loads(sources_path.read_text(encoding='utf-8'))
        source_gate(bundle)
        verify_snapshots(bundle, work)
        print(f'Source gate passed: {len(bundle["records"])} evidence records', flush=True)
        if args.command == 'collect':
            return
        # Sources older than today's bundle cannot be recycled as a new daily episode.
        if bundle['cutoff'][:10] != now().date().isoformat():
            raise GateError('Source bundle belongs to another Taiwan date')
        gemini = Gemini(work)
        corrections = None
        for editorial_attempt in range(2):
            script = create_script(gemini, bundle, work, corrections)
            try:
                verify_script(gemini, script, bundle, work)
                break
            except GateError:
                if editorial_attempt == 1:
                    raise
                corrections = json.loads((work / 'editorial-check.json').read_text(encoding='utf-8'))['issues']
                # Preserve rejected drafts; the next attempt must be freshly reviewed, not downgraded.
                for path in [work / 'script.json', *[work / f'section-{i}.json' for i in range(6)]]:
                    path.replace(path.with_suffix('.rejected.json'))
        (work / 'transcript.txt').write_text(transcript(script), encoding='utf-8')
        audio = synthesize(gemini, script, work)
        manifest = {'status': 'VERIFIED_TEST', 'date': now().date().isoformat(),
                    'guid': 'urn:daily-ai-finance:test:' + now().date().isoformat(),
                    'title': script['title'], 'published_at': now().isoformat(),
                    'description': 'AI 自動生成測試節目。資料截止：' + bundle['cutoff'] + '。非投資建議。',
                    'bytes': audio['bytes'], 'sha256': audio['sha256'], 'duration': audio['duration'],
                    'files': {name: sha(work / name) for name in
                              ['script.json', 'sources.json', 'transcript.txt', 'editorial-check.json', 'audio-check.json']}}
        save(work / 'manifest.json', manifest)
        save(work / 'status.json', {'status': 'VERIFIED_TEST', 'human_listening': 'NOT_RUN'})
        print('Verified test MP3: ' + str(work / 'episode.mp3'))
    except Exception as exc:
        # No exception locals, headers, raw provider responses, or secrets in logs.
        message = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        save(work / 'status.json', {'status': 'BLOCKED', 'error': message, 'time': now().isoformat()})
        print('BLOCKED: ' + message, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
