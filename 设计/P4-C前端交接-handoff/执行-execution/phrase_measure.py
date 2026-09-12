"""Fixed CPU word timestamps + PCM RMS evidence; never judges pronunciation."""
import argparse
from difflib import SequenceMatcher
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import wave

import numpy as np
from content_verify import MODEL, PARAMETERS, normalize, sha, read, write

HERE = Path(__file__).resolve().parent
OUT = HERE / '词组连续-trial04'
CONFIG = {'frame_ms': 20, 'hop_ms': 10, 'rms_dbfs': -40, 'minimum_run_ms': 50,
          'endpoint_grid_error_ms': 20, 'alignment_sensitivity_ms': 120,
          'word_flag_seconds': .25, 'enumeration_flag_seconds': .35,
          'alignment': 'faster-whisper-small word_timestamps; no character-time interpolation',
          'alignment_error': 'No independent timing ground truth; 120ms is a sensitivity guard, not validated accuracy.',
          'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 8, 'num_workers': 1,
          'parameters': PARAMETERS}


def pcm(path):
    with wave.open(str(path), 'rb') as f:
        assert f.getnchannels() == 1 and f.getsampwidth() == 2
        rate = f.getframerate()
        return np.frombuffer(f.readframes(f.getnframes()), dtype='<i2').astype(float) / 32768, rate


def low_runs(path):
    samples, rate = pcm(path)
    frame, hop = int(rate * .02), int(rate * .01)
    energy = np.array([np.sqrt(np.mean(samples[i:i + frame] ** 2))
                       for i in range(0, len(samples) - frame + 1, hop)])
    low = 20 * np.log10(np.maximum(energy, 1e-12)) < CONFIG['rms_dbfs']
    edges = np.diff(np.r_[False, low, False].astype(int))
    return [[round(float(a * hop / rate), 5), round(float((b - 1) * hop / rate + frame / rate), 5)]
            for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))
            if (b - a - 1) * hop / rate + frame / rate >= .05]


def locate(expected, rows):
    words, actual = [], ''
    for row in rows:
        for word in row['words']:
            text = normalize(word['word'])
            if text:
                words.append((len(actual), len(actual) + len(text), word))
                actual += text
    source = normalize(expected)
    mapping = {}
    uncertain = []
    for op, a, b, x, y in SequenceMatcher(None, source, actual, autojunk=False).get_opcodes():
        if op == 'equal' or (op == 'replace' and b - a == y - x):
            for i, j in zip(range(a, b), range(x, y)):
                mapping[i] = j
            if op != 'equal':
                uncertain.append([a, b, source[a:b], actual[x:y]])
    def span(a, b):
        if a >= b:
            return None
        if any(i not in mapping for i in range(a, b)):
            return None
        ids = [mapping[i] for i in range(a, b)]
        if ids != list(range(min(ids), max(ids) + 1)):
            return None
        selected = [w for x, y, w in words if x <= max(ids) and min(ids) < y]
        if not selected or any(w['end'] <= w['start'] for w in (selected[0], selected[-1])):
            return None
        return [selected[0]['start'], selected[-1]['end']]
    targets = []
    for phrase in ('大数据工具实操', '业财融合', '企业真实场景实战', '业财融合思维塑造'):
        assert source.count(phrase) == 1
        a = source.index(phrase)
        targets.append({'text': phrase, 'normalized_span': [a, a + len(phrase)], 'seconds': span(a, a + len(phrase)),
                        'substitution_uncertainty': [u for u in uncertain if u[0] < a + len(phrase) and a < u[1]]})
    boundaries = []
    position = 0
    for c in expected:
        if c in '，、。':
            before, after = span(max(0, position - 1), position), span(position, min(len(source), position + 1))
            boundaries.append({'punctuation': c, 'normalized_offset': position,
                               'before': before, 'after': after})
        position += len(normalize(c))
    return targets, boundaries


def measure(path, expected, rows):
    samples, rate = pcm(path)
    runs = low_runs(path)
    targets, boundaries = locate(expected, rows)
    for t in targets:
        t['low_energy_intervals'] = [] if t['seconds'] is None else [r for r in runs if t['seconds'][0] < r[0] and r[1] < t['seconds'][1]]
        durations = [b - a for a, b in t['low_energy_intervals']]
        t.update(count=len(durations), total_seconds=round(sum(durations), 5), maximum_seconds=round(max(durations, default=0), 5),
                 flags_ge_025=sum(d >= .25 for d in durations))
        t['robust_to_120ms_edge_guard'] = [] if t['seconds'] is None else [r for r in t['low_energy_intervals'] if t['seconds'][0] + .12 < r[0] and r[1] < t['seconds'][1] - .12]
    for b in boundaries:
        if b['before'] and b['after']:
            b['low_energy_intervals'] = [r for r in runs if b['before'][0] <= sum(r) / 2 <= b['after'][1]]
            b['maximum_seconds'] = round(max((y-x for x, y in b['low_energy_intervals']), default=0), 5)
        else:
            b['low_energy_intervals'] = None
            b['maximum_seconds'] = None
    return {'audio_path': str(path), 'audio_sha256': sha(path), 'sample_rate': rate, 'frames': len(samples),
            'seconds': len(samples) / rate, 'added_tail_seconds': .2,
            'characters_per_second_excluding_tail': len(normalize(expected)) / (len(samples) / rate - .2),
            'targets': targets, 'boundaries': boundaries, 'all_low_energy_intervals': runs,
            'localization_complete': all(t['seconds'] for t in targets),
            'effect_conclusion': '证据不足：声学低能量与ASR时间候选，缺独立端点真值及用户听审，不代判韵律。'}


def run(mode):
    from faster_whisper import WhisperModel
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    OUT.mkdir(exist_ok=True)
    plan = read(HERE / 'frontend-dry-run.json')
    block, = [b for b in plan['blocks'] if b['index'] == 5]
    config = {**CONFIG, 'python': sys.executable, 'model': str(MODEL), 'model_sha256': sha(MODEL / 'model.bin'),
              'faster_whisper': importlib.metadata.version('faster-whisper'),
              'ctranslate2': importlib.metadata.version('ctranslate2'), 'numpy': np.__version__,
              'measurement_source_sha256': sha(__file__)}
    if mode == 'baseline':
        assert not (OUT / 'measurement-preregistered.json').exists()
        write(OUT / 'measurement-preregistered.json', config)
        paths = [('baseline', HERE / '0c9fbfbd47d44e2bbdd0a45049dd0f3b-block-5.wav')]
    else:
        assert config == read(OUT / 'measurement-preregistered.json'), 'measurement parameters changed'
        paths = [(p.stem, Path(read(p)['output']['path'])) for p in sorted(OUT.glob('[AB][01].json')) if read(p).get('output')]
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', cpu_threads=8, num_workers=1, local_files_only=True)
    for name, path in paths:
        dest = OUT / f'{name}-measurement.json'
        assert not dest.exists(), 'measurement already attempted'
        segments, info = model.transcribe(str(path), **PARAMETERS)
        rows = [{'start': s.start, 'end': s.end, 'text': s.text,
                 'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'probability': w.probability} for w in s.words or []]} for s in segments]
        write(OUT / f'{name}-timing-raw.json', {'audio_sha256': sha(path), 'raw_segments': rows, 'duration': info.duration})
        result = measure(path, block['plain_text'], rows)
        assert abs(info.duration - result['seconds']) < .1
        write(dest, {**result, 'raw_segments': rows, 'processed_full_file': True,
                     'config_sha256': sha(OUT / 'measurement-preregistered.json')})
        print(json.dumps({'item': name, 'localized': result['localization_complete'], 'seconds': result['seconds']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['baseline', 'outputs'])
    run(parser.parse_args().mode)
