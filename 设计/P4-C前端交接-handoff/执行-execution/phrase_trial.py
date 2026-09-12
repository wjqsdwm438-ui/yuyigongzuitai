"""dispatch-04 bounded A/B execution; persistent raw evidence, no implicit retry."""
import argparse
import ast
import contextlib
import copy
from datetime import datetime, timezone
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import random
import shutil
import socket
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace
from typing import Generator
from unittest.mock import patch

from p4_delivery import HERE, TTS, MODEL, REFERENCE, PAIR, sha, read, write, setup, blocked
from p4_delivery import frontend, input_identity, source_versions
from content_verify import compare, self_check, normalize

OUT = HERE / '词组连续-trial04'
SOURCE = TTS / 'cosyvoice/cli/model.py'
BACKUP = OUT / '源码备份-source-backup/model-before.py'
FILTERED = BACKUP.with_name('model-filtered.py')
BASE_SHA = '3f3b41df14d54d7364f1d92dd53397278a56b7b2b414a63f9038e58fa6505781'
PLAN_SHA = '24f53814c0f934171631f2e9c232f4e6abc34db6795edc817333220f5e9b261f'
SILENT = [1, 2, 28, 29, 55, 248, 494, 2241, 2242, 2322, 2323]
NEUTRAL = 'You are a helpful assistant.<|endofprompt|>'
DIRECTED = 'You are a helpful assistant. 请自然朗读，大数据工具实操、业财融合、企业真实场景实战各自内部连续，词内不插入停顿；业财融合与后面的思维塑造保持自然承接。<|endofprompt|>'
CONDITIONS = ['A0', 'A1', 'B0', 'B1']


def stamp():
    return datetime.now(timezone.utc).isoformat()


def fixed_block():
    assert sha(HERE / 'frontend-dry-run.json') == PLAN_SHA
    plan = read(HERE / 'frontend-dry-run.json')
    block, = [b for b in plan['blocks'] if b['index'] == 5]
    assert plan['blocks'][4] == block and block['source_span'] == [245, 319]
    assert len(block['plain_text']) == 74 and block['engine_control_ids'] == []
    assert plan['plain_text'][245 - 2:319 - 2] == block['plain_text']
    assert block['compiled_text'] == block['plain_text']
    input_identity()
    assert sha(REFERENCE) == 'cce494c6e996b380b9d9b281c42450ef5d963c8483ee1755fcb156d64982808f'
    assert sha(PAIR) == '106489a2f1cc697035910a3e0ef7cecc7854cbd2a7698900cc58c5e7ba939a25'
    return plan, block


def condition(name):
    plan, block = fixed_block()
    return {'condition': name, 'interface': 'inference_zero_shot' if name[0] == 'A' else 'inference_instruct2',
            'filter': name == 'A1', 'seed': 1986, 'zero_shot_spk_id': '',
            'text_frontend': True, 'stream': False, 'speed': 1.0, 'added_tail_seconds': .2,
            'prompt': plan['prompt_text'] if name[0] == 'A' else NEUTRAL if name == 'B0' else DIRECTED,
            'reference': str(REFERENCE), 'reference_sha256': sha(REFERENCE),
            'compiled_text': block['compiled_text'], 'normalized_text': block['normalized_text'],
            'source_span': block['source_span'], 'model_dir': str(MODEL)}


def assert_condition(item):
    assert item == condition(item['condition']), 'condition matrix mismatch'


def filtered_tokens(tokens, silent=SILENT):
    kept, deleted, runs = [], [], []
    run = 0
    for index, token in enumerate(tokens):
        run = run + 1 if token in silent else 0
        if run > 5:
            deleted.append(index)
        else:
            kept.append(token)
    start = None
    for i, token in enumerate(tokens + [999]):
        if token in silent and start is None:
            start = i
        elif token not in silent and start is not None:
            runs.append({'start_index': start, 'end_index': i, 'length': i-start})
            start = None
    return kept, deleted, runs


def patch_bytes(original):
    text = original.decode('utf-8')
    nl = '\r\n' if '\r\n' in text else '\n'
    anchor = '        self.hift_cache_dict = {}' + nl
    assert text.count(anchor) == 3 and 'silent_tokens' not in text
    parts = text.split(anchor)
    text = parts[0] + anchor + '        self.silent_tokens = []' + nl + parts[1] + anchor + '        self.silent_tokens = []' + nl + parts[2] + anchor + '        self.silent_tokens = ' + repr(SILENT) + nl + parts[3]
    anchor = '    def llm_job(self, text, prompt_text, llm_prompt_speech_token, llm_embedding, uuid):' + nl
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '        cur_silent_token_num, max_silent_token_num = 0, 5' + nl)
    anchor = '                    self.tts_speech_token_dict[uuid].append(i)' + nl
    assert text.count(anchor) == 2
    guard = nl.join(['                    if i in self.silent_tokens:', '                        cur_silent_token_num += 1',
                     '                        if cur_silent_token_num > max_silent_token_num:', '                            continue',
                     '                    else:', '                        cur_silent_token_num = 0', ''])
    return text.replace(anchor, guard + anchor).encode('utf-8')


def offline_checks(data):
    import torch
    tree = ast.parse(data)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    for cls in classes:
        init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
        assignments = [n for n in ast.walk(init) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'silent_tokens' for t in n.targets)]
        assert len(assignments) == 1
        assert ast.literal_eval(assignments[0].value) == (SILENT if cls.name == 'CosyVoice3Model' else [])
    job = next(n for n in classes[0].body if isinstance(n, ast.FunctionDef) and n.name == 'llm_job')
    assert sum(isinstance(n, ast.Continue) for n in ast.walk(job)) == 2
    class Dummy:
        pass
    scope = {'torch': torch, 'Generator': Generator, 'CosyVoice2Model': Dummy}
    exec(compile(ast.Module(body=[job], type_ignores=[]), '<actual patched llm_job>', 'exec'), scope)
    sequences = [[28,29,28,29,28,29,28,999,1,2,1,2,1,2], [1]*5, [1]*6+[999]+[2]*6, [999,888], []]
    zero = torch.zeros(1, 0, dtype=torch.int32)
    for streaming in (False, True):
        for silent in (SILENT, []):
            for sequence in sequences:
                dummy = Dummy()
                dummy.device, dummy.fp16, dummy.llm_context = 'cpu', False, contextlib.nullcontext()
                dummy.silent_tokens = silent
                dummy.llm = SimpleNamespace(inference=lambda **kw: iter(sequence), inference_bistream=lambda **kw: iter(sequence))
                for repetition in range(2):
                    dummy.tts_speech_token_dict, dummy.llm_end_dict = {'test': []}, {}
                    scope['llm_job'](dummy, (x for x in []) if streaming else zero, zero, zero, zero, 'test')
                    assert dummy.tts_speech_token_dict['test'] == filtered_tokens(sequence, silent)[0]
                    assert dummy.llm_end_dict['test']
    assert filtered_tokens(sequences[0])[:2] == ([28,29,28,29,28,999,1,2,1,2,1], [5,6,13])
    for name, key, bad in [('B0','filter',True), ('B1','zero_shot_spk_id','stale'), ('A0','seed',1987), ('B1','normalized_text','wrong'), ('A1','model_dir','D:/wrong')]:
        item = condition(name)
        item[key] = bad
        try:
            assert_condition(item)
        except AssertionError:
            continue
        raise AssertionError('invalid condition was accepted')
    self_check()
    return {'both_llm_job_branches': True, 'constructors_1_2_empty_3_final_set': True,
            'mixed_exact5_reset_empty_independent_calls': True, 'invalid_conditions_rejected': True}


def prepare():
    setup()
    OUT.mkdir(exist_ok=True)
    assert not (OUT / 'preflight.json').exists(), 'preflight already fixed'
    plan, block = fixed_block()
    assert sha(SOURCE) == BASE_SHA
    assert not (TTS / '.git').exists()
    assert sha(HERE / '0c9fbfbd47d44e2bbdd0a45049dd0f3b-block-5.wav') == 'b5738db6b19300041b7f2cc68da9ff3823ff8558fbff2adaf149ebcd0875364e'
    baseline = read(OUT / 'baseline-measurement.json')
    assert baseline['localization_complete'], 'measurement baseline localization failed; no TTS'
    assert baseline['config_sha256'] == sha(OUT / 'measurement-preregistered.json')
    assert read(OUT / 'measurement-preregistered.json')['measurement_source_sha256'] == sha(HERE / 'phrase_measure.py')
    BACKUP.parent.mkdir(exist_ok=True)
    assert not BACKUP.exists() and not FILTERED.exists()
    original = SOURCE.read_bytes()
    BACKUP.write_bytes(original)
    modified = patch_bytes(original)
    FILTERED.write_bytes(modified)
    checks = offline_checks(modified)
    try:
        SOURCE.write_bytes(modified)
        assert sha(SOURCE) == sha(FILTERED)
        raise RuntimeError('intentional pre-TTS rollback probe')
    except RuntimeError as error:
        assert str(error) == 'intentional pre-TTS rollback probe'
    finally:
        assert SOURCE.read_bytes() == modified, 'concurrent change: refusing overwrite'
        SOURCE.write_bytes(original)
    assert sha(SOURCE) == sha(BACKUP) == BASE_SHA
    with patch.object(socket.socket, 'connect', blocked), patch.object(socket, 'create_connection', blocked):
        f = frontend()
        actual = f.text_normalize(block['compiled_text'], split=True, text_frontend=True)
    assert actual == [block['normalized_text']], 'actual TN must produce exactly one block'
    weights = [MODEL / n for n in ('llm.pt','flow.pt','hift.pt','cosyvoice3.yaml','campplus.onnx','speech_tokenizer_v3.onnx','.mv','.msc','README.md')]
    weights += [MODEL / 'CosyVoice-BlankEN' / n for n in ('config.json','model.safetensors','tokenizer_config.json','vocab.json','merges.txt')]
    source = source_versions() + [{'path': str(TTS / n), 'sha256': sha(TTS / n)} for n in ('cosyvoice/llm/llm.py','cosyvoice/utils/common.py','main_cosyvoice.py')]
    result = {'created_at': stamp(), 'approval': 'dispatch-04/acceptance-04; user PLEASE IMPLEMENT THIS PLAN; root releases this batch only',
              'batch_limit': 4, 'history': {'requests': 5, 'model_blocks': 12, 'repair_calls_today': 4, 'consecutive_voice_failures': 2, 'delivery_used': 6, 'delivery_limit': 6},
              'future_limits': {'repeat': 0, 'accounting_hotfix': 0, 'combined': 0, 'completion': 0},
              'plan_sha256': PLAN_SHA, 'block': block, 'dry_run_segments': actual, 'conditions': [condition(n) for n in CONDITIONS],
              'backup': str(BACKUP), 'filtered_backup': str(FILTERED), 'before_sha256': sha(BACKUP), 'patched_sha256': sha(FILTERED),
              'rollback_probe_restored_sha256': sha(SOURCE), 'offline_checks': checks, 'source_versions': source,
              'weights': [{'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in weights],
              'model_version': 'local .mv Revision:master,CreatedAt:1765940913; explicit file hashes, not latest upstream identity',
              'measurement_config_sha256': sha(OUT / 'measurement-preregistered.json'), 'baseline_measurement_sha256': sha(OUT / 'baseline-measurement.json'),
              'request_log_sha256': sha(TTS / 'request_records.jsonl'),
              'task_model': {'requested': 'Astra/xhigh', 'actual_metadata': 'not independently readable'},
              'skills': ['utf8-text-read','systematic-debugging','qwen3-asr-local']}
    write(OUT / 'preflight.json', result)
    (OUT / 'silent-filter.patch').write_bytes(''.join(difflib.unified_diff(original.decode().replace('\r\n', '\n').splitlines(True), modified.decode().replace('\r\n', '\n').splitlines(True), fromfile='model-before.py', tofile='model-filtered.py')).encode('utf-8'))
    print(json.dumps({'preflight': 'passed', 'model_blocks': 1, 'budget': 4}, ensure_ascii=False))


def current_sources(pre, filtered=False):
    for item in pre['source_versions']:
        expected = pre['patched_sha256'] if Path(item['path']) == SOURCE and filtered else item['sha256']
        assert sha(item['path']) == expected, f"source identity changed: {item['path']}"


def synthesize(name):
    setup()
    import numpy as np
    import soundfile as sf
    import torch
    import main_cosyvoice as main
    from cosyvoice.cli import model as module
    from cosyvoice.utils.common import set_all_random_seed
    pre = read(OUT / 'preflight.json')
    assert_condition(params := condition(name))
    current_sources(pre, params['filter'])
    assert sha(OUT / 'measurement-preregistered.json') == pre['measurement_config_sha256']
    assert torch.cuda.is_available(), 'CPU synthesis prohibited'
    path = OUT / (name + '.json')
    assert not path.exists(), 'condition already attempted; no retry'
    record = {'condition': name, 'parameters': params, 'started_at': stamp(), 'pid': os.getpid(),
              'python': sys.executable, 'module_file': module.__file__, 'loaded_source_sha256': sha(module.__file__),
              'preflight_sha256': sha(OUT / 'preflight.json'), 'status': 'loading', 'executed': False,
              'runtime': {}, 'raw_tokens': [], 'retained_tokens': [], 'output': None, 'frontend': [], 'torch_load_paths': []}
    write(path, record)
    start = time.monotonic()
    handles = []
    try:
        assert Path(module.__file__).resolve() == SOURCE.resolve()
        real_load = torch.load
        def capture_load(f, *args, **kw):
            if isinstance(f, (str, Path)):
                record['torch_load_paths'].append(str(Path(f).resolve()))
            return real_load(f, *args, **kw)
        with patch.object(torch, 'load', capture_load):
            model = main.load_cosyvoice(MODEL, main.DEFAULT_WETEXT_DIR, main.DEFAULT_MATCHA_DIR)
        assert Path(model.model_dir).resolve() == MODEL.resolve()
        assert model.model.flow.input_frame_rate == 25 and model.model.flow.token_mel_ratio == 2
        assert model.frontend.text_normalize(params['compiled_text'], split=True, text_frontend=True) == [params['normalized_text']]
        assert getattr(model.model, 'silent_tokens', []) == (SILENT if params['filter'] else [])
        model.frontend.spk2info.clear()
        record['model'] = {'directory': str(MODEL.resolve()), 'class': type(model).__name__, 'model_class': type(model.model).__name__,
                           'llm_job_owner': model.model.llm_job.__func__.__qualname__, 'tts_owner': model.model.tts.__func__.__qualname__,
                           'token_frame_rate': model.model.flow.input_frame_rate, 'token_mel_ratio': model.model.flow.token_mel_ratio,
                           'token_hop_len': model.model.token_hop_len, 'sample_rate': model.sample_rate,
                           'fp16': model.fp16, 'sampling': str(model.model.llm.sampling),
                           'inference_defaults': str(__import__('inspect').signature(model.model.llm.inference)),
                           'campplus_providers': model.frontend.campplus_session.get_providers(),
                           'speech_tokenizer_providers': model.frontend.speech_tokenizer_session.get_providers(),
                           'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__}
        def tensors(v):
            if isinstance(v, torch.Tensor):
                return [v]
            if isinstance(v, dict):
                return [t for x in v.values() for t in tensors(x)]
            if isinstance(v, (list, tuple)):
                return [t for x in v for t in tensors(x)]
            return []
        def hook(key):
            def inspect(node, args, kwargs):
                inputs = tensors((args, kwargs))
                assert inputs and all(t.device.type == 'cuda' for t in inputs)
                assert all(p.device.type == 'cuda' for p in node.parameters())
                runtime = record['runtime'].setdefault(key, {'calls': 0, 'input_devices': sorted({str(t.device) for t in inputs}),
                           'input_dtypes': sorted({str(t.dtype) for t in inputs}), 'all_parameters_cuda': True})
                runtime['calls'] += 1
                if key == 'f0':
                    assert all(t.dtype == torch.float64 for t in inputs)
                    assert all(p.dtype == torch.float64 for p in node.parameters())
            return inspect
        nodes = {'llm_qwen': model.model.llm.llm.model, 'flow_estimator': model.model.flow.decoder.estimator,
                 'hift_conv': model.model.hift.conv_pre, 'f0': model.model.hift.f0_predictor}
        for key, node in nodes.items():
            handles.append(node.register_forward_pre_hook(hook(key), with_kwargs=True))
        real_llm = model.model.llm.inference
        def raw(**kwargs):
            for token in real_llm(**kwargs):
                record['raw_tokens'].append(int(token))
                yield token
        model.model.llm.inference = raw
        real_wave = model.model.token2wav
        def token_wave(*args, **kwargs):
            record['retained_tokens'].extend(kwargs['token'].flatten().tolist())
            return real_wave(*args, **kwargs)
        model.model.token2wav = token_wave
        real_frontend = getattr(model.frontend, 'frontend_zero_shot' if name[0] == 'A' else 'frontend_instruct2')
        def frontend_capture(*args, **kwargs):
            data = real_frontend(*args, **kwargs)
            assert len(record['frontend']) == 0, 'more than one frontend block'
            entry = {'text': args[0], 'prompt': args[1], 'reference': args[2], 'sample_rate': args[3], 'speaker_id': args[4],
                     'speaker_cache_keys': list(model.frontend.spk2info), 'fields': {}}
            for k, v in data.items():
                if isinstance(v, torch.Tensor):
                    a = v.detach().cpu().contiguous()
                    entry['fields'][k] = {'shape': list(v.shape), 'dtype': str(v.dtype), 'device': str(v.device),
                                         'sha256': hashlib.sha256(a.numpy().tobytes()).hexdigest()}
                    if k in ('text','prompt_text','llm_prompt_speech_token','flow_prompt_speech_token'):
                        entry['fields'][k]['tokens'] = a.flatten().tolist()
            record['frontend'].append(entry)
            return data
        setattr(model.frontend, 'frontend_zero_shot' if name[0] == 'A' else 'frontend_instruct2', frontend_capture)
        real_tts = model.model.tts
        def tts_capture(*args, **kwargs):
            assert not record['executed'], 'more than one model block prohibited'
            assert sum(int(read(p).get('executed', False)) for p in OUT.glob('[AB][01].json')) < 4
            assert model.frontend.spk2info == {}
            set_all_random_seed(1986)
            record.update(seed_applied=1986, seed_applied_at=stamp(), executed=True, status='synthesizing')
            write(path, record)
            yield from real_tts(*args, **kwargs)
        model.model.tts = tts_capture
        generator = getattr(model, params['interface'])(params['compiled_text'], params['prompt'], str(REFERENCE),
                      zero_shot_spk_id='', stream=False, speed=1.0, text_frontend=True)
        outputs = list(generator)
        assert len(outputs) == 1 and set(record['runtime']) == set(nodes)
        speech = outputs[0]['tts_speech']
        assert speech.shape[0] == 1 and speech.shape[1] > 0 and torch.isfinite(speech).all() and float(speech.abs().max()) > 1e-4
        expected, deleted, runs = filtered_tokens(record['raw_tokens'], SILENT if params['filter'] else [])
        assert expected == record['retained_tokens']
        record.update(deleted_raw_indices=deleted, silent_runs=runs)
        wav = OUT / (name + '.wav')
        assert not wav.exists()
        main.save_wav_safe(wav, torch.cat([speech.cpu(), torch.zeros(1,4800,dtype=speech.dtype)], dim=1), 24000)
        pcm, rate = sf.read(wav,dtype='int16')
        assert rate == 24000 and np.all(pcm[-4800:] == 0)
        record['output'] = {'path': str(wav), 'sha256': sha(wav), 'frames': len(pcm), 'sample_rate': rate, 'seconds': len(pcm)/rate, 'added_silence_samples':4800}
        record['status'] = 'success'
    except Exception as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        raise
    finally:
        for handle in handles:
            handle.remove()
        record.update(finished_at=stamp(), elapsed_seconds=round(time.monotonic()-start,3))
        write(path, record)


def run_all():
    pre = read(OUT / 'preflight.json')
    assert not any(OUT.glob('[AB][01].json')), 'batch already started; no automatic repeat'
    current_sources(pre)
    for item in pre['weights']:
        assert sha(item['path']) == item['sha256']
    assert sha(SOURCE) == sha(BACKUP) == pre['before_sha256']
    receipt = {'started_at': stamp(), 'limit': 4, 'attempts': [], 'status': 'running'}
    failed_groups = set()
    try:
        for name in CONDITIONS:
            if name[0] in failed_groups:
                receipt['attempts'].append({'condition': name,'status':'not_sent_group_stopped'})
                continue
            assert sha(SOURCE) == BASE_SHA
            if name == 'A1':
                SOURCE.write_bytes(FILTERED.read_bytes())
            try:
                command = [sys.executable, '-X','utf8','-B',str(Path(__file__).resolve()), 'synthesize','--condition',name]
                with (OUT / (name + '.log')).open('w',encoding='utf-8') as log:
                    process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=300)
                receipt['attempts'].append({'condition':name,'command':command,'exit_code':process.returncode})
                if process.returncode:
                    failed_groups.add(name[0])
                    if not (OUT / (name + '.json')).exists() or not read(OUT / (name + '.json'))['executed']:
                        raise RuntimeError('shared pre-TTS failure; stop both groups')
            finally:
                if name == 'A1':
                    assert sha(SOURCE) == pre['patched_sha256'], 'unexpected concurrent source change; do not overwrite'
                    SOURCE.write_bytes(BACKUP.read_bytes())
                    receipt['after_A1_restored_sha256'] = sha(SOURCE)
                write(OUT / 'batch-receipt.json', receipt)
            update_state()
        receipt['status'] = 'complete' if not failed_groups else 'partial_failed'
    except Exception as error:
        receipt.update(status='stopped', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        receipt.update(finished_at=stamp(), restored_sha256=sha(SOURCE), executed=sum(int(read(p)['executed']) for p in OUT.glob('[AB][01].json')))
        write(OUT / 'batch-receipt.json',receipt)
        update_state()
        assert sha(SOURCE) == BASE_SHA


def update_state():
    count = sum(int(read(p)['executed']) for p in OUT.glob('[AB][01].json'))
    path = HERE / '恢复-state.md'
    text = path.read_text(encoding='utf-8')
    import re
    text = re.sub(r'当前本批实际TTS \d/4、剩余\d',f'当前本批实际TTS {count}/4、剩余{4-count}',text)
    path.write_text(text,encoding='utf-8')


def content_inputs():
    assert not (OUT / 'qwen-inputs.json').exists()
    inputs = []
    directory = OUT / '独立核验-inputs'
    directory.mkdir(exist_ok=True)
    successful = [read(p) for p in sorted(OUT.glob('[AB][01].json')) if read(p).get('output')]
    assert successful, 'N=0: do not run Qwen controls'
    _, block = fixed_block()
    cases = [(r['condition'],r['output']['path'],block['plain_text'],r['output']['sha256']) for r in successful]
    cases += [(c['label'],c['audio_path'],c['expected'],c['audio_sha256']) for c in read(HERE/'asr-calibration.json')['cases']]
    for role,path,expected,identity in cases:
        assert sha(path)==identity
        dest=directory/(role+'.wav')
        assert not dest.exists()
        shutil.copyfile(path,dest)
        assert sha(dest)==identity
        inputs.append({'role':role,'source':str(path),'copy':str(dest),'expected':identity,'text':expected})
    write(OUT/'qwen-inputs.json',inputs)


def qwen_content():
    def load(path):
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    receipt = load(OUT/'qwen-run-receipt.json')
    assert receipt['status']=='completed' and receipt['exit_code']==0
    config=read(HERE/'qwen-tool-config.json')
    assert sha(config['wrapper_path'])==config['wrapper_sha256']
    assert sha(config['runner_path'])==config['runner_sha256']
    for item in config['model_files']:
        assert sha(item['path'])==item['sha256']
    inputs=read(OUT/'qwen-inputs.json')
    expected={r['condition']:fixed_block()[1]['plain_text'] for p in OUT.glob('[AB][01].json') if (r:=read(p)).get('output')}
    assert expected, 'N=0: content batch must not run'
    expected.update({c['label']:c['expected'] for c in read(HERE/'asr-calibration.json')['cases']})
    assert {i['role'] for i in inputs}==set(expected) and len(inputs)==len(expected)
    output=OUT/'独立核验-qwen'
    batch=load(output/'batch_summary.json')
    assert batch['total']==batch['success']==len(inputs) and batch['cached']==batch['failed']==0
    assert batch['model_device'].startswith('cuda')
    cases={}
    for item in inputs:
        name=item['role']
        assert sha(item['source'])==sha(item['copy'])==item['expected']
        assert item['text']==expected[name]
        files=[output/(name+'.qwen3.'+suffix) for suffix in ('txt','json','report.md')]
        assert all(p.exists() and p.stat().st_size for p in files)
        result=load(files[1])
        qwen_identity(result,item)
        assert Path(result['model']).resolve()==Path(config['model_path']).resolve()
        runner=Path(config['runner_path'])
        assert result['tool_fingerprint'].lower()==sha(runner.with_name('transcribe_file.py'))+':'+sha(runner)
        assert result['backend']=='transformers' and result['model_device'].startswith('cuda')
        assert result['language']=='Chinese' and result['max_new_tokens']==1024 and result['max_inference_batch_size']==8
        assert result['ok'] and result['status']=='candidate' and result['text']==files[0].read_text(encoding='utf-8').strip()
        cases[name]={'comparison':compare(expected[name],[{'text':result['text']}]), 'audio_sha256':item['expected'],
                     'raw_json':str(files[1]), 'raw_json_sha256':sha(files[1]), 'raw_text':result['text']}
    assert cases['known_bad_12j_sentence2']['comparison']['exit_code']!=0, 'known bad control falsely accepted'
    assert all(cases[n]['comparison']['exit_code']==0 for n in ('human_reference_good','user_accepted_g1_good')), 'normal controls failed'
    # RT7 uses the real previous output as a mismatched fixture for the new audio.
    old=load(HERE/'独立核验-qwen/current_full.qwen3.json')
    try:
        qwen_identity(old,next(i for i in inputs if i['role'] in CONDITIONS))
    except AssertionError:
        old_rejected=True
    else:
        raise AssertionError('old ASR wrongly accepted for new audio')
    return {'cases':cases, 'batch':batch, 'normal_false_positives':0, 'bad_false_negatives':0,
            'old_asr_mismatch_rejected':old_rejected,
            'scope':'同批两正常/一坏小样本；ASR内容候选不判读音、声调与韵律。'}


def qwen_identity(result,item):
    assert Path(result['audio_path']).resolve()==Path(item['copy']).resolve(), 'Qwen actual input path mismatch'
    assert result['audio_sha256'].lower()==result['request_audio_sha256'].lower()==item['expected'], 'Qwen audio identity mismatch'


def audit(need_blind=True):
    from phrase_measure import measure
    import soundfile as sf
    import numpy as np
    setup()
    pre=read(OUT/'preflight.json')
    _,block=fixed_block()
    current_sources(pre)
    assert sha(SOURCE)==sha(BACKUP)==pre['before_sha256']==pre['rollback_probe_restored_sha256']==BASE_SHA
    assert sha(FILTERED)==pre['patched_sha256'] and FILTERED.read_bytes()==patch_bytes(BACKUP.read_bytes())
    offline_checks(FILTERED.read_bytes())
    for item in pre['weights']:
        assert sha(item['path'])==item['sha256']
    assert sha(OUT/'measurement-preregistered.json')==pre['measurement_config_sha256']
    assert sha(HERE/'phrase_measure.py')==read(OUT/'measurement-preregistered.json')['measurement_source_sha256']
    assert sha(OUT/'baseline-measurement.json')==pre['baseline_measurement_sha256']
    baseline=read(OUT/'baseline-measurement.json')
    assert sha(baseline['audio_path'])==baseline['audio_sha256'] and baseline['localization_complete']
    with contextlib.redirect_stdout(io.StringIO()),patch.object(socket.socket,'connect',blocked),patch.object(socket,'create_connection',blocked):
        assert frontend().text_normalize(block['compiled_text'],split=True,text_frontend=True)==pre['dry_run_segments']==[block['normalized_text']]
    receipt=read(OUT/'batch-receipt.json')
    assert receipt['restored_sha256']==BASE_SHA
    records={p.stem:read(p) for p in OUT.glob('[AB][01].json')}
    count=sum(int(r['executed']) for r in records.values())
    assert count==receipt['executed']<=pre['batch_limit']==4
    assert sha(TTS/'request_records.jsonl')==pre['request_log_sha256'], 'historical request log changed'
    assert pre['history']=={'requests':5,'model_blocks':12,'repair_calls_today':4,'consecutive_voice_failures':2,'delivery_used':6,'delivery_limit':6}
    issues=[]
    if set(records)!=set(CONDITIONS): issues.append('missing condition(s)')
    measurements={}
    token_acoustics={}
    for name,r in records.items():
        assert_condition(r['parameters'])
        assert r['preflight_sha256']==sha(OUT/'preflight.json')
        assert Path(r['python']).resolve()==Path('D:/anaconda3/envs/cosyvoice/python.exe').resolve()
        assert Path(r['module_file']).resolve()==SOURCE.resolve()
        assert r['loaded_source_sha256']==(pre['patched_sha256'] if name=='A1' else BASE_SHA)
        assert r['started_at']>=pre['created_at']
        if r['status']!='success' or not r['output']:
            issues.append(name+': failed output'); continue
        assert r['executed'] and r['seed_applied']==1986
        assert set(r['runtime'])=={'llm_qwen','flow_estimator','hift_conv','f0'}
        for node in r['runtime'].values():
            assert node['calls']>0 and node['input_devices']==['cuda:0'] and node['all_parameters_cuda']
        assert r['runtime']['f0']['input_dtypes']==['torch.float64']
        assert r['model']['token_frame_rate']==25 and r['model']['token_mel_ratio']==2
        assert r['model']['model_class']=='CosyVoice3Model' and r['model']['llm_job_owner']=='CosyVoiceModel.llm_job'
        assert r['model']['tts_owner']=='CosyVoice2Model.tts'
        for weight in ('llm.pt','flow.pt','hift.pt'):
            assert str((MODEL/weight).resolve()) in r['torch_load_paths']
        assert all(not p.endswith('llm.rl.pt') for p in r['torch_load_paths'])
        f,=r['frontend']
        assert f['text']==block['normalized_text'] and f['prompt']==r['parameters']['prompt']
        assert f['speaker_id']=='' and f['speaker_cache_keys']==[] and f['reference']==str(REFERENCE)
        assert ('llm_prompt_speech_token' in f['fields'])==(name[0]=='A')
        kept,deleted,runs=filtered_tokens(r['raw_tokens'],SILENT if name=='A1' else [])
        assert kept==r['retained_tokens'] and deleted==r['deleted_raw_indices'] and runs==r['silent_runs']
        audio=Path(r['output']['path'])
        assert sha(audio)==r['output']['sha256']
        pcm,rate=sf.read(audio,dtype='int16')
        assert rate==24000 and pcm.ndim==1 and len(pcm)==r['output']['frames'] and np.all(pcm[-4800:]==0)
        m=read(OUT/(name+'-measurement.json'))
        assert m['audio_sha256']==sha(audio) and m['processed_full_file'] and m['config_sha256']==pre['measurement_config_sha256']
        actual=measure(audio,block['plain_text'],m['raw_segments'])
        assert actual=={k:m[k] for k in actual}, 'measurement replay differs'
        raw=read(OUT/(name+'-timing-raw.json'))
        assert raw['raw_segments']==m['raw_segments'] and raw['audio_sha256']==sha(audio)
        if not m['localization_complete']: issues.append(name+': localization insufficient')
        measurements[name]=m
        nominal=(len(pcm)-4800)/rate
        assert abs(nominal-len(r['retained_tokens'])/25)<1/rate
        _,potential_deleted,silent_runs=filtered_tokens(r['raw_tokens'])
        token_acoustics[name]={'raw_token_count':len(r['raw_tokens']),'retained_token_count':len(r['retained_tokens']),
            'actual_deleted_count':len(r['deleted_raw_indices']),'potential_deleted_count_with_final_set':len(potential_deleted),
            'maximum_raw_silent_run':max((s['length'] for s in silent_runs),default=0),
            'token_clock_frame_samples':960,'actual_output_samples_match_token_clock':True,
            'runs':[dict(s,nominal_original_seconds=[s['start_index']/25,s['end_index']/25]) for s in silent_runs],
            'mapping_boundary':'Token/mel output clock only; flow/HiFT receptive fields and ASR timing uncertainty prevent phoneme attribution.',
            'target_overlaps':[{'text':t['text'],'candidate_seconds':t['seconds'],
                 'raw_silent_runs_overlapping':[s for s in silent_runs if t['seconds'] and s['start_index']/25 < t['seconds'][1] and t['seconds'][0] < s['end_index']/25]}
                 for t in m['targets']]}
    for group in ('A','B'):
        if group+'0' in records and group+'1' in records and records[group+'0']['output'] and records[group+'1']['output']:
            x,y=records[group+'0'],records[group+'1']
            for field in ('text','flow_prompt_speech_token','prompt_speech_feat','flow_embedding','llm_embedding'):
                assert x['frontend'][0]['fields'][field]==y['frontend'][0]['fields'][field], 'within-group reference/TN contamination'
            if group=='A':
                assert x['frontend']==y['frontend']
                if x['raw_tokens']!=y['raw_tokens']: issues.append('A raw token sequence differs: not strictly paired')
            else:
                assert x['frontend'][0]['fields']['prompt_text']!=y['frontend'][0]['fields']['prompt_text']
    content=qwen_content()
    for name in records:
        if name in content['cases'] and content['cases'][name]['comparison']['exit_code']:
            issues.append(name+': unresolved content difference')
    if need_blind:
        mapping=read(OUT/'盲标映射-private.json')
        valid=[n for n in records if records[n]['output'] and content['cases'][n]['comparison']['exit_code']==0]
        assert set(mapping.values())==set(valid) and len(mapping)==len(valid)
        for label,name in mapping.items():
            assert sha(OUT/'盲听-listening'/(label+'.wav'))==records[name]['output']['sha256']
        assert (OUT/'盲听-listening/听审清单.md').exists()
    content_passed=[name for name in records if name in content['cases'] and content['cases'][name]['comparison']['exit_code']==0]
    return {'level':'通过' if not issues else '嫌疑','exit_code':0 if not issues else 2,'unresolved':issues,
            'actual_calls':count,'remaining':4-count,'history_total_requests':5+count,'history_total_model_blocks':12+count,
            'batch_complete_success':not issues and len(records)==4,
            'listening_subset':{'count':len(content_passed),'conditions_private':content_passed,
                                'boundary':'仅内容通过子集；批次未完整成功，缺对组不判效果。'},
            'content':content,'measurements':measurements,'token_acoustics':token_acoustics,
            'A_raw_equal':records['A0']['raw_tokens']==records['A1']['raw_tokens'] if all(n in records for n in ('A0','A1')) else None,
            'A_audio_byte_equal':records['A0']['output']['sha256']==records['A1']['output']['sha256'] if all(n in records and records[n]['output'] for n in ('A0','A1')) else None,
            'group_conclusions':{'A':'证据不足：用户盲听待定；未运行第二seed','B':'证据不足：用户盲听待定；未运行第二seed'},
            'user_listening':'未判定，P5不放行','source_restored':True}


def deliver():
    result=audit(need_blind=False)
    write(OUT/'trial04-result.json',result)
    valid=[n for n in CONDITIONS if n in result['content']['cases'] and result['content']['cases'][n]['comparison']['exit_code']==0]
    assert valid and all(s.endswith(': unresolved content difference') for s in result['unresolved']), 'shared automatic gates unresolved: do not deliver blind audio'
    assert not (OUT/'盲标映射-private.json').exists(), 'blind mapping already exists'
    random.SystemRandom().shuffle(valid)
    mapping={f'听样-{i+1:02d}':name for i,name in enumerate(valid)}
    write(OUT/'盲标映射-private.json',mapping)
    directory=OUT/'盲听-listening'
    directory.mkdir(exist_ok=True)
    lines=['# 词组连续听审\n','以下为本轮条件隐藏听样；请听完整块，再记录声音判断。自动内容核验已完成，用户结论留空。\n',
           '每项可反馈：通过、错读、停顿异常、不确定。原全文会计错读不在本轮块中。\n']
    for label,name in mapping.items():
        r=read(OUT/(name+'.json'))
        shutil.copyfile(r['output']['path'],directory/(label+'.wav'))
        m=result['measurements'][name]
        lines.extend([f'## {label}\n',f'![{label}]({(directory/(label+".wav")).as_posix()})\n',
                      '| 时间段（秒） | 词组或承接 | 期望 | 允许替代 | 用户结论 |','|---|---|---|---|---|'])
        for t in m['targets']:
            a,b=t['seconds']
            expectation='词组内部连续，与思维塑造自然承接' if '思维塑造' in t['text'] else '内部完整连续，避免不恰当断开'
            lines.append(f"| {max(0,a-.12):.2f}—{min(m['seconds'],b+.12):.2f} | {t['text']} | {expectation} | 无 | 待用户 |")
        for boundary,label_text in [(46,'实操／业财融合思维塑造'),(54,'思维塑造／企业真实场景实战')]:
            b=next(x for x in m['boundaries'] if x['normalized_offset']==boundary)
            if b['before'] and b['after']:
                lines.append(f"| {b['before'][0]:.2f}—{b['after'][1]:.2f} | {label_text} | 三项列举关系清楚，保留必要语义停顿 | 无 | 待用户 |")
        lines.append(f"| 0—{m['seconds']:.2f} | 完整块及列举/句间承接 | 词组间保留必要语义停顿，全文无新错读/漏读/重复 | 无 | 待用户 |\n")
    (directory/'听审清单.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'blind_audio_count':len(mapping),'listening_checklist':str(directory/'听审清单.md')},ensure_ascii=False))


def verify_trial():
    result={'level':'工具错误','exit_code':3,'unresolved':[]}
    try:
        result=audit()
    except AssertionError as error:
        result.update(level='失败',exit_code=1,error=str(error),traceback=traceback.format_exc())
    except Exception as error:
        result.update(error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    result['command']="& 'D:/anaconda3/envs/cosyvoice/python.exe' -X utf8 -B '"+str(HERE/'verify.py')+"' --batch trial04; exit $LASTEXITCODE"
    write(OUT/'trial04-result.json',result)
    print(json.dumps({k:result[k] for k in ('level','exit_code')} | {'unresolved_count':len(result['unresolved']),
                      'detail_path':str(OUT/'trial04-result.json')},ensure_ascii=False))
    return result['exit_code']


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['prepare','run','synthesize','content-inputs','deliver'])
    parser.add_argument('--condition',choices=CONDITIONS)
    args=parser.parse_args()
    if args.mode=='prepare': prepare()
    elif args.mode=='run': run_all()
    elif args.mode=='content-inputs': content_inputs()
    elif args.mode=='deliver': deliver()
    else:
        with patch.object(socket.socket,'connect',blocked), patch.object(socket.socket,'connect_ex',blocked), patch.object(socket,'create_connection',blocked):
            synthesize(args.condition)


if __name__=='__main__':
    main()
