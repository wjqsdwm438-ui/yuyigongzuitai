"""Instruct2 candidate verification: frozen-tool identities, Qwen independent content evidence, pause metrics vs baseline."""
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
BASELINE_WAV = EXEC / '0c9fbfbd47d44e2bbdd0a45049dd0f3b-完整第一自然段-full-paragraph.wav'
sys.path.insert(0, str(EXEC))
from content_verify import compare, normalize, sha  # noqa: E402

PHRASES = ['大数据工具实操', '业财融合', '企业真实场景实战', '管理会计实务', '数据赋能经营', '企业全链条业务场景']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def silence_runs(path, threshold_db=-38, min_dur=0.18):
    pcm, sr = sf.read(path, dtype='float32')
    if pcm.ndim > 1:
        pcm = pcm.mean(axis=1)
    win = int(0.025 * sr)
    hop = int(0.01 * sr)
    frames = np.lib.stride_tricks.sliding_window_view(pcm, win)[::hop]
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms / (rms.max() + 1e-12) + 1e-12)
    sil = db < threshold_db
    runs = []
    i = 0
    while i < len(sil):
        if sil[i]:
            j = i
            while j < len(sil) and sil[j]:
                j += 1
            dur = (j - i) * hop / sr
            if dur >= min_dur:
                runs.append(round(dur, 2))
            i = j
        else:
            i += 1
    return len(pcm) / sr, runs


def word_gap_report(asr, expected, phrases):
    words = []
    for seg in asr['raw_segments']:
        words.extend(seg.get('words') or [])
    words.sort(key=lambda w: w['start'])
    norm_chars = []
    char_word = []
    for wi, w in enumerate(words):
        for ch in normalize(w['word']):
            norm_chars.append(ch)
            char_word.append(wi)
    norm_transcript = ''.join(norm_chars)
    norm_expected = normalize(expected)
    sm = SequenceMatcher(None, norm_expected, norm_transcript, autojunk=False)
    report = {}
    for phrase in phrases:
        nphrase = normalize(phrase)
        hits = []
        start = norm_expected.find(nphrase)
        while start != -1:
            end = start + len(nphrase)
            entry = {}
            for m in sm.get_matching_blocks():
                if m.a <= start < m.a + m.size:
                    t_a = m.b + (start - m.a)
                    t_b = t_a + min(m.size - (start - m.a), len(nphrase))
                    if t_b > t_a and t_b <= len(char_word):
                        w_a, w_b = char_word[t_a], char_word[t_b - 1]
                        entry['time'] = [round(words[w_a]['start'], 2), round(words[w_b]['end'], 2)]
                        gaps = []
                        for i in range(w_a, w_b):
                            g = words[i + 1]['start'] - words[i]['end']
                            if g >= 0.12:
                                gaps.append({'gap': round(g, 3), 'at': round(words[i]['end'], 2),
                                             'after': words[i]['word'], 'before': words[i + 1]['word']})
                        entry['internal_gaps'] = gaps
                        entry['internal_gap_ge_025'] = sum(1 for g in gaps if g['gap'] >= 0.25)
                    break
            hits.append(entry)
            start = norm_expected.find(nphrase, start + 1)
        report[phrase] = hits
    gaps_all = []
    for i in range(len(words) - 1):
        g = words[i + 1]['start'] - words[i]['end']
        if g >= 0.3:
            gaps_all.append({'gap': round(g, 3), 'at': round(words[i]['end'], 2),
                             'after': words[i]['word'], 'before': words[i + 1]['word']})
    gaps_all.sort(key=lambda x: -x['gap'])
    return report, gaps_all


def main():
    plan = read(EXEC / 'frontend-dry-run.json')
    request = read(HERE / 'instruct2-delivery-request.json')
    assert request['status'] == 'success', 'candidate delivery not successful'
    summary = {'schema_version': 'p4-instruct2-result.v1', 'request_id': request['request_id'],
               'checks': {}, 'unresolved': []}
    full = HERE / request['output']['filename']
    assert sha(full) == request['output']['sha256'], 'candidate audio hash mismatch'
    # 1. Qwen wrapper/runner/model identity
    config = read(EXEC / 'qwen-tool-config.json')
    assert sha(config['wrapper_path']) == config['wrapper_sha256']
    assert sha(config['runner_path']) == config['runner_sha256']
    for mf in config['model_files']:
        assert sha(mf['path']) == mf['sha256'], 'Qwen model file changed'
    receipt = read(HERE / 'qwen-run-receipt-instruct2.json')
    assert receipt['status'] in ('completed', 'failed'), 'wrapper did not finish'
    batch = read(HERE / '独立核验-qwen/batch_summary.json')
    assert batch['total'] == 4 and batch['cached'] == 0 and batch['success'] == 4 and batch['failed'] == 0
    assert batch['model_device'].startswith('cuda')
    summary['checks']['qwen_batch'] = {'total': batch['total'], 'success': batch['success'], 'device': batch['model_device'],
                                       'elapsed_seconds': batch['elapsed_seconds'],
                                       'external_exit_note': receipt.get('observation_note')}
    # 2. Per-case identity + comparisons
    calibration = read(EXEC / 'asr-calibration.json')
    expected_map = {'instruct2_full': plan['plain_text']}
    identities = {'instruct2_full': request['output']['sha256']}
    for case in calibration['cases']:
        expected_map[case['label']] = case['expected']
        identities[case['label']] = case['audio_sha256']
    out_dir = HERE / '独立核验-qwen'
    cases = {}
    for name in ('instruct2_full', 'human_reference_good', 'user_accepted_g1_good', 'known_bad_12j_sentence2'):
        paths = [out_dir / f'{name}.qwen3.{suffix}' for suffix in ('txt', 'json', 'report.md')]
        assert all(p.exists() and p.stat().st_size > 0 for p in paths), f'missing Qwen output for {name}'
        result = read(paths[1])
        assert result['audio_sha256'].lower() == identities[name], f'{name} audio identity mismatch'
        runner = Path(config['runner_path'])
        assert result['tool_fingerprint'].lower() == sha(runner.with_name('transcribe_file.py')) + ':' + sha(runner), 'Qwen source fingerprint changed'
        assert result['model_device'].startswith('cuda') and result['backend'] == 'transformers'
        assert result['language'] == 'Chinese' and result['max_new_tokens'] == 1024
        assert result['ok'] and result['status'] == 'candidate'
        assert result['text'] == paths[0].read_text(encoding='utf-8').strip()
        cases[name] = {'audio_sha256': result['audio_sha256'], 'raw_json': str(paths[1]),
                       'raw_json_sha256': sha(paths[1]), 'text': result['text'],
                       'comparison': compare(expected_map[name], [{'text': result['text']}])}
    assert cases['known_bad_12j_sentence2']['comparison']['exit_code'] != 0, 'Qwen missed the known bad sample'
    normal_fp = sum(cases[n]['comparison']['exit_code'] != 0 for n in ('human_reference_good', 'user_accepted_g1_good'))
    assert normal_fp == 0, f'Qwen false positives on good samples: {normal_fp}'
    content = cases['instruct2_full']['comparison']
    summary['checks']['qwen_cases'] = {
        'normal_false_positives': normal_fp, 'known_bad_false_negatives': 0,
        'instruct2_full': {'exit_code': content['exit_code'], 'level': content['level'],
                           'differences': content['differences'],
                           'excess_repetition_spans': content['excess_repetition_spans'],
                           'detail_json_sha256': cases['instruct2_full']['raw_json_sha256']}}
    # 3. Protocol-01 replay from stored whisper words (frozen tool)
    asr = read(HERE / 'asr-instruct2.json')
    assert asr['audio_sha256'] == request['output']['sha256'] and asr['expected'] == plan['plain_text']
    replay = compare(plan['plain_text'], asr['raw_segments'])
    summary['checks']['protocol01_content'] = {'level': replay['level'], 'exit_code': replay['exit_code'],
                                               'differences': len(replay['differences']),
                                               'excess_repetition_spans': len(replay['excess_repetition_spans']),
                                               'note': 'replayed from stored raw_segments with frozen tool; known 2/2 FP tool'}
    # 4. Pause metrics candidate vs baseline
    cand_dur, cand_sil = silence_runs(full)
    base_dur, base_sil = silence_runs(BASELINE_WAV)
    phrase_report, gaps_all = word_gap_report(asr, plan['plain_text'], PHRASES)
    intra_total = sum(h.get('internal_gap_ge_025', 0) for hits in phrase_report.values() for h in hits)
    summary['rhythm'] = {
        'baseline_seconds': base_dur, 'candidate_seconds': cand_dur,
        'baseline_pauses_ge_018': len(base_sil), 'candidate_pauses_ge_018': len(cand_sil),
        'baseline_pause_rate_per_min': round(len(base_sil) / base_dur * 60, 1),
        'candidate_pause_rate_per_min': round(len(cand_sil) / cand_dur * 60, 1),
        'baseline_pause_seconds_total': round(sum(base_sil), 2), 'candidate_pause_seconds_total': round(sum(cand_sil), 2),
        'intra_phrase_gaps_ge_025_total': intra_total,
        'phrase_report': phrase_report,
        'top_gaps_candidate': gaps_all[:20],
    }
    summary['checks']['identity_and_outputs'] = '通过：候选/参考/校准样本身份与工具指纹一致，4/4 Qwen成功(cuda)'
    summary['level'] = content['level']
    summary['exit_code'] = content['exit_code']
    summary['unresolved'] = content['differences']
    write(HERE / 'instruct2-结果-result.json', summary)
    print(json.dumps({'level': summary['level'], 'exit_code': summary['exit_code'],
                      'candidate_seconds': cand_dur, 'baseline_seconds': base_dur,
                      'candidate_pause_rate': summary['rhythm']['candidate_pause_rate_per_min'],
                      'baseline_pause_rate': summary['rhythm']['baseline_pause_rate_per_min'],
                      'intra_phrase_gaps_ge_025': intra_total}, ensure_ascii=False))


if __name__ == '__main__':
    main()
