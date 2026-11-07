"""Cập nhật tự động từ thư mục mạng LAN (chỉ dùng thư viện chuẩn).

Thư mục cập nhật chứa:
  - version.json : {"version": "1.3.0", "file": "ClipForge-Setup-1.3.0.exe",
                    "sha256": "<64 ký tự hex>", "notes": "..."}
  - file cài đặt được ghi trong version.json

Tạo thư mục này bằng: python tools\\make_release.py ...
Chỉ cho tài khoản quản trị quyền GHI vào thư mục này (ai ghi được là đẩy được chương trình
tới mọi máy), các máy khác chỉ cần quyền ĐỌC.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def parse_version(text):
    match = re.search(r'(\d+(?:\.\d+){0,3})', str(text))
    return tuple(int(part) for part in match.group(1).split('.')) if match else ()


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    if not a:
        return False
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return a > b


def _settings(app):
    base = os.environ.get('APPDATA') or str(Path.home())
    return Path(base) / app / 'update.json'


def get_folder(app):
    try:
        return str(json.loads(_settings(app).read_text('utf-8')).get('folder', '')).strip()
    except Exception:
        return ''


def set_folder(app, folder):
    path = _settings(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'folder': str(folder)}), 'utf-8')


def check_latest(folder, current):
    """Trả về dict thông tin bản mới, hoặc None nếu đang là bản mới nhất."""
    base = Path(folder)
    manifest = base / 'version.json'
    if not manifest.is_file():
        raise ValueError(f'Không tìm thấy version.json trong:\n{folder}')
    data = json.loads(manifest.read_text('utf-8-sig'))
    version = str(data.get('version', ''))
    if not is_newer(version, current):
        return None
    name = str(data.get('file', ''))
    sha = str(data.get('sha256', '')).lower()
    if not re.fullmatch(r'[\w .\-]+\.exe', name) or name.strip() != name:
        raise ValueError('Tên file cập nhật không hợp lệ.')
    if not re.fullmatch(r'[0-9a-f]{64}', sha):
        raise ValueError('version.json thiếu mã SHA-256 hợp lệ.')
    path = base / name
    if not path.is_file():
        raise ValueError(f'Chưa thấy file {name} trong thư mục cập nhật.')
    return {'version': version.lstrip('vV'), 'name': name, 'path': str(path),
            'sha256': sha, 'notes': str(data.get('notes', ''))}


def download(info, progress=None):
    """Chép file cài đặt về máy, kiểm tra SHA-256, trả về đường dẫn file trên máy."""
    folder = tempfile.mkdtemp(prefix='app_update_')
    dest = os.path.join(folder, info['name'])
    digest = hashlib.sha256()
    total = os.path.getsize(info['path'])
    done = 0
    with open(info['path'], 'rb') as src, open(dest, 'wb') as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done * 100 / total)
    if digest.hexdigest() != info['sha256']:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError('File cập nhật bị lỗi (sai mã SHA-256), đã huỷ cập nhật.')
    return dest


def install(path):
    """App chạy 1 file .exe (không có bộ cài): đặt file mới cạnh file cũ, mở bản mới rồi xoá bản cũ.
    Gọi xong thì đóng app ngay. Chỉ chạy khi app đã đóng gói (sys.frozen)."""
    import sys
    if not getattr(sys, 'frozen', False):
        raise ValueError('Chỉ cập nhật được khi chạy bản .exe.')
    old = os.path.abspath(sys.executable)
    new = os.path.join(os.path.dirname(old), os.path.basename(path))

    def q(text):
        return "'" + str(text).replace("'", "''") + "'"
    script = (
        "$ErrorActionPreference='Stop'; "
        f"try {{ Wait-Process -Id {os.getpid()} -Timeout 90 -ErrorAction SilentlyContinue }} catch {{}}; "
        "Start-Sleep -Seconds 1; "
        f"Copy-Item -LiteralPath {q(path)} -Destination {q(new)} -Force; "
        f"Start-Process -FilePath {q(new)}; "
        f"if ({q(old)} -ne {q(new)}) {{ for ($i=0; $i -lt 30; $i++) {{ try {{ Remove-Item -LiteralPath {q(old)} -Force -ErrorAction Stop; break }} catch {{ Start-Sleep -Seconds 1 }} }} }}"
    )
    import base64
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    exe = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen([exe, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], close_fds=True, creationflags=flags)
