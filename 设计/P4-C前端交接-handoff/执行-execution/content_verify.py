"""Offline whole-audio transcription and strict, replayable content comparison."""
import argparse
from collections import Counter
import ctypes
from difflib import SequenceMatcher
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
import unicodedata

HERE = Path(__file__).resolve().parent
MODEL = Path('D:/hf_models/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120')
PARAMETERS = dict(language='zh', task='transcribe', beam_size=1, best_of=1, temperature=0,
                  condition_on_previous_text=False, vad_filter=False, word_timestamps=True)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def normalize(text):
    # Windows' installed locale tables avoid adding a conversion dependency.
    text = unicodedata.normalize('NFKC', text)
    convert = ctypes.windll.kernel32.LCMapStringEx
    length = convert('zh-CN', 0x02000000, text, len(text), None, 0, None, None, 0)
    if length <= 0:
        if not text:
            return ''
        raise ctypes.WinError()
    buffer = ctypes.create_unicode_buffer(length)
    if convert('zh-CN', 0x02000000, text, len(text), buffer, length, None, None, 0) <= 0:
        raise ctypes.WinError()
    return ''.join(c for c in buffer[:length] if not c.isspace() and not unicodedata.category(c).startswith('P'))


def compare(expected, rows):
    actual = ''.join(row['text'] for row in rows)
    left, right = normalize(expected), normalize(actual)
    differences = [{'operation': op, 'expected_span': [a, b], 'transcript_span': [x, y],
                    'expected': left[a:b], 'observed': right[x:y]}
                   for op, a, b, x, y in SequenceMatcher(None, left, right, autojunk=False).get_opcodes()
                   if op != 'equal']
    source_english = Counter(re.findall('[A-Za-z]{2,}', left))
    found_english = Counter(re.findall('[A-Za-z]{2,}', right))
    unexpected_english = dict(found_english - source_english)
    repeated = []
    for n in range(4, 13):
        source = Counter(left[i:i+n] for i in range(len(left) - n + 1))
        observed = Counter(right[i:i+n] for i in range(len(right) - n + 1))
        for phrase, count in observed.items():
            if count >= 2 and count > source[phrase]:
                for match in re.finditer('(?=' + re.escape(phrase) + ')', right):
                    repeated.append([match.start(), match.start() + n])
    merged = []
    for a, b in sorted(repeated):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    locations, position = [], 0
    for row in rows:
        width = len(normalize(row['text']))
        words = row.get('words', [])
        if words and ''.join(normalize(w['word']) for w in words) == normalize(row['text']):
            for word in words:
                size = len(normalize(word['word']))
                locations.append((position, position + size, word['start'], word['end'], 'ASR词级候选'))
                position += size
        else:
            locations.append((position, position + width, row.get('start'), row.get('end'), 'ASR分段候选'))
            position += width
    def locate(span):
        a, b = span
        selected = [loc for loc in locations if loc[0] < max(b, a + 1) and a < loc[1] and loc[2] is not None]
        return {'seconds': [min(x[2] for x in selected), max(x[3] for x in selected)],
                'basis': sorted({x[4] for x in selected})} if selected else None
    for difference in differences:
        difference['time_location'] = locate(difference['transcript_span'])
    return {'level': '通过' if rows and not differences and not unexpected_english and not merged else '嫌疑',
            'exit_code': 0 if rows and not differences and not unexpected_english and not merged else 2,
            'normalized_expected': left, 'normalized_transcript': right, 'differences': differences,
            'unexpected_english': unexpected_english, 'excess_repetition_spans': merged,
            'excess_repetition_time_locations': [locate(span) for span in merged]}


def self_check():
    def check(source, observed):
        return compare(source, [{'text': observed}])['exit_code']
    assert check('企业全链条业务', '企業全鏈條業務。') == 0
    assert check('APP APP，复核之后再复核', 'APP APP复核之后再复核') == 0
    assert check('可以分析', '不可以分析') == 2
    assert check('15%', '50%') == 2
    assert check('原有APP', '原有API') == 2
    assert check('企业全链条业务', '企业全链条业务Tapi企业全链条业务') == 2
    assert check('没有重复', '') == 2


def transcribe(model, path, expected, label):
    import soundfile as sf
    start = time.monotonic()
    segments, info = model.transcribe(str(path), **PARAMETERS)
    rows = [{'start': segment.start, 'end': segment.end, 'text': segment.text,
             'words': [{'start': word.start, 'end': word.end, 'word': word.word, 'probability': word.probability}
                       for word in segment.words or []]} for segment in segments]
    audio_info = sf.info(path)
    assert rows and abs(info.duration - audio_info.duration) < 0.1
    return {'label': label, 'audio_path': str(path), 'audio_sha256': sha(path),
            'audio_seconds': audio_info.duration, 'expected': expected,
            'expected_sha256': hashlib.sha256(expected.encode('utf-8')).hexdigest(),
            'processed_full_file': True, 'asr_duration': info.duration, 'raw_segments': rows,
            'comparison': compare(expected, rows), 'elapsed_seconds': round(time.monotonic() - start, 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['calibrate', 'delivery', 'self-check'])
    args = parser.parse_args()
    self_check()
    if args.mode == 'self-check':
        print('strict comparison checks: passed')
        return
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    from faster_whisper import WhisperModel
    from p4_delivery import REFERENCE, PAIR, READY, read as load
    tool = {'model': str(MODEL), 'model_sha256': sha(MODEL / 'model.bin'),
            'faster_whisper_version': importlib.metadata.version('faster-whisper'),
            'ctranslate2_version': importlib.metadata.version('ctranslate2'),
            'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 8, 'num_workers': 1,
            'parameters': PARAMETERS, 'normalization': {'nfkc_unicode': unicodedata.unidata_version,
            'traditional_conversion': 'Windows LCMapStringEx zh-CN LCMAP_SIMPLIFIED_CHINESE',
            'windows_version': platform.version(), 'punctuation': 'Unicode P* categories only',
            'homophone_tolerance': 0, 'case_folding': False}, 'timeout_seconds_per_process': 180}
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True, cpu_threads=8, num_workers=1)
    if args.mode == 'calibrate':
        if (HERE / 'asr-calibration.json').exists():
            raise RuntimeError('protocol01 calibration is frozen; parameter changes require a new dispatch/protocol')
        trial = HERE.parent / '稀疏修订-sparse/paragraph-sentence-trial'
        groups = load(READY)
        cases = [transcribe(model, REFERENCE, PAIR.read_text(encoding='utf-8').strip(), 'human_reference_good'),
                 transcribe(model, HERE.parent / '课程02-course02/g1-actual-cca46a55ed6945759505b4fc57209620.wav', groups[0]['plain_text'], 'user_accepted_g1_good'),
                 transcribe(model, trial / 'cad9009aff9c46ae95f9ea753f276bf5-sentence-2.wav', ''.join(g['plain_text'] for g in groups[3:7]), 'known_bad_12j_sentence2')]
        write(HERE / 'asr-calibration.json', {'tool': tool, 'cases': cases,
              'comparison_fixture_checks': 'passed; original English/repetition retained, added English/repetition/digits/negation rejected',
              'false_positive_count': sum(c['comparison']['exit_code'] != 0 for c in cases[:2]),
              'false_negative_count': int(cases[2]['comparison']['exit_code'] == 0),
              'scope': '两份有来源依据的正常音频、一份已知坏音频；英文/原有重复是比较器文本对照，未覆盖真实英文音频。'})
        print(json.dumps([{ 'label': c['label'], 'level': c['comparison']['level'], 'differences': c['comparison']['differences']} for c in cases], ensure_ascii=False))
    else:
        plan = load(HERE / 'frontend-dry-run.json')
        request = load(HERE / 'delivery-request.json')
        path = HERE / request['output']['filename']
        result = transcribe(model, path, plan['plain_text'], 'new_full_delivery')
        result['tool'] = tool
        write(HERE / 'asr-delivery.json', result)
        print(json.dumps(result['comparison'], ensure_ascii=False))
        raise SystemExit(result['comparison']['exit_code'])


if __name__ == '__main__':
    main()
