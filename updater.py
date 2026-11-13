"""Cập nhật tự động qua GitHub Releases (chỉ dùng thư viện chuẩn).

App hỏi https://api.github.com/repos/<OWNER>/<REPO>/releases/latest:
  - tag_name      : "vX.Y.Z"  -> phiên bản mới nhất
  - assets        : file chạy  "GetAudio-X.Y.Z.exe"
                    (tuỳ chọn) "GetAudio-X.Y.Z.exe.sha256" để kiểm tra toàn vẹn
  - body          : ghi chú phát hành

Chuẩn bị file đăng bằng: python tools\\make_release.py <file .exe> <phiên bản>
Ai có quyền tạo Release trên repo là đẩy được chương trình tới mọi máy.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

OWNER = 'vohaidang98'
REPO = 'GetAudio'
API_URL = f'https://api.github.com/repos/{OWNER}/{REPO}/releases/latest'
USER_AGENT = f'{REPO}-Updater'
TIMEOUT = 30


def asset_name(version):
    """Tên file đăng lên GitHub Release (không dấu cách, GitHub không đổi tên)."""
    return f'GetAudio-{version}.exe'


def local_name(version):
    """Tên file chạy trên máy (giữ đúng tên PyInstaller tạo ra trong app.spec)."""
    return f'Gen Audio {version}.exe'


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


def _request(url, accept='application/vnd.github+json'):
    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})


def _read_sha256(url):
    with urllib.request.urlopen(_request(url, 'application/octet-stream'), timeout=TIMEOUT) as resp:
        text = resp.read(4096).decode('utf-8', 'replace')
    match = re.search(r'\b([0-9a-fA-F]{64})\b', text)
    if not match:
        raise ValueError('File .sha256 trên GitHub không chứa mã SHA-256 hợp lệ.')
    return match.group(1).lower()


def check_latest(current):
    """Trả về dict thông tin bản mới, hoặc None nếu đang là bản mới nhất / chưa có Release."""
    try:
        with urllib.request.urlopen(_request(API_URL), timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # repo chưa có Release nào
            return None
        if exc.code == 403:
            raise ValueError('GitHub tạm chặn do hỏi quá nhiều lần, hãy thử lại sau ít phút.') from exc
        raise ValueError(f'GitHub trả lỗi {exc.code}.') from exc
    except urllib.error.URLError as exc:
        raise ValueError(f'Không kết nối được GitHub:\n{exc.reason}') from exc

    tag = str(data.get('tag_name', '')).strip()
    version = tag.lstrip('vV')
    if not parse_version(version) or not is_newer(version, current):
        return None

    assets = {str(a.get('name', '')): str(a.get('browser_download_url', ''))
              for a in data.get('assets') or [] if isinstance(a, dict)}
    # Ưu tiên tên chuẩn; chấp nhận cả file dist đăng thẳng (GitHub đổi dấu cách thành dấu chấm).
    candidates = [asset_name(version), local_name(version), local_name(version).replace(' ', '.')]
    name = next((n for n in candidates if assets.get(n, '').startswith('https://')), '')
    if not name:
        raise ValueError(f'Release {tag} chưa có file {asset_name(version)}.')

    sha = ''
    sha_url = assets.get(name + '.sha256', '')
    if sha_url.startswith('https://'):
        sha = _read_sha256(sha_url)

    return {'version': version, 'name': local_name(version), 'url': assets[name],
            'sha256': sha, 'notes': str(data.get('body') or '')}


def download(info, progress=None):
    """Tải file từ GitHub về máy, kiểm tra SHA-256 (nếu Release có), trả về đường dẫn file."""
    folder = tempfile.mkdtemp(prefix='app_update_')
    dest = os.path.join(folder, info['name'])
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(_request(info['url'], 'application/octet-stream'), timeout=TIMEOUT) as resp, \
                open(dest, 'wb') as out:
            total = int(resp.headers.get('Content-Length') or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done * 100 / total)
        if total and done != total:
            raise ValueError('Tải bản cập nhật không đủ dung lượng, đã huỷ cập nhật.')
    except urllib.error.URLError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise ValueError(f'Không tải được bản cập nhật:\n{getattr(exc, "reason", exc)}') from exc
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    if info.get('sha256') and digest.hexdigest() != info['sha256']:
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
