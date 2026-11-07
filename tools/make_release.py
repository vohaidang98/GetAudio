"""Tạo thư mục phát hành để đặt lên thư mục chia sẻ LAN.

Chạy:
  python tools\\make_release.py <file cài đặt .exe> <phiên bản> <thư mục đích> [ghi chú]

Ví dụ:
  python tools\\make_release.py D:\\Code\\GetAudio-Setup-1.3.0.exe 1.3.0 D:\\Code\\_CAP_NHAT\\GetAudio "Sửa lỗi"
Kết quả: thư mục đích có file cài đặt và version.json (kèm SHA-256).
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

if len(sys.argv) < 4:
    raise SystemExit(__doc__)
installer = Path(sys.argv[1])
version = sys.argv[2]
dest = Path(sys.argv[3])
notes = sys.argv[4] if len(sys.argv) > 4 else ''
if not installer.is_file():
    raise SystemExit(f'Không thấy file: {installer}')
dest.mkdir(parents=True, exist_ok=True)
digest = hashlib.sha256()
with installer.open('rb') as f:
    for chunk in iter(lambda: f.read(1 << 20), b''):
        digest.update(chunk)
target = dest / installer.name
if installer.resolve() != target.resolve():
    shutil.copy2(installer, target)
manifest = {'version': version, 'file': installer.name, 'sha256': digest.hexdigest(), 'notes': notes}
(dest / 'version.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print('Da tao:', dest / 'version.json')
