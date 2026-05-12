import json
import threading
from pathlib import Path

_lock = threading.Lock()
_log_path = Path('.clause_probe_log.jsonl')


def clause_probe(cid, func):
    """Evaluate func(), record boolean result for clause id, and return original value."""
    try:
        val = func()
    except Exception:
        # if evaluation fails, record as False and re-raise
        _record(cid, False)
        raise
    b = bool(val)
    _record(cid, b)
    return val


def _record(cid, b):
    line = json.dumps({"id": cid, "value": bool(b)}, ensure_ascii=False)
    with _lock:
        with _log_path.open('a', encoding='utf-8') as f:
            f.write(line + '\n')


def reset_log():
    try:
        _log_path.unlink()
    except Exception:
        pass
