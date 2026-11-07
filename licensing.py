"""Kích hoạt bằng một mã duy nhất. Trong app chỉ lưu mã băm (PBKDF2), không lưu mã gốc.

Đặt CODE_HASH bằng: python tools\\make_hash.py  (nhập mã, chữ hiện dấu *).
"""
import hashlib
import hmac
import json
import os
from pathlib import Path

SALT = b'GetAudio|activation|v1'
ROUNDS = 200_000
CODE_HASH = '1f66b4a86003c5710e62ef8a40b85d2dcfee0274cdb038d451fa8bf476d25919'


def normalize(code):
    return str(code).strip()


def hash_code(code):
    return hashlib.pbkdf2_hmac('sha256', normalize(code).encode('utf-8'), SALT, ROUNDS).hex()


def _store():
    base = os.environ.get('APPDATA') or str(Path.home())
    return Path(base) / 'GetAudio' / 'license.json'


def verify(code):
    return bool(CODE_HASH) and hmac.compare_digest(hash_code(code), CODE_HASH)


def is_activated():
    if not CODE_HASH:
        return False
    try:
        data = json.loads(_store().read_text('utf-8'))
        return hmac.compare_digest(str(data.get('hash', '')), CODE_HASH)
    except Exception:
        return False


def activate(code):
    if not verify(code):
        return False
    path = _store()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'hash': CODE_HASH}), 'utf-8')
    return True
