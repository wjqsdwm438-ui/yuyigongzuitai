"""Run current-input gates without synthesizing or trusting cached pass flags."""
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

from p4_delivery import HERE, TTS, READY, READINGS, INPUT, REFERENCE, PAIR, sha, read, write
from p4_delivery import setup, blocked, frontend, make_plan, source_versions, input_identity
from content_verify import compare, self_check


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
        with patch.object(socket.socket, 'connect', blocked), patch.object(socket.socket, 'connect_ex', blocked), patch.object(socket, 'create_connection', blocked):
            current = make_plan(frontend())
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
        summary['checks']['content'] = content
        summary['unresolved'] = content['differences']
        summary['level'], summary['exit_code'] = content['level'], content['exit_code']
        summary['artifacts'] = {'audio': str(full), 'raw_asr': str(HERE / 'asr-delivery.json'),
                                'listening_checklist': str(HERE / '听审清单-listening.md')}
    except AssertionError as exc:
        summary.update(level='失败', exit_code=1, error=str(exc))
    except Exception as exc:
        summary.update(level='工具错误', exit_code=3, error=f'{type(exc).__name__}: {exc}')
    write(HERE / 'verification-result.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
