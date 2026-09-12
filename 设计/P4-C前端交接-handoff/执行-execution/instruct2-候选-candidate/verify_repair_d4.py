"""Final verdict for the d4-repaired full paragraph: Qwen cases + identity + spot checks."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
sys.path.insert(0, str(EXEC))
from content_verify import compare, sha  # noqa: E402


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    plan = read(EXEC / 'frontend-dry-run.json')
    repair = read(HERE / 'repair-d4-request.json')
    candidate = read(HERE / 'instruct2-delivery-request.json')
    calibration = read(EXEC / 'asr-calibration.json')
    config = read(EXEC / 'qwen-tool-config.json')
    receipt = read(HERE / 'qwen-run-receipt-repair-d4.json')
    assert receipt['status'] == 'completed' and receipt['exit_code'] == 0
    out_dir = HERE / '独立核验-qwen-repair-d4'
    batch = read(out_dir / 'batch_summary.json')
    assert batch['total'] == 4 and batch['success'] == 4 and batch['failed'] == 0 and batch['model_device'].startswith('cuda')
    expected_map = {'repair_d4_full': plan['plain_text']}
    identities = {'repair_d4_full': repair['output']['sha256']}
    for case in calibration['cases']:
        expected_map[case['label']] = case['expected']
        identities[case['label']] = case['audio_sha256']
    cases = {}
    for name in ('repair_d4_full', 'human_reference_good', 'user_accepted_g1_good', 'known_bad_12j_sentence2'):
        paths = [out_dir / f'{name}.qwen3.{suffix}' for suffix in ('txt', 'json', 'report.md')]
        assert all(p.exists() and p.stat().st_size > 0 for p in paths), name
        result = read(paths[1])
        assert result['audio_sha256'].lower() == identities[name], f'{name} identity'
        runner = Path(config['runner_path'])
        assert result['tool_fingerprint'].lower() == sha(runner.with_name('transcribe_file.py')) + ':' + sha(runner)
        assert result['model_device'].startswith('cuda') and result['status'] == 'candidate'
        assert result['text'] == paths[0].read_text(encoding='utf-8').strip()
        cases[name] = {'comparison': compare(expected_map[name], [{'text': result['text']}]),
                       'raw_json_sha256': sha(paths[1])}
    assert cases['known_bad_12j_sentence2']['comparison']['exit_code'] != 0, 'bad sample missed'
    normal_fp = sum(cases[n]['comparison']['exit_code'] != 0 for n in ('human_reference_good', 'user_accepted_g1_good'))
    assert normal_fp == 0, f'false positives: {normal_fp}'
    content = cases['repair_d4_full']['comparison']
    # unchanged blocks identity check
    unchanged_ok = all(sha(HERE / candidate['calls'][i - 1]['output']['filename']) == candidate['calls'][i - 1]['output']['sha256'] for i in (1, 2, 4, 5, 6))
    assert unchanged_ok
    summary = {'schema_version': 'p4-repair-d4-result.v1', 'request_id': repair['request_id'],
               'qwen_batch': {'total': batch['total'], 'success': batch['success'], 'device': batch['model_device']},
               'normal_false_positives': normal_fp, 'known_bad_false_negatives': 0,
               'repaired_full': {'exit_code': content['exit_code'], 'level': content['level'],
                                 'differences': content['differences'],
                                 'excess_repetition_spans': content['excess_repetition_spans'],
                                 'detail_json_sha256': cases['repair_d4_full']['raw_json_sha256']},
               'unchanged_blocks_bytes_identical': unchanged_ok,
               'protocol01': read(HERE / 'asr-repair-d4.json')['comparison']['exit_code'],
               'level': content['level'], 'exit_code': content['exit_code'], 'unresolved': content['differences']}
    write(HERE / 'repair-d4-result.json', summary)
    print(json.dumps({'level': summary['level'], 'exit_code': summary['exit_code'],
                      'differences': len(summary['unresolved']),
                      'repetitions': len(content['excess_repetition_spans']),
                      'qwen_fp': normal_fp}, ensure_ascii=False))


if __name__ == '__main__':
    main()
