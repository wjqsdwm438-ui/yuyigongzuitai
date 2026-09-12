"""P4 dispatch-01: mapped real frontend dry-run and bounded local delivery."""
import argparse
import hashlib
import json
import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
TTS = Path('E:/zimu/建设-worktrees/配音引擎-cosyvoice')
SUBTITLE = Path('E:/zimu/建设-worktrees/新配音-voiceover-workflow')
REVIEWED = HERE.parents[1] / 'P4-B全文语义核验-semantic/稀疏控制修订-sparse-control/已审阅-reviewed'
READY = REVIEWED / 'ready-segments.json'
READINGS = REVIEWED / 'readings.json'
INPUT = HERE.parent / '稀疏修订-sparse/g3-pause-review/完整第一自然段-paragraph-input.txt'
REFERENCE = Path('E:/zimu/谢军/赵欣.WAV')
PAIR = Path('E:/zimu/谢军/数字人音频文.txt')
MODEL = Path('D:/tts/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B')
WETEXT = Path('C:/Users/admin/.cache/modelscope/hub/pengzhendong/wetext')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


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
    sys.path[:0] = [str(TTS), str(SUBTITLE), 'D:/tts/CosyVoice/third_party/Matcha-TTS']


def blocked(*args, **kwargs):
    raise RuntimeError('P4 offline execution: network blocked')


def frontend():
    from cosyvoice.cli.frontend import CosyVoiceFrontEnd, build_local_wetext_normalizers
    from cosyvoice.tokenizer.tokenizer import get_qwen_tokenizer
    import inflect
    result = CosyVoiceFrontEnd.__new__(CosyVoiceFrontEnd)
    result.tokenizer = get_qwen_tokenizer(str(MODEL / 'CosyVoice-BlankEN'), skip_special_tokens=True, version='cosyvoice3')
    result.allowed_special = 'all'
    result.use_ttsfrd = False
    result.zh_tn_model, result.en_tn_model = build_local_wetext_normalizers(WETEXT)
    result.inflect_parser = inflect.engine()
    return result


def input_identity():
    import re
    entries = re.findall(r'\|[^\n]+\|\s*(E:/[^|]+?)\s*\|\s*([0-9a-f]{64})\s*\|', (HERE / 'acceptance-01.md').read_text(encoding='utf-8'))
    assert len(entries) == 6, 'acceptance fixed input table missing'
    for path, expected in entries:
        assert sha(path) == expected, f'fixed input changed: {path}'
    return [{'path': path, 'sha256': expected} for path, expected in entries]


def source_versions():
    paths = [TTS / name for name in ('cosyvoice/cli/frontend.py', 'cosyvoice/utils/frontend_utils.py',
             'cosyvoice/cli/cosyvoice.py', 'cosyvoice/cli/model.py', 'cosyvoice/hifigan/generator.py')]
    paths += [SUBTITLE / 'src/manual_tools/reading_preparation.py', READINGS]
    paths += [WETEXT / lang / 'tn' / name for lang in ('zh', 'en') for name in ('tagger.fst', 'verbalizer.fst')]
    paths += [MODEL / 'CosyVoice-BlankEN' / name for name in ('tokenizer_config.json', 'vocab.json', 'merges.txt')]
    return [{'path': str(path), 'sha256': sha(path)} for path in paths]


def make_plan(f):
    from src.manual_tools.reading_preparation import build_view, load_source
    identity = input_identity()
    groups = read(READY)[:11]
    assert [g['item_id'] for g in groups] == [f'g{i}' for i in range(1, 12)]
    readings = read(READINGS)
    source = load_source(readings)
    plain = ''.join(g['plain_text'] for g in groups)
    assert plain == source[2:383]
    assert ''.join(g['views']['cosyvoice']['text'] for g in groups) == INPUT.read_text(encoding='utf-8')
    # Official candidates are taken on the unannotated, source-mapped body first.
    candidates = f.text_normalize(plain, split=True, text_frontend=True)
    assert ''.join(candidates) == plain, 'TN changed body: mapping must be reviewed again'
    offset = 2
    candidate_ends = []
    for candidate in candidates:
        offset += len(candidate)
        candidate_ends.append(offset)
    # Reviewed group ends are legal punctuation outside enumerations/modifiers.
    # Recompile each candidate group with the shared compiler, then check actual TN.
    blocks = []
    cursor = 0
    while cursor < len(groups):
        choices = []
        for stop in range(cursor + 1, len(groups) + 1):
            span = [groups[cursor]['source_span'][0], groups[stop - 1]['source_span'][1]]
            view = build_view(readings, 'cosyvoice', tokenizer=f.tokenizer, source_span=span)
            text = view['text']
            if len(text) > 80:
                break
            actual = f.text_normalize(text, split=True, text_frontend=True)
            if len(actual) == 1 and len(actual[0]) <= 80:
                choices.append((stop, span, view, actual[0]))
        assert choices, 'no safe punctuation within frontend capacity'
        stop, span, view, normalized = choices[-1]
        ids = [g['item_id'] for g in groups[cursor:stop]]
        blocks.append({'index': len(blocks) + 1, 'groups': ids, 'source_span': span,
                       'plain_text': source[slice(*span)], 'compiled_text': view['text'],
                       'normalized_text': normalized, 'projection': view['projection'],
                       'decision_ids': view['decision_ids'], 'engine_control_ids': view['engine_control_ids'],
                       'characters': len(normalized),
                       'tokens': len(f.tokenizer.encode(normalized, allowed_special='all')),
                       'end_boundary_reason': groups[stop - 1]['boundary']['basis'],
                       'adjustment': '标准候选对齐到已审阅完整语义组末标点；容量按编译后实际TN重验。',
                       'trailing_punctuation_change': [view['text'][-1], normalized[-1]]})
        cursor = stop
    assert ''.join(b['compiled_text'] for b in blocks) == INPUT.read_text(encoding='utf-8')
    assert [x for b in blocks for x in b['engine_control_ids']] == ['d1', 'd2']
    assert [b['groups'] for b in blocks] == [['g1'], ['g2', 'g3'], ['g4', 'g5'], ['g6', 'g7'], ['g8', 'g9'], ['g10', 'g11']]
    prompt = 'You are a helpful assistant.<|endofprompt|>' + PAIR.read_text(encoding='utf-8').strip()
    assert f.text_normalize(prompt, split=False, text_frontend=True) == prompt
    historical = [json.loads(line) for line in (TTS / 'request_records.jsonl').read_text(encoding='utf-8').splitlines()]
    return {'schema_version': 'p4-delivery-plan.v1', 'fixed_inputs': identity,
            'source_versions': source_versions(), 'source_span': [2, 383], 'plain_text': plain,
            'standard_candidate_ends': candidate_ends, 'standard_candidates': candidates,
            'blocks': blocks, 'block_count': len(blocks), 'synthesis_calls': 0,
            'prompt_text': prompt, 'source_identity': readings['source'],
            'history': {'request_records': len(historical),
                        'actual_model_calls': sum(x.get('model_call_count', x.get('audio', {}).get('model_block_count', 0)) for x in historical),
                        'request_log_sha256': sha(TTS / 'request_records.jsonl'),
                        'paragraph_failed_deliveries': 2,
                        'same_root_cause_status': '12-f与12-j均声音否决；具体同根因未证，保守维持连续失败2的停合成条件，需主线程依据新dry-run恢复。'},
            'parameters': {'text_frontend': True, 'speed': 1.0, 'stream': False, 'pause': 0.2},
            'diagnosis': '旧长段/三长句绕过标准分段；输入完整但输出内容失败。当前唯一变化为源映射上的合法标准长度分段，不改F0、参考、正文、控制或采样；这是一项待实际核验的修复假设。'}


def synthesize():
    import time
    import traceback
    import uuid
    from datetime import datetime, timezone
    import numpy as np
    import soundfile as sf
    import torch
    import main_cosyvoice as main
    approved_sha = '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
    plan_path = HERE / 'frontend-dry-run.json'
    assert sha(plan_path) == approved_sha, 'approved dry-run changed'
    record_path = HERE / 'delivery-request.json'
    assert not record_path.exists(), 'delivery already attempted; no implicit retry'
    assert torch.cuda.is_available(), 'CPU synthesis is prohibited'
    plan = read(plan_path)
    input_identity()
    assert source_versions() == plan['source_versions'], 'TN/compiler/model source changed'
    old_log = main.REQUEST_LOG_PATH.read_bytes()
    assert hashlib.sha256(old_log).hexdigest() == plan['history']['request_log_sha256']
    started = time.monotonic()
    record = {'schema_version': 'cosyvoice-request-record.v1', 'request_id': uuid.uuid4().hex,
              'received_at': datetime.now(timezone.utc).isoformat(),
              'entry': 'diagnostic direct inference_zero_shot; official text_frontend=True; not HTTP /inference',
              'approved_plan_sha256': approved_sha, 'approval_source': 'root explicit collaboration message, 2026-09-12',
              'approval': {'delivery_block_limit': 6, 'extra_repair_limit': 0,
                           'historical_stop_released_for_this_diagnosis': True, 'historical_consecutive_failures': 2},
              'prior_model_calls': 6, 'prior_repair_calls_today': 4,
              'model_call_count': 0, 'delivery_count': 0, 'calls': [], 'status': 'preflight',
              'request': {'txt1': PAIR.read_text(encoding='utf-8').strip(),
                          'txt2': INPUT.read_text(encoding='utf-8'), 'txt3': 0.2,
                          'text_frontend': True, 'stream': False, 'speed': 1.0},
              'reference': {'path': str(REFERENCE), 'sha256': sha(REFERENCE), 'pair_sha256': sha(PAIR)},
              'source_versions': source_versions(), 'previous_log_sha256': hashlib.sha256(old_log).hexdigest(),
              'output': None}
    write(record_path, record)
    handles = []
    current = [None]
    parts = []
    try:
        model = main.load_cosyvoice(main.DEFAULT_MODEL_DIR, main.DEFAULT_WETEXT_DIR, main.DEFAULT_MATCHA_DIR)
        assert make_plan(model.frontend)['blocks'] == plan['blocks'], 'loaded actual frontend differs from approved dry-run'
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
            call = {**block, 'executed': False, 'runtime': {}, 'consumed_segments': [],
                    'consumed_prompt': [], 'model_output_count': 0, 'status': 'preparing'}
            record['calls'].append(call)
            current[0] = call
            write(record_path, record)
            audio = []
            for output in model.inference_zero_shot(block['compiled_text'], plan['prompt_text'], str(REFERENCE),
                    stream=False, speed=1.0, text_frontend=True,
                    on_text_segment=call['consumed_segments'].append,
                    on_prompt_text=call['consumed_prompt'].append):
                speech = output['tts_speech']
                assert speech.ndim == 2 and speech.shape[0] == 1 and speech.shape[1] > 0
                assert torch.isfinite(speech).all() and float(speech.abs().max()) > 1e-4
                audio.extend([speech.cpu(), torch.zeros(1, int(0.2 * model.sample_rate), dtype=speech.dtype)])
                call['model_output_count'] += 1
            assert call['executed'] and set(call['runtime']) == set(nodes)
            assert call['model_output_count'] == 1 and call['consumed_segments'] == [block['normalized_text']]
            assert call['consumed_prompt'] == [plan['prompt_text']]
            path = HERE / f"{record['request_id']}-block-{block['index']}.wav"
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
        path = HERE / f"{record['request_id']}-完整第一自然段-full-paragraph.wav"
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
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['dry-run', 'synthesize'])
    args = parser.parse_args()
    setup()
    with patch.object(socket.socket, 'connect', blocked), patch.object(socket.socket, 'connect_ex', blocked), patch.object(socket, 'create_connection', blocked):
        if args.mode == 'synthesize':
            synthesize()
            return
        plan = make_plan(frontend())
    write(HERE / 'frontend-dry-run.json', plan)
    print(json.dumps({'block_count': plan['block_count'], 'spans': [b['source_span'] for b in plan['blocks']], 'chars': [b['characters'] for b in plan['blocks']], 'history': plan['history']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
