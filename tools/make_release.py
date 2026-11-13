"""Chuẩn bị file để đăng lên GitHub Release (app tự cập nhật từ Release mới nhất).

Chạy:
  python tools\\make_release.py <file .exe đã build> <phiên bản> [thư mục đích]

Ví dụ:
  python tools\\make_release.py "dist\\Gen Audio 4.2.1.exe" 4.2.1
Kết quả (mặc định trong release\\<phiên bản>):
  - GetAudio-4.2.1.exe          (file app, tên không dấu cách)
  - GetAudio-4.2.1.exe.sha256   (mã SHA-256 để app kiểm tra file tải về)
Sau đó tạo Release có tag v4.2.1 và đính kèm cả 2 file, ví dụ:
  gh release create v4.2.1 release\\4.2.1\\GetAudio-4.2.1.exe release\\4.2.1\\GetAudio-4.2.1.exe.sha256 --notes "..."
"""
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import updater  # noqa: E402

if len(sys.argv) < 3:
    raise SystemExit(__doc__)
exe = Path(sys.argv[1])
version = sys.argv[2].lstrip('vV')
dest = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).resolve().parent.parent / 'release' / version
if not exe.is_file():
    raise SystemExit(f'Không thấy file: {exe}')
if not updater.parse_version(version):
    raise SystemExit(f'Phiên bản không hợp lệ: {version}')
dest.mkdir(parents=True, exist_ok=True)
digest = hashlib.sha256()
with exe.open('rb') as f:
    for chunk in iter(lambda: f.read(1 << 20), b''):
        digest.update(chunk)
name = updater.asset_name(version)
target = dest / name
if exe.resolve() != target.resolve():
    shutil.copy2(exe, target)
sha = digest.hexdigest()
(dest / (name + '.sha256')).write_text(f'{sha}  {name}\n', encoding='ascii')
print('Da tao:', target)
print('SHA256:', sha)
print(f'Tag: v{version}')
