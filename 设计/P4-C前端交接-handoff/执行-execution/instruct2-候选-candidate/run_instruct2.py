"""P4 instruct2 candidate: single-variable switch from zero_shot to inference_instruct2.

Fixed per root-approved plan (2026-09-12): same reference 赵欣.WAV, same reviewed body,
same approved 6-block plan (frontend-dry-run.json 24f53814...), text_frontend=True,
stream=False, speed=1.0, txt3=0.2, seed 1986, empty speaker cache id. The only change
versus the accepted zero-shot delivery is the interface and the registered instruction.
No source-code modification; instruction stays a call parameter.
"""
import hashlib
import json
import os
import socket
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
TTS = Path('E:/zimu/建设-worktrees/配音引擎-cosyvoice')
REFERENCE = Path('E:/zimu/谢军/赵欣.WAV')
PAIR = Path('E:/zimu/谢军/数字人音频文.txt')
APPROVED_PLAN_SHA = '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
INSTRUCT = 'You are a helpful assistant. 请用自然流畅的普通话讲解，语速适中，短语之间衔接紧凑。<|endofprompt|>'
SEED = 1986


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def setup():
    for name in ('HF_HOME', 'MODELSCOPE_CACHE', 'TORCH_HOME', 'NUMBA_CACHE_DIR', 'TEMP', 'TMP', 'TMPDIR'):
        directory = HERE / 'cache' / name.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', MODELSCOPE_OFFLINE='1')
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(TTS), 'D:/tts/CosyVoice/third_party/Matcha-TTS']


def blocked(*args, **kwargs):
    raise RuntimeError('P4 offline execution: network blocked')


def source_versions():
    import json as _json
    parent = _json.loads((EXEC / 'frontend-dry-run.json').read_text(encoding='utf-8'))
    return parent['source_versions']


def synthesize():
    import numpy as np
    import soundfile as sf
    import torch
    import main_cosyvoice as main
    record_path = HERE / 'instruct2-delivery-request.json'
    assert not record_path.exists(), 'instruct2 candidate already attempted; no implicit retry'
    plan_path = EXEC / 'frontend-dry-run.json'
    assert sha(plan_path) == APPROVED_PLAN_SHA, 'approved dry-run changed'
    plan = read(plan_path)
    assert torch.cuda.is_available(), 'CPU synthesis is prohibited'
    assert source_versions() == plan['source_versions'], 'model/frontend source changed since approval'
    old_log = main.REQUEST_LOG_PATH.read_bytes()
    historical = [json.loads(line) for line in old_log.decode('utf-8').splitlines()]
    prior_model_calls = sum(x.get('model_call_count', x.get('audio', {}).get('model_block_count', 0)) for x in historical)
    prior_repair_calls_today = 4
    record = {'schema_version': 'cosyvoice-request-record.v1', 'request_id': uuid.uuid4().hex,
              'received_at': datetime.now(timezone.utc).isoformat(),
              'entry': 'diagnostic direct inference_instruct2; official instruct entry; not HTTP /inference',
              'approved_plan_sha256': APPROVED_PLAN_SHA,
              'approval_source': 'root explicit instruction in audit chat, 2026-09-12: 按这个方案执行吧',
              'approval': {'delivery_block_limit': 6, 'extra_repair_limit': 0},
              'prior_model_calls': prior_model_calls, 'prior_repair_calls_today': prior_repair_calls_today,
              'model_call_count': 0, 'delivery_count': 0, 'calls': [], 'status': 'preflight',
              'interface': {'method': 'inference_instruct2', 'zero_shot_spk_id': '', 'seed': SEED,
                            'instruct_text': INSTRUCT,
                            'note': 'frontend_instruct2 removes llm_prompt_speech_token (official behavior); voice identity relies on speaker embedding plus flow prompt conditions',
                            'not_used': ['breath tags', 'emphasis tags', 'RL weights', 'silent-token filter', 'reference change', 'punctuation change', 'rechunking']},
              'request': {'txt1': PAIR.read_text(encoding='utf-8').strip(),
                          'txt2': (EXEC.parent / '稀疏修订-sparse/g3-pause-review/完整第一自然段-paragraph-input.txt').read_text(encoding='utf-8'),
                          'txt3': 0.2, 'text_frontend': True, 'stream': False, 'speed': 1.0},
              'reference': {'path': str(REFERENCE), 'sha256': sha(REFERENCE), 'pair_sha256': sha(PAIR)},
              'source_versions': plan['source_versions'],
              'previous_log_sha256': hashlib.sha256(old_log).hexdigest(),
              'output': None}
    write(record_path, record)
    handles = []
    current = [None]
    parts = []
    started = time.monotonic()
    try:
        model = main.load_cosyvoice(main.DEFAULT_MODEL_DIR, main.DEFAULT_WETEXT_DIR, main.DEFAULT_MATCHA_DIR)
        from cosyvoice.utils.common import set_all_random_seed
        assert model.frontend.text_normalize(INSTRUCT, split=False, text_frontend=True) == INSTRUCT, 'instruct text must reach the model verbatim'
        record['device'] = {'gpu_name': torch.cuda.get_device_name(0),
                            'all_parameter_devices': {name: sorted({str(p.device) for p in getattr(model.model, name).parameters()}) for name in ('llm', 'flow', 'hift')},
                            'campplus_providers': model.frontend.campplus_session.get_providers(),
                            'speech_tokenizer_providers': model.frontend.speech_tokenizer_session.get_providers()}
        assert all(devices == ['cuda:0'] for devices in record['device']['all_parameter_devices'].values())

        def tensors(value):
            if isinstance(value, torch.Tensor):
                return [value]
            if isinstance(value, dict):
                return [t for v in value.values() for t in tensors(v)]
            if isinstance(value, (tuple, list)):
                return [t for v in value for t in tensors(v)]
            return []

        def hook(name):
            def inspect(module, args, kwargs):
                call = current[0]
                assert call is not None
                inputs = tensors((args, kwargs))
                assert inputs and all(t.device.type == 'cuda' for t in inputs), f'{name} CPU input'
                assert all(p.device.type == 'cuda' for p in module.parameters()), f'{name} CPU parameters'
                if not call['executed']:
                    assert record['model_call_count'] < 6, 'approved GPU block budget exhausted'
                    call['executed'] = True
                    record['model_call_count'] += 1
                    write(record_path, record)
                runtime = call['runtime'].setdefault(name, {'calls': 0, 'input_devices': sorted({str(t.device) for t in inputs}),
                           'input_dtypes': sorted({str(t.dtype) for t in inputs}), 'all_parameters_cuda': True})
                runtime['calls'] += 1
                if name == 'f0':
                    assert all(t.dtype == torch.float64 for t in inputs)
                    assert all(p.dtype == torch.float64 for p in module.parameters())
            return inspect

        nodes = {'llm_qwen': model.model.llm.llm.model,
                 'flow_estimator': model.model.flow.decoder.estimator,
                 'hift_conv': model.model.hift.conv_pre,
                 'f0': model.model.hift.f0_predictor}
        for name, node in nodes.items():
            handles.append(node.register_forward_pre_hook(hook(name), with_kwargs=True))

        for block in plan['blocks']:
            assert time.monotonic() - started < 300, 'delivery time window exceeded; no additional calls'
            consumed = model.frontend.text_normalize(block['compiled_text'], split=True, text_frontend=True)
            assert consumed == [block['normalized_text']], 'actual frontend consumption differs from approved plan'
            call = {**block, 'executed': False, 'runtime': {},
                    'consumed_segments': consumed, 'consumed_prompt': [INSTRUCT],
                    'model_output_count': 0, 'status': 'preparing'}
            record['calls'].append(call)
            current[0] = call
            write(record_path, record)
            set_all_random_seed(SEED)
            audio = []
            for output in model.inference_instruct2(block['compiled_text'], INSTRUCT, str(REFERENCE),
                    zero_shot_spk_id='', stream=False, speed=1.0, text_frontend=True):
                speech = output['tts_speech']
                assert speech.ndim == 2 and speech.shape[0] == 1 and speech.shape[1] > 0
                assert torch.isfinite(speech).all() and float(speech.abs().max()) > 1e-4
                audio.extend([speech.cpu(), torch.zeros(1, int(0.2 * model.sample_rate), dtype=speech.dtype)])
                call['model_output_count'] += 1
            assert call['executed'] and set(call['runtime']) == set(nodes)
            assert call['model_output_count'] == 1
            path = HERE / f"{record['request_id']}-instruct2-block-{block['index']}.wav"
            main.save_wav_safe(path, torch.cat(audio, dim=1), model.sample_rate)
            pcm, rate = sf.read(path, dtype='int16')
            assert rate == 24000 and len(pcm) > 4800 and np.all(pcm[-4800:] == 0)
            call['output'] = {'filename': path.name, 'sha256': sha(path), 'frames': len(pcm), 'seconds': len(pcm)/rate,
                              'offset_seconds': sum(len(p) for p in parts)/rate, 'added_silence_samples': 4800}
            call['status'] = 'success'
            parts.append(pcm)
            write(record_path, record)
            print(json.dumps({'block': block['index'], 'seconds': len(pcm)/rate, 'executed_calls': record['model_call_count']}, ensure_ascii=False), flush=True)
        assert record['model_call_count'] == 6
        path = HERE / f"{record['request_id']}-instruct2-完整第一自然段-full-paragraph.wav"
        sf.write(path, np.concatenate(parts), 24000, subtype='PCM_16')
        actual, rate = sf.read(path, dtype='int16')
        assert np.array_equal(actual, np.concatenate(parts))
        record['output'] = {'filename': path.name, 'sha256': sha(path), 'frames': len(actual), 'sample_rate': rate,
                            'seconds': len(actual)/rate, 'sample_exact_concatenation': True}
        record['status'] = 'success'
        record['delivery_count'] = 1
    except Exception as exc:
        record.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        (HERE / 'synthesis-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
    finally:
        for handle in handles:
            handle.remove()
        record['elapsed_seconds'] = round(time.monotonic() - started, 3)
        write(record_path, record)
        assert main.REQUEST_LOG_PATH.read_bytes() == old_log
        main.append_request_record(record)
        assert main.REQUEST_LOG_PATH.read_bytes().startswith(old_log)


def main():
    setup()
    with patch.object(socket.socket, 'connect', blocked), patch.object(socket.socket, 'connect_ex', blocked), patch.object(socket, 'create_connection', blocked):
        synthesize()


if __name__ == '__main__':
    main()
