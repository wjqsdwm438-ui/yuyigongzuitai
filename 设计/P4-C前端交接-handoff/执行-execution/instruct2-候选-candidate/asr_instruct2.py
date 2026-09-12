"""Protocol-01 whole-audio transcription for the instruct2 candidate (frozen tool, no parameter change)."""
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
    plan = json.loads((EXEC / 'frontend-dry-run.json').read_text(encoding='utf-8'))
    request = json.loads((HERE / 'instruct2-delivery-request.json').read_text(encoding='utf-8'))
    assert request['status'] == 'success', 'instruct2 delivery did not succeed'
    path = HERE / request['output']['filename']
    assert sha(path) == request['output']['sha256'], 'candidate audio identity mismatch'
    tool = {'model': str(MODEL), 'model_sha256': sha(MODEL / 'model.bin'),
            'faster_whisper_version': importlib.metadata.version('faster-whisper'),
            'ctranslate2_version': importlib.metadata.version('ctranslate2'),
            'device': 'cpu', 'compute_type': 'int8', 'cpu_threads': 8, 'num_workers': 1,
            'parameters': PARAMETERS, 'normalization': {'nfkc_unicode': unicodedata.unidata_version,
            'traditional_conversion': 'Windows LCMapStringEx zh-CN LCMAP_SIMPLIFIED_CHINESE',
            'windows_version': platform.version(), 'punctuation': 'Unicode P* categories only',
            'homophone_tolerance': 0, 'case_folding': False}, 'timeout_seconds_per_process': 180}
    calibration = json.loads((EXEC / 'asr-calibration.json').read_text(encoding='utf-8'))
    assert tool['model_sha256'] == calibration['tool']['model_sha256'] and tool['parameters'] == calibration['tool']['parameters'], 'protocol01 tool drifted'
    from faster_whisper import WhisperModel
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True, cpu_threads=8, num_workers=1)
    result = protocol_transcribe(model, path, plan['plain_text'], 'instruct2_candidate')
    result['tool'] = tool
    (HERE / 'asr-instruct2.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    comparison = result['comparison']
    print(json.dumps({'level': comparison['level'], 'exit_code': comparison['exit_code'],
                      'differences': len(comparison['differences']),
                      'excess_repetition_spans': len(comparison['excess_repetition_spans'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
