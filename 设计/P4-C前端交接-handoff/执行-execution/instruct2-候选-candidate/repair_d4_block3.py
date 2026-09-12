"""P4 repair: recompile block 3 with d4 pronunciation control restored (user 41.7s misread),
re-synthesize ONLY block 3 on the approved instruct2 candidate config (1 approved call),
reassemble the full paragraph sample-exactly, and append the record.

Traceability: the frozen readings.json is NOT modified; the corrected d4 decision is an
in-memory override recorded verbatim in the repair record, applied through the real
build_view compiler so projection/decision ids remain genuine.
"""
import hashlib
import json
import os
import socket
import sys
import time
import traceback
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
TTS = Path('E:/zimu/建设-worktrees/配音引擎-cosyvoice')
SUBTITLE = Path('E:/zimu/建设-worktrees/新配音-voiceover-workflow')
READINGS = EXEC.parent.parent / 'P4-B全文语义核验-semantic/稀疏控制修订-sparse-control/已审阅-reviewed/readings.json'
REFERENCE = Path('E:/zimu/谢军/赵欣.WAV')
APPROVED_PLAN_SHA = '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
INSTRUCT = 'You are a helpful assistant. 请用自然流畅的普通话讲解，语速适中，短语之间衔接紧凑。<|endofprompt|>'
SEED = 1986
BLOCK_INDEX = 3
BLOCK_SPAN = [99, 166]
OLD_BLOCK3_COMPILED = '本课程坚守高职教育"以岗定学、学以致用、能力为本"的育人理念，深度融合大数据前沿技术、智能财务工具、企业全链条业务场景与管理会计实务，'
NEW_BLOCK3_COMPILED = '本课程坚守高职教育"以岗定学、学以致用、能力为本"的育人理念，深度融合大数据前沿技术、智能财务工具、企业全链条业务场景与管理[k][uài][j][ì]实务，'


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
    sys.path[:0] = [str(TTS), str(SUBTITLE), 'D:/tts/CosyVoice/third_party/Matcha-TTS']


def blocked(*args, **kwargs):
    raise RuntimeError('P4 offline execution: network blocked')


def corrected_readings():
    record = read(READINGS)
    decisions = record['decisions']
    d4 = next(d for d in decisions if d['id'] == 'd4')
    assert d4['span'] == [161, 163] and d4['original'] == '会计'
    assert d4['engine_control']['status'] == 'not_required' and d4['engine_tokens'] == []
    fixed = deepcopy(d4)
    fixed['engine_control'] = {
        'basis': '用户听审反馈本处会计读呲（98.72s版41.7s处；来源为用户本轮聊天原话），经用户批准补局部四token控制；'
                 '仅此源跨度，不推广其他管理会计，不改变11-d稀疏决策的其余部分。',
        'basis_version': 'user-listening-2026-09-12; repair approved in audit chat',
        'scope': {'run_id': record['run_id'], 'span': BLOCK_SPAN},
        'status': 'required'}
    fixed['engine_tokens'] = ['[k]', '[uài]', '[j]', '[ì]']
    fixed['phonetic_basis'] = '目标kuàijì分解为[k][uài][j][ì]；实际tokenizer在本机已验证（d1/d2同版写法）。'
    record['decisions'] = [fixed if d['id'] == 'd4' else d for d in decisions]
    return record, fixed


def recompile_block3(tokenizer):
    from src.manual_tools.reading_preparation import build_view
    record, fixed = corrected_readings()
    view = build_view(record, 'cosyvoice', tokenizer=tokenizer, source_span=BLOCK_SPAN)
    assert view['text'] == NEW_BLOCK3_COMPILED, f'unexpected compiled text: {view["text"]!r}'
    assert view['engine_control_ids'] == ['d4'], view['engine_control_ids']
    assert view['decision_ids'][-1] == 'd4'
    assert len(view['text']) == 79, len(view['text'])
    return view, fixed


def synthesize():
    import numpy as np
    import soundfile as sf
    import torch
    import main_cosyvoice as main
    record_path = HERE / 'repair-d4-request.json'
    assert not record_path.exists(), 'repair already attempted; no implicit retry'
    candidate_request = read(HERE / 'instruct2-delivery-request.json')
    assert candidate_request['status'] == 'success'
    plan = read(EXEC / 'frontend-dry-run.json')
    assert sha(EXEC / 'frontend-dry-run.json') == APPROVED_PLAN_SHA
    block3 = next(b for b in plan['blocks'] if b['index'] == BLOCK_INDEX)
    assert block3['source_span'] == BLOCK_SPAN and block3['compiled_text'] == OLD_BLOCK3_COMPILED
    assert torch.cuda.is_available(), 'CPU synthesis is prohibited'
    old_log = main.REQUEST_LOG_PATH.read_bytes()
    historical = [json.loads(line) for line in old_log.decode('utf-8').splitlines()]
    prior_model_calls = sum(x.get('model_call_count', x.get('audio', {}).get('model_block_count', 0)) for x in historical)
    record = {'schema_version': 'cosyvoice-request-record.v1', 'request_id': uuid.uuid4().hex,
              'received_at': datetime.now(timezone.utc).isoformat(),
              'entry': 'repair direct inference_instruct2; single block 3 with d4 control restored; not HTTP /inference',
              'approved_plan_sha256': APPROVED_PLAN_SHA,
              'approval_source': 'user approval in audit chat, 2026-09-12: 批（1次修复额度）',
              'approval': {'repair_call_limit': 1, 'extra_repair_limit': 0},
              'prior_model_calls': prior_model_calls, 'prior_repair_calls_today': 4,
              'model_call_count': 0, 'delivery_count': 0, 'calls': [], 'status': 'preflight',
              'interface': {'method': 'inference_instruct2', 'zero_shot_spk_id': '', 'seed': SEED,
                            'instruct_text': INSTRUCT},
              'repair': {'decision_id': 'd4', 'decision_source_sha256': sha(READINGS),
                         'decision_override': None, 'span': BLOCK_SPAN,
                         'old_compiled': OLD_BLOCK3_COMPILED, 'old_compiled_sha256': hashlib.sha256(OLD_BLOCK3_COMPILED.encode()).hexdigest(),
                         'new_compiled': NEW_BLOCK3_COMPILED, 'new_compiled_sha256': hashlib.sha256(NEW_BLOCK3_COMPILED.encode()).hexdigest(),
                         'old_block_wav': candidate_request['calls'][2]['output']['filename'],
                         'old_block_wav_sha256': candidate_request['calls'][2]['output']['sha256']},
              'request': {'txt3': 0.2, 'text_frontend': True, 'stream': False, 'speed': 1.0},
              'reference': {'path': str(REFERENCE), 'sha256': sha(REFERENCE)},
              'previous_log_sha256': hashlib.sha256(old_log).hexdigest(),
              'output': None}
    handles = []
    current = [None]
    started = time.monotonic()
    try:
        model = main.load_cosyvoice(main.DEFAULT_MODEL_DIR, main.DEFAULT_WETEXT_DIR, main.DEFAULT_MATCHA_DIR)
        from cosyvoice.utils.common import set_all_random_seed
        view, fixed = recompile_block3(model.frontend.tokenizer)
        record['repair']['decision_override'] = fixed
        compiled = view['text']
        consumed = model.frontend.text_normalize(compiled, split=True, text_frontend=True)
        assert len(consumed) == 1 and len(consumed[0]) <= 80, consumed
        normalized = consumed[0]
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
                assert call is not None
                inputs = tensors((args, kwargs))
                assert inputs and all(t.device.type == 'cuda' for t in inputs), f'{name} CPU input'
                if not call['executed']:
                    assert record['model_call_count'] < 1, 'repair budget exhausted'
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

        call = {'index': BLOCK_INDEX, 'compiled_text': compiled, 'normalized_text': normalized,
                'source_span': BLOCK_SPAN, 'executed': False, 'runtime': {},
                'consumed_segments': consumed, 'consumed_prompt': [INSTRUCT],
                'model_output_count': 0, 'status': 'preparing'}
        record['calls'].append(call)
        current[0] = call
        write(record_path, record)
        set_all_random_seed(SEED)
        audio = []
        for output in model.inference_instruct2(compiled, INSTRUCT, str(REFERENCE),
                zero_shot_spk_id='', stream=False, speed=1.0, text_frontend=True):
            speech = output['tts_speech']
            assert speech.ndim == 2 and speech.shape[0] == 1 and speech.shape[1] > 0
            assert torch.isfinite(speech).all() and float(speech.abs().max()) > 1e-4
            audio.extend([speech.cpu(), torch.zeros(1, int(0.2 * model.sample_rate), dtype=speech.dtype)])
            call['model_output_count'] += 1
        assert call['executed'] and set(call['runtime']) == set(nodes)
        assert call['model_output_count'] == 1
        new_block_path = HERE / f"{record['request_id']}-repair-d4-block-3.wav"
        main.save_wav_safe(new_block_path, torch.cat(audio, dim=1), model.sample_rate)
        pcm3, rate = sf.read(new_block_path, dtype='int16')
        assert rate == 24000 and len(pcm3) > 4800 and np.all(pcm3[-4800:] == 0)
        call['output'] = {'filename': new_block_path.name, 'sha256': sha(new_block_path),
                          'frames': len(pcm3), 'seconds': len(pcm3)/rate, 'added_silence_samples': 4800}
        call['status'] = 'success'
        record['model_call_count'] = 1
        # Reassemble: candidate blocks 1,2 (unchanged) + new block 3 + candidate blocks 4,5,6 (unchanged)
        parts = []
        for index in (1, 2, 3, 4, 5, 6):
            if index == BLOCK_INDEX:
                parts.append(pcm3)
            else:
                src = HERE / candidate_request['calls'][index - 1]['output']['filename']
                assert sha(src) == candidate_request['calls'][index - 1]['output']['sha256'], f'block {index} changed'
                block_pcm, block_rate = sf.read(src, dtype='int16')
                assert block_rate == 24000
                parts.append(block_pcm)
        full = HERE / f"{record['request_id']}-repair-d4-完整第一自然段-full-paragraph.wav"
        sf.write(full, np.concatenate(parts), 24000, subtype='PCM_16')
        actual, rate = sf.read(full, dtype='int16')
        assert np.array_equal(actual, np.concatenate(parts))
        record['output'] = {'filename': full.name, 'sha256': sha(full), 'frames': len(actual), 'sample_rate': rate,
                            'seconds': len(actual)/rate, 'sample_exact_reassembly': True,
                            'replaced_block': BLOCK_INDEX, 'blocks_from_candidate': [1, 2, 4, 5, 6]}
        record['status'] = 'success'
        record['delivery_count'] = 1
    except Exception as exc:
        record.update(status='failed', error={'type': type(exc).__name__, 'message': str(exc)})
        (HERE / 'repair-d4-error.log').write_text(traceback.format_exc(), encoding='utf-8')
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
