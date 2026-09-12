"""P4 role-instruction probes R1/R2/R3: block 5, instruct2, 赵欣 reference, seed 1986.
Purpose: test whether official-style role phrasings trigger the trained role-playing dimension.
Control: trial04 B0 (neutral arm, same block/seed/reference) reused without new calls.
Judgment: no measurable/listenable difference vs B0 => 未触发, wording discarded.
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
APPROVED_PLAN_SHA = '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
SEED = 1986
PROBES = {
    'R1': 'You are a helpful assistant. 我想体验一下经验丰富的职业院校教师课堂讲课的风格，可以吗？<|endofprompt|>',
    'R2': 'You are a helpful assistant. 请像经验丰富的教师给学生讲课一样表达。<|endofprompt|>',
    'R3': 'You are a helpful assistant. 请用自然流畅的普通话讲解，语速适中，不要过快；专业词组内部连贯，句读停顿从容。<|endofprompt|>',
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


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


def synthesize():
    import numpy as np
    import soundfile as sf
    import torch
    import main_cosyvoice as main
    record_path = HERE / 'role-probes-request.json'
    assert not record_path.exists(), 'probes already attempted; no implicit retry'
    plan = read(EXEC / 'frontend-dry-run.json')
    assert sha(EXEC / 'frontend-dry-run.json') == APPROVED_PLAN_SHA
    block5 = next(b for b in plan['blocks'] if b['index'] == 5)
    assert torch.cuda.is_available(), 'CPU synthesis is prohibited'
    old_log = main.REQUEST_LOG_PATH.read_bytes()
    historical = [json.loads(line) for line in old_log.decode('utf-8').splitlines()]
    prior_model_calls = sum(x.get('model_call_count', x.get('audio', {}).get('model_block_count', 0)) for x in historical)
    record = {'schema_version': 'cosyvoice-request-record.v1', 'request_id': uuid.uuid4().hex,
              'received_at': datetime.now(timezone.utc).isoformat(),
              'entry': 'probe direct inference_instruct2; role-instruction variants R1/R2/R3; block 5 only; not HTTP /inference',
              'approved_plan_sha256': APPROVED_PLAN_SHA,
              'approval_source': 'user approval in audit chat, 2026-09-13: 批准（3次探针）',
              'approval': {'probe_call_limit': 3, 'control_arm': 'trial04 B0 neutral reused without new calls'},
              'prior_model_calls': prior_model_calls,
              'model_call_count': 0, 'calls': [], 'status': 'preflight',
              'interface': {'method': 'inference_instruct2', 'zero_shot_spk_id': '', 'seed': SEED,
                            'variants': PROBES,
                            'judgment_rules': ['no measurable/listenable difference vs B0 => 未触发, discard',
                                               'triggered + useful => seed-repeat verification before adoption']},
              'request': {'txt2': block5['compiled_text'], 'txt3': 0.2, 'text_frontend': True, 'stream': False, 'speed': 1.0},
              'reference': {'path': str(REFERENCE), 'sha256': sha(REFERENCE)},
              'previous_log_sha256': hashlib.sha256(old_log).hexdigest(),
              'output': None}
    write(record_path, record)
    handles = []
    current = [None]
    started = time.monotonic()
    try:
        model = main.load_cosyvoice(main.DEFAULT_MODEL_DIR, main.DEFAULT_WETEXT_DIR, main.DEFAULT_MATCHA_DIR)
        from cosyvoice.utils.common import set_all_random_seed
        consumed = model.frontend.text_normalize(block5['compiled_text'], split=True, text_frontend=True)
        assert len(consumed) == 1 and consumed[0] == block5['normalized_text'], consumed
        record['device'] = {'gpu_name': torch.cuda.get_device_name(0),
                            'all_parameter_devices': {name: sorted({str(p.device) for p in getattr(model.model, name).parameters()}) for name in ('llm', 'flow', 'hift')}}
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
                inputs = tensors((args, kwargs))
                assert inputs and all(t.device.type == 'cuda' for t in inputs), f'{name} CPU input'
                if not call['executed']:
                    assert record['model_call_count'] < 3, 'probe budget exhausted'
                    call['executed'] = True
                    record['model_call_count'] += 1
                    write(record_path, record)
                runtime = call['runtime'].setdefault(name, {'calls': 0, 'input_devices': sorted({str(t.device) for t in inputs}),
                           'input_dtypes': sorted({str(t.dtype) for t in inputs})})
                runtime['calls'] += 1
                if name == 'f0':
                    assert all(t.dtype == torch.float64 for t in inputs)
            return inspect

        nodes = {'llm_qwen': model.model.llm.llm.model,
                 'flow_estimator': model.model.flow.decoder.estimator,
                 'hift_conv': model.model.hift.conv_pre,
                 'f0': model.model.hift.f0_predictor}
        for name, node in nodes.items():
            handles.append(node.register_forward_pre_hook(hook(name), with_kwargs=True))

        for variant, instruct in PROBES.items():
            assert time.monotonic() - started < 300, 'probe window exceeded; remaining variants skipped'
            call = {'variant': variant, 'instruct_text': instruct, 'compiled_text': block5['compiled_text'],
                    'normalized_text': block5['normalized_text'], 'executed': False, 'runtime': {},
                    'consumed_segments': consumed, 'consumed_prompt': [instruct],
                    'model_output_count': 0, 'status': 'preparing'}
            record['calls'].append(call)
            current[0] = call
            write(record_path, record)
            set_all_random_seed(SEED)
            audio = []
            for output in model.inference_instruct2(block5['compiled_text'], instruct, str(REFERENCE),
                    zero_shot_spk_id='', stream=False, speed=1.0, text_frontend=True):
                speech = output['tts_speech']
                assert speech.ndim == 2 and speech.shape[0] == 1 and speech.shape[1] > 0
                assert torch.isfinite(speech).all() and float(speech.abs().max()) > 1e-4
                audio.extend([speech.cpu(), torch.zeros(1, int(0.2 * model.sample_rate), dtype=speech.dtype)])
                call['model_output_count'] += 1
            assert call['executed'] and set(call['runtime']) == set(nodes)
            assert call['model_output_count'] == 1
            path = HERE / f"{record['request_id']}-role-{variant}-block-5.wav"
            main.save_wav_safe(path, torch.cat(audio, dim=1), model.sample_rate)
            pcm, rate = sf.read(path, dtype='int16')
            assert rate == 24000 and len(pcm) > 4800 and np.all(pcm[-4800:] == 0)
            call['output'] = {'filename': path.name, 'sha256': sha(path), 'frames': len(pcm),
                              'seconds': len(pcm)/rate, 'added_silence_samples': 4800}
            call['status'] = 'success'
            write(record_path, record)
            print(json.dumps({'variant': variant, 'seconds': len(pcm)/rate}, ensure_ascii=False), flush=True)
        assert record['model_call_count'] == 3
        record['status'] = 'success'
    except Exception as exc:
        record.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        (HERE / 'role-probes-error.log').write_text(traceback.format_exc(), encoding='utf-8')
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
