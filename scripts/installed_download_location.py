"""Bounded read-only result-location evidence for the synthetic installed gate.

Only exact approved filenames are read. Private directory input stays in memory;
reports contain fixed location categories and hashes only for matching own bytes.
"""
import hashlib
import ctypes
import json
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 256 * 1024
NAMES = {'md': 'learnnote-diagnostics.md', 'json': 'learnnote-diagnostics.json'}


def identity(info):
    return info.st_dev, info.st_ino


def real(info, directory):
    return (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) and not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT and (directory or info.st_nlink == 1)


def ancestry(path):
    """Validate every existing component without enumerating directories."""
    path = Path(path)
    assert path.is_absolute() and '..' not in path.parts and len(path.parts) <= 32
    result = {}
    for item in reversed((path, *path.parents)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            break
        assert real(info, True) and item.resolve(strict=True) == item
        result[item] = identity(info)
    return result


def unchanged(before, after):
    assert all(after.get(path) == value for path, value in before.items())


def exact_file(path, expected=None, baseline=None):
    """Baseline is metadata only; unsafe/raced results retain no hash or contents."""
    result = {'state': 'unavailable', 'bytes': None, 'bytes_capped': False, 'matches_expected': None}
    try:
        parents = ancestry(path.parent)
        if baseline is not None:
            unchanged(baseline['parents'], parents)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return {'state': 'missing', 'bytes': None, 'bytes_capped': False, 'matches_expected': None}, parents
        if not real(info, False):
            return {'state': 'unsafe', 'bytes': None, 'bytes_capped': False, 'matches_expected': None}, parents
        result = {'state': 'regular', 'bytes': min(MAX_BYTES + 1, info.st_size), 'bytes_capped': info.st_size > MAX_BYTES + 1, 'matches_expected': None}
        if expected is None:
            return result, parents
        if baseline is not None and baseline['file']['state'] != 'missing':
            result['state'] = 'preexisting' if baseline['file']['state'] == 'regular' else 'unavailable'
            return result, parents
        if info.st_size > MAX_BYTES or info.st_size != expected['bytes']:
            result['matches_expected'] = False; return result, parents
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            assert real(opened, False) and identity(info) == identity(opened)
            unchanged(parents, ancestry(path.parent))
            named = path.lstat()
            assert real(named, False) and identity(named) == identity(opened)
            value = stream.read(MAX_BYTES + 1)
            end = os.fstat(stream.fileno())
        after = path.lstat()
        unchanged(parents, ancestry(path.parent))
        assert real(after, False) and identity(after) == identity(info)
        assert (info.st_size, info.st_mtime_ns) == (opened.st_size, opened.st_mtime_ns) == (end.st_size, end.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        result['matches_expected'] = len(value) == expected['bytes'] and hashlib.sha256(value).hexdigest() == expected['sha256']
        if result['matches_expected']:
            result['sha256'] = expected['sha256']
        return result, parents
    except (OSError, ValueError, AssertionError):
        return {'state': 'unavailable', 'bytes': None, 'bytes_capped': False, 'matches_expected': None}, {}


def fixed_local_drive(root):
    drive_type = ctypes.WinDLL('kernel32', use_last_error=True).GetDriveTypeW
    drive_type.argtypes = [ctypes.c_wchar_p]
    drive_type.restype = ctypes.c_uint
    return drive_type(root) == 3  # DRIVE_FIXED; reject remote/mapped/unknown volumes.


def default_downloads():
    # The approved exception is the disposable GitHub-hosted runner Downloads,
    # never an ordinary local or self-hosted user's Downloads.
    assert os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted' and os.environ.get('RUNNER_OS') == 'Windows'
    # Same Shell Folders value read by pinned pywebview 6.2.1.
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders', 0, winreg.KEY_READ) as key:
        value, kind = winreg.QueryValueEx(key, '{374DE290-123F-4565-9164-39C4925E467B}')
    assert kind == winreg.REG_SZ and isinstance(value, str) and 0 < len(value) <= 4096
    assert re.match(r'^[A-Za-z]:\\', value) and not value.startswith('\\\\')
    assert fixed_local_drive(value[:3])
    path = Path(value)
    parents = ancestry(path)
    assert path in parents
    return path


def parse_private(raw):
    assert isinstance(raw, str) and len(raw) <= 4096 and raw.startswith('OWNED_DOWNLOAD_EVIDENCE:')
    value = json.loads(raw.removeprefix('OWNED_DOWNLOAD_EVIDENCE:'))
    assert set(value) == {'directory', 'expected'}
    assert re.fullmatch(r'local-native-exports-[A-Za-z0-9]{6}', value['directory'])
    assert isinstance(value['expected'], list) and 1 <= len(value['expected']) <= 2
    seen = set()
    for item in value['expected']:
        assert set(item) == {'format', 'bytes', 'sha256'} and item['format'] in NAMES and item['format'] not in seen
        assert type(item['bytes']) is int and 0 < item['bytes'] <= MAX_BYTES
        assert re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
        seen.add(item['format'])
    return value


class DownloadLocationEvidence:
    def __init__(self, data, output, resolve_downloads=default_downloads):
        self.data, self.output = Path(data), Path(output)
        self.private = None
        self.resolve_downloads = resolve_downloads
        self.report = {'status': 'prepared', 'normal_close': False, 'locations': [], 'scope': 'exact approved filenames only; no directory enumeration'}
        self.output_parents = ancestry(self.output)
        assert self.output in self.output_parents
        self.folders = {'synthetic_home': data.parent / (data.name + '-home'),
                        'synthetic_desktop': data.parent / (data.name + '-home') / 'Desktop',
                        'synthetic_downloads': data.parent / (data.name + '-home') / 'Downloads'}
        try: self.folders['default_downloads'] = resolve_downloads()
        except (OSError, ValueError, AssertionError, ImportError): self.report['downloads_folder_unavailable'] = True
        self.baselines = {}
        for category, folder in self.folders.items():
            for format, name in NAMES.items():
                state, parents = exact_file(folder / name)
                self.baselines[category, format] = {'file': state, 'parents': parents}

    def accept(self, raw):
        self.private = None
        try: self.private = parse_private(raw)
        except (TypeError, ValueError, KeyError, AssertionError): self.report['private_input_unavailable'] = True

    def finish(self, normal_close):
        self.report['normal_close'] = normal_close is True
        try:
            if normal_close is not True or self.private is None:
                self.report['status'] = 'unavailable'; self.report['locations'] = []; return
            unchanged(self.output_parents, ancestry(self.output))
            default_valid = True
            if 'default_downloads' in self.folders:
                try:
                    default_valid = self.resolve_downloads() == self.folders['default_downloads']
                except Exception:
                    default_valid = False
                if not default_valid:
                    self.report['downloads_folder_unavailable'] = True
            categories = {}
            for expected in self.private['expected']:
                format = expected['format']; name = NAMES[format]
                categories[format] = {key: folder / name for key, folder in self.folders.items()}
                categories[format]['requested_destination'] = self.output / self.private['directory'] / name
                for category, path in categories[format].items():
                    baseline = self.baselines.get((category, format))
                    if category == 'requested_destination':
                        baseline = {'parents': self.output_parents, 'file': {'state': 'missing'}}
                    # Parent asserts absence before starting the helper; the
                    # unchanged native guard rechecks before eligible input.
                    if category == 'default_downloads' and not default_valid:
                        state = {'state': 'unavailable', 'bytes': None, 'bytes_capped': False, 'matches_expected': None}
                    else:
                        state, _ = exact_file(path, expected, baseline)
                    self.report['locations'].append({'format': format, 'location': category, 'before': 'parent_asserted_absent' if category == 'requested_destination' else baseline['file']['state'], **state})
            self.report['status'] = 'checked'
        except Exception:
            self.report['status'] = 'unavailable'
            self.report['locations'] = []
        finally:
            self.private = None
