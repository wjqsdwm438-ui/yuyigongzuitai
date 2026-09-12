"""Run current-input gates without synthesizing or trusting cached pass flags."""
import hashlib
import contextlib
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

from p4_delivery import HERE, TTS, READY, READINGS, INPUT, REFERENCE, PAIR, sha, read, write
from p4_delivery import setup, blocked, frontend, make_plan, source_versions, input_identity
from content_verify import compare, self_check


def independent_content(plan, calibration, first_asr):
    def load(path):
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    from difflib import SequenceMatcher
    from content_verify import normalize
    receipt = load(HERE / 'qwen-run-receipt.json')
    config = load(HERE / 'qwen-tool-config.json')
    inputs = load(HERE / 'qwen-inputs.json')
    if receipt['status'] != 'completed' or receipt['exit_code'] != 0:
        raise RuntimeError(f"Qwen wrapper did not complete: {receipt['status']}, exit={receipt['exit_code']}")
    assert sha(config['wrapper_path']) == config['wrapper_sha256']
    assert sha(config['runner_path']) == config['runner_sha256']
    for model_file in config['model_files']:
        assert sha(model_file['path']) == model_file['sha256'], 'Qwen model file identity changed'
    out = HERE / '独立核验-qwen'
    batch = load(out / 'batch_summary.json')
    assert batch['total'] == 4 and batch['cached'] == 0 and batch['success'] == 4 and batch['failed'] == 0
    assert batch['model_device'].startswith('cuda')
    expected = {'current_full': plan['plain_text'], **{c['label']: c['expected'] for c in calibration['cases']}}
    identities = {'current_full': read(HERE / 'delivery-request.json')['output']['sha256'],
                  **{c['label']: c['audio_sha256'] for c in calibration['cases']}}
    assert len(inputs) == 4 and {item['role'] for item in inputs} == set(expected), 'Qwen batch coverage differs from acceptance02'
    cases = {}
    for item in inputs:
        assert sha(item['source']) == sha(item['copy']) == item['expected']
        name = item['role']
        assert item['expected'] == identities[name], 'Qwen input differs from the fixed delivery/calibration audio'
        paths = [out / (name + '.qwen3.' + suffix) for suffix in ('txt', 'json', 'report.md')]
        assert all(p.exists() and p.stat().st_size > 0 for p in paths)
        result = load(paths[1])
        assert Path(result['audio_path']).resolve() == Path(item['copy']).resolve(), 'Qwen actual input path mismatch'
        assert result['audio_sha256'].lower() == item['expected'] == result['request_audio_sha256'].lower(), 'Qwen audio identity mismatch'
        assert Path(result['model']).resolve() == Path(config['model_path']).resolve(), 'Qwen model path mismatch'
        runner = Path(config['runner_path'])
        assert result['tool_fingerprint'].lower() == sha(runner.with_name('transcribe_file.py')) + ':' + sha(runner), 'Qwen source fingerprint changed'
        assert result['model_device'].startswith('cuda') and result['backend'] == 'transformers'
        assert result['language'] == 'Chinese' and result['max_new_tokens'] == 1024
        assert result['max_inference_batch_size'] == 8 and result['ok'] and result['status'] == 'candidate'
        assert result['text'] == paths[0].read_text(encoding='utf-8').strip()
        cases[name] = {'audio_sha256': item['expected'], 'raw_json': str(paths[1]), 'raw_json_sha256': sha(paths[1]),
                       'text': result['text'], 'comparison': compare(expected[name], [{'text': result['text']}])}
    assert cases['known_bad_12j_sentence2']['comparison']['exit_code'] != 0, 'Qwen missed the known bad sample'
    content = cases['current_full']['comparison']
    matches = SequenceMatcher(None, normalize(plan['plain_text']), normalize(cases['current_full']['text']), autojunk=False).get_matching_blocks()
    decisions = []
    for difference in first_asr['differences']:
        a, b = difference['expected_span']
        supported = any(m.a <= a and b <= m.a + m.size for m in matches)
        decisions.append({**difference, 'independent_content_evidence': '源文字词获独立转写直接支持' if supported else '未解决',
                          'resolved_for_content_only': supported, 'phoneme_tone_prosody': '不作结论'})
    result = {'schema_version': 'p4-independent-content.v1', 'wrapper_receipt_sha256': sha(HERE / 'qwen-run-receipt.json'),
              'batch_summary': batch, 'cases': cases, 'old_difference_adjudication': decisions,
              'normal_false_positives': sum(cases[name]['comparison']['exit_code'] != 0 for name in ('human_reference_good', 'user_accepted_g1_good')),
              'known_bad_false_negatives': 0, 'level': content['level'], 'exit_code': content['exit_code'],
              'prior_repetition_suspicions': {'count': len(first_asr['excess_repetition_spans']),
                    'independent_excess_repetition_spans': content['excess_repetition_spans'],
                    'resolved_for_content_only': content['exit_code'] == 0},
              'scope': '一次独立ASR内容候选证据；不给目标正文提示，无新增同音容差；声音目标仍交用户。'}
    if not all(d['resolved_for_content_only'] for d in decisions):
        result['level'], result['exit_code'] = '嫌疑', 2
    write(HERE / 'independent-content-result.json', result)
    return result, content


def main():
    import numpy as np
    import soundfile as sf
    summary = {'level': '工具错误', 'exit_code': 3, 'checks': {}, 'unresolved': [],
               'user_listening': '未通过：尚未用户听审，自动门槛不代替声音验收',
               'command': "& 'D:/anaconda3/envs/cosyvoice/python.exe' -X utf8 -B '" + str(HERE / 'verify.py') + "'"}
    try:
        setup()
        self_check()
        input_identity()
        plan = read(HERE / 'frontend-dry-run.json')
        assert sha(HERE / 'frontend-dry-run.json') == '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
        assert source_versions() == plan['source_versions']
        frontend_output = io.StringIO()
        with contextlib.redirect_stdout(frontend_output), patch.object(socket.socket, 'connect', blocked), patch.object(socket.socket, 'connect_ex', blocked), patch.object(socket, 'create_connection', blocked):
            current = make_plan(frontend())
        summary['frontend_diagnostics'] = frontend_output.getvalue().strip()
        assert current['blocks'] == plan['blocks']
        assert current['prompt_text'] == plan['prompt_text']
        summary['checks']['input_and_frontend'] = '通过：身份、源映射、共享编译与实际TN重跑一致'
        request = read(HERE / 'delivery-request.json')
        assert request['approved_plan_sha256'] == sha(HERE / 'frontend-dry-run.json')
        assert request['approval']['delivery_block_limit'] == 6
        assert request['approval']['extra_repair_limit'] == 0
        assert request['prior_model_calls'] == 6 and request['prior_repair_calls_today'] == 4
        assert request['model_call_count'] == sum(int(c['executed']) for c in request['calls']) <= 6
        assert request['reference']['sha256'] == sha(REFERENCE) and request['reference']['pair_sha256'] == sha(PAIR)
        log_bytes = (TTS / 'request_records.jsonl').read_bytes()
        log_lines = log_bytes.splitlines(keepends=True)
        assert len(log_lines) == 5
        assert hashlib.sha256(b''.join(log_lines[:4])).hexdigest() == request['previous_log_sha256']
        assert json.loads(log_lines[-1]) == request
        assert request['status'] == 'success' and request['delivery_count'] == 1 and request['model_call_count'] == 6
        native_parts = []
        for actual, block in zip(request['calls'], plan['blocks'], strict=True):
            for key, value in block.items():
                assert actual[key] == value, f'actual call mismatch: {key}'
            assert actual['consumed_segments'] == [block['normalized_text']]
            assert actual['consumed_prompt'] == [plan['prompt_text']]
            assert set(actual['runtime']) == {'llm_qwen', 'flow_estimator', 'hift_conv', 'f0'}
            for runtime in actual['runtime'].values():
                assert runtime['calls'] > 0 and runtime['input_devices'] == ['cuda:0'] and runtime['all_parameters_cuda']
            assert actual['runtime']['f0']['input_dtypes'] == ['torch.float64']
            output = actual['output']
            path = HERE / output['filename']
            assert sha(path) == output['sha256']
            pcm, rate = sf.read(path, dtype='int16')
            assert rate == 24000 and pcm.ndim == 1 and len(pcm) == output['frames']
            assert output['offset_seconds'] == sum(len(p) for p in native_parts)/24000
            assert output['added_silence_samples'] == 4800 and np.all(pcm[-4800:] == 0)
            native_parts.append(pcm)
        full = HERE / request['output']['filename']
        assert sha(full) == request['output']['sha256']
        pcm, rate = sf.read(full, dtype='int16')
        assert rate == 24000 and np.array_equal(pcm, np.concatenate(native_parts))
        summary['checks']['request_gpu_budget_complete_audio'] = '通过：6实耗/6预批，实际算子CUDA；完整PCM等于六块依序拼接'
        calibration = read(HERE / 'asr-calibration.json')
        replayed = []
        for case in calibration['cases']:
            assert sha(case['audio_path']) == case['audio_sha256']
            assert hashlib.sha256(case['expected'].encode('utf-8')).hexdigest() == case['expected_sha256']
            replayed.append(compare(case['expected'], case['raw_segments']))
        assert len(replayed) == 3 and replayed[-1]['exit_code'] != 0
        assert calibration['cases'][-1]['audio_sha256'] == '2cd6eb0adc3cb5a4904b2502b6350652dccc1f43e444edda4ee4700e65a8f047'
        summary['checks']['calibration'] = {'known_bad_rejected': True,
                     'false_positives': sum(x['exit_code'] != 0 for x in replayed[:2]),
                     'false_negatives': 0, 'boundary': calibration['scope']}
        asr = read(HERE / 'asr-delivery.json')
        assert asr['audio_sha256'] == sha(full) and asr['expected'] == plan['plain_text']
        assert hashlib.sha256(asr['expected'].encode('utf-8')).hexdigest() == asr['expected_sha256']
        assert asr['tool'] == calibration['tool'], 'delivery ASR differs from frozen calibrated parameters'
        assert sha(Path(asr['tool']['model']) / 'model.bin') == asr['tool']['model_sha256']
        assert abs(asr['asr_duration'] - len(pcm)/rate) < 0.1
        assert asr['processed_full_file'] and asr['raw_segments']
        assert all(0 <= row['start'] <= row['end'] <= len(pcm)/rate + 0.1 for row in asr['raw_segments'])
        content = compare(plan['plain_text'], asr['raw_segments'])
        summary['checks']['protocol01_content'] = content
        summary['unresolved'] = content['differences']
        summary['level'], summary['exit_code'] = content['level'], content['exit_code']
        if (HERE / 'dispatch-02.md').exists():
            independent, new_content = independent_content(plan, calibration, content)
            summary['checks']['protocol02_independent_content'] = {
                'normal_false_positives': independent['normal_false_positives'],
                'known_bad_false_negatives': independent['known_bad_false_negatives'],
                'resolved_old_differences': sum(d['resolved_for_content_only'] for d in independent['old_difference_adjudication']),
                'new_content': new_content, 'detail_path': str(HERE / 'independent-content-result.json')}
            summary['unresolved'] = new_content['differences']
            summary['level'], summary['exit_code'] = independent['level'], independent['exit_code']
        summary['artifacts'] = {'audio': str(full), 'raw_asr': str(HERE / 'asr-delivery.json'),
                                'listening_checklist': str(HERE / '听审清单-listening.md')}
    except AssertionError as exc:
        summary.update(level='失败', exit_code=1, error=str(exc))
    except Exception as exc:
        summary.update(level='工具错误', exit_code=3, error=f'{type(exc).__name__}: {exc}')
    write(HERE / 'verification-result.json', summary)
    print(json.dumps({'level': summary['level'], 'exit_code': summary['exit_code'],
                      'unresolved_count': len(summary['unresolved']),
                      'detail_path': str(HERE / 'verification-result.json'),
                      **({'error': summary['error']} if 'error' in summary else {})}, ensure_ascii=False))
    return summary['exit_code']


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch', choices=['dispatch02', 'trial04'], default='dispatch02')
    args = parser.parse_args()
    if args.batch == 'trial04':
        from phrase_trial import verify_trial
        raise SystemExit(verify_trial())
    raise SystemExit(main())
