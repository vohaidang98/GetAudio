"""Tạo mã băm từ mã kích hoạt để dán vào licensing.CODE_HASH.

Chạy:  python tools\\make_hash.py
Mã nhập vào sẽ hiện dấu * và không được lưu ở đâu cả.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import licensing  # noqa: E402

code = getpass.getpass('Nhập mã kích hoạt: ')
again = getpass.getpass('Nhập lại để xác nhận: ')
if not code.strip() or code != again:
    raise SystemExit('Hai lần nhập không khớp hoặc để trống.')
print('CODE_HASH =', licensing.hash_code(code))
