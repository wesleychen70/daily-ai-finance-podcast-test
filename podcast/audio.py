import json
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from .common import GateError, save, sha
from .editorial import audio_similarity


def ffmpeg(*args):
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-nostdin', *map(str, args)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    if result.returncode:
        raise GateError('AUDIO_GATE: ffmpeg failed: ' + result.stderr[-600:])
    return result.stderr


def duration(path):
    text = ffmpeg('-i', path, '-f', 'null', '-')
    match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', text)
    if not match:
        raise GateError('AUDIO_GATE: cannot read duration')
    return int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])


def chunks(script):
    out = []
    for section in script['sections']:
        text = '\n\n'.join(p['text'] for p in section['paragraphs'])
        if len(text) <= 1400:
            out.append(text)
            continue
        sentences = re.split(r'(?<=[。！？])', text)
        current = ''
        for sentence in sentences:
            if len(current) + len(sentence) > 1000 and current:
                out.append(current)
                current = ''
            current += sentence
        if current:
            out.append(current)
    if len(out) > 12:
        raise GateError('AUDIO_GATE: too many chunks for daily budget')
    return out


def synthesize(gemini, script, work):
    directory = work / 'chunks'
    directory.mkdir(exist_ok=True)
    paths, reports = [], []
    for i, text in enumerate(chunks(script)):
        name = directory / f'{i:02d}'
        wav = name.with_suffix('.wav')
        mp3 = name.with_suffix('.mp3')
        report_path = name.with_suffix('.json')
        import hashlib
        text_sha = hashlib.sha256(text.encode()).hexdigest()
        if report_path.exists() and mp3.exists():
            report = json.loads(report_path.read_text(encoding='utf-8'))
            if report.get('text_sha256') == text_sha and report.get('sha256') == sha(mp3) and report.get('approved') is True:
                paths.append(mp3)
                reports.append(report)
                continue
        if not wav.exists():
            gemini.speech(text, wav)
        ffmpeg('-y', '-i', wav, '-ar', '44100', '-ac', '1', '-codec:a', 'libmp3lame', '-b:a', '128k', mp3)
        length = duration(mp3)
        if length < 10 or length > 300:
            raise GateError('AUDIO_GATE: abnormal segment duration')
        report = gemini.json('''請實際聽取所附音訊，逐字轉錄成繁體中文。不要根據猜測補字。
金融數值、日期、時間請使用阿拉伯數字，保留小數與正負，不要補入音訊未說出的資訊。
評估是否有漏讀、加話、截斷、長段靜音、非中文、朗讀指令或音訊異常。
回傳JSON {"transcript":"實際聽到的內容","approved":true或false,"issues":[],
"taiwan_mandarin":true或false}。音色自然與台灣口音也必須合格才能批准。''', audio=mp3)
        similarity = audio_similarity(text, report.get('transcript', ''))
        report.update(similarity=similarity, duration=length, sha256=sha(mp3), text_sha256=text_sha)
        save(report_path, report)
        if report.get('approved') is not True or report.get('issues') != [] or report.get('taiwan_mandarin') is not True or similarity < .93:
            # A backup run must regenerate rejected audio rather than reusing it indefinitely.
            wav.unlink(missing_ok=True)
            mp3.unlink(missing_ok=True)
            raise GateError(f'AUDIO_GATE: segment {i} failed automatic listening verification')
        reports.append(report)
        paths.append(mp3)
        print(f'Validated speech segment {i + 1}: {length:.1f}s', flush=True)
    listing = directory / 'concat.txt'
    listing.write_text('\n'.join("file '" + p.name + "'" for p in paths), encoding='utf-8')
    joined = work / 'joined.mp3'
    ffmpeg('-y', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', joined)
    output = work / 'episode.mp3'
    original_length = duration(joined)
    tempo = max(.85, min(1.15, original_length / 1200))
    ffmpeg('-y', '-i', joined, '-af', f'atempo={tempo:.6f},loudnorm=I=-16:TP=-1.5:LRA=11',
           '-ar', '44100', '-ac', '1', '-codec:a', 'libmp3lame', '-b:a', '128k', output)
    length = duration(output)
    if not 1080 <= length <= 1380:
        raise GateError(f'AUDIO_GATE: expected 18-23 minutes, got {length / 60:.2f}')
    report = {'status': 'AUTOMATIC_CHECKS_PASSED', 'human_listening': 'NOT_RUN',
              'duration': length, 'sha256': sha(output), 'bytes': output.stat().st_size,
              'original_duration': original_length, 'tempo_factor': tempo,
              'segments': reports, 'limitation': 'Model-assisted checks cannot guarantee factual or accent perfection.'}
    save(work / 'audio-check.json', report)
    return report
