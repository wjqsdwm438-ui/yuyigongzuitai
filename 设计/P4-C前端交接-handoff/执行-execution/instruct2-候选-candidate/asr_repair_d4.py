"""Protocol-01 whisper transcription of the d4-repaired full paragraph (frozen tool)."""
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXEC = HERE.parent
sys.path.insert(0, str(EXEC))
from content_verify import MODEL, PARAMETERS, sha  # noqa: E402
from content_verify import transcribe as protocol_transcribe  # noqa: E402

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')


def main():
    plan = json.loads((EXEC / 'frontend-dry-run.json').read_text(encoding='utf-8-sig'))
    repair = json.loads((HERE / 'repair-d4-request.json').read_text(encoding='utf-8-sig'))
    path = HERE / repair['output']['filename']
    assert sha(path) == repair['output']['sha256']
    tool = {'model': str(MODEL), 'model_sha256': sha(MODEL / 'model.bin'),
            'faster_whisper_version': importlib.metadata.version('faster-whisper'),
            'ctranslate2_version': importlib.metadata.version('ctranslate2'),
            'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 8, 'num_workers': 1,
            'parameters': PARAMETERS, 'normalization': {'nfkc_unicode': unicodedata.unidata_version,
            'traditional_conversion': 'Windows LCMapStringEx zh-CN LCMAP_SIMPLIFIED_CHINESE',
            'windows_version': platform.version(), 'punctuation': 'Unicode P* categories only',
            'homophone_tolerance': 0, 'case_folding': False}, 'timeout_seconds_per_process': 180}
    calibration = json.loads((EXEC / 'asr-calibration.json').read_text(encoding='utf-8-sig'))
    assert tool['model_sha256'] == calibration['tool']['model_sha256']
    from faster_whisper import WhisperModel
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True, cpu_threads=8, num_workers=1)
    result = protocol_transcribe(model, path, plan['plain_text'], 'repair_d4_full')
    result['tool'] = tool
    (HERE / 'asr-repair-d4.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    c = result['comparison']
    print(json.dumps({'level': c['level'], 'exit_code': c['exit_code'], 'differences': len(c['differences']),
                      'repetitions': len(c['excess_repetition_spans'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
