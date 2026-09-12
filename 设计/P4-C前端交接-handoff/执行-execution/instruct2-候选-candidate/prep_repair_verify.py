"""Verify the d4-repaired full paragraph: identity, protocol-01 whisper, Qwen independent batch, block-3 spot checks."""
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
sys.path.insert(0, str(EXEC))
from content_verify import MODEL, PARAMETERS, compare, normalize, sha  # noqa: E402

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    plan = read(EXEC / 'frontend-dry-run.json')
    repair = read(HERE / 'repair-d4-request.json')
    assert repair['status'] == 'success'
    full = HERE / repair['output']['filename']
    assert sha(full) == repair['output']['sha256'], 'repaired audio identity mismatch'
    summary = {'schema_version': 'p4-repair-d4-result.v1', 'request_id': repair['request_id'],
               'checks': {}, 'unresolved': []}
    # Qwen wrapper/model identity
    config = read(EXEC / 'qwen-tool-config.json')
    assert sha(config['wrapper_path']) == config['wrapper_sha256']
    assert sha(config['runner_path']) == config['runner_sha256']
    for mf in config['model_files']:
        assert sha(mf['path']) == mf['sha256']
    # inputs for the Qwen batch: repaired full + 2 good + 1 bad
    in_dir = HERE / 'repair-d4-inputs'
    in_dir.mkdir(exist_ok=True)
    import shutil
    shutil.copyfile(full, in_dir / 'repair_d4_full.wav')
    for name in ('human_reference_good.wav', 'user_accepted_g1_good.wav', 'known_bad_12j_sentence2.wav'):
        shutil.copyfile(EXEC / '独立核验-inputs' / name, in_dir / name)
    summary['checks']['prepared_inputs'] = '4 files in repair-d4-inputs'
    write(HERE / 'repair-d4-result.json', summary)
    print(json.dumps({'stage': 'prepared', 'full_sha256': repair['output']['sha256'],
                      'inputs': sorted(p.name for p in in_dir.iterdir())}, ensure_ascii=False))


if __name__ == '__main__':
    main()
