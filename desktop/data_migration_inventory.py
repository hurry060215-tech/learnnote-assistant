"""No-follow inventory and verified byte copies for explicit desktop migration.

The configured source boundary is trusted. No recorded artifact path is opened
here. Credentials, browser state and caches are excluded before traversal.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat


class MigrationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


DIRECTORIES = frozenset({
    "tasks", "uploads", "materials", "raw-imports", "courses", "learning-spaces",
    "concept-identities", "personal-notes", "user-editions", "personal-reviews",
    "study-schedule-backups", "assistant-operations", "assistant-runs", "exports",
    "config", "static",
})
DATABASES = frozenset({"library.sqlite3", "task-queue.sqlite3", "study.sqlite3",
    "token-usage.sqlite3", "course-episodes.sqlite3", "community.sqlite3", "activation.sqlite3"})
FILES = frozenset({"preferences.json", "export-presets.json", "assistant-history.json", "model-connection.json"})
CONFIG_FILES = frozenset({"update-preferences.json", "release-notes.json", "model-capability-checks.json", "release-cache.json"})
EXCLUDED_ROOTS = {
    "webview-profile": "浏览器资料与登录状态不会复制",
    "temp": "临时文件不会复制", "model-cache": "模型缓存可重新下载",
    "installers": "旧安装包不会复制", "updates": "更新暂存不会复制",
    "extension-updates": "扩展更新缓存不会复制", "extension-staging": "扩展暂存不会复制",
    "extension-backup": "扩展安装备份不会复制",
}


def fail(code, detail):
    raise MigrationError(code, f"LearnNote 数据迁移未执行：{detail}")


def linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def checked(path: Path, *, directory=False):
    try:
        info = path.lstat()
    except OSError as exc:
        fail("path_unavailable", f"无法检查 {path.name}。请检查所选目录。")
    if linked(info) or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        fail("unsafe_path", f"{path.name} 不是可验证的普通{'目录' if directory else '文件'}。")
    return info


def absolute_directory(value, *, ancestors=False):
    path = Path(value)
    if not path.is_absolute() or any(part in {"..", "."} for part in str(value).replace("\\", "/").split("/")):
        fail("ambiguous_directory", "请选择明确的绝对目录。")
    if ancestors:
        for ancestor in reversed(path.parents):
            checked(ancestor, directory=True)
    checked(path, directory=True)
    return path


def destination_directory(source: Path, target: Path):
    source = absolute_directory(source)
    target = absolute_directory(target, ancestors=True)
    if source == target or source in target.parents or target in source.parents:
        fail("overlapping_directories", "新旧数据目录必须互不包含。")
    try:
        if next(target.iterdir(), None) is not None:
            fail("destination_not_empty", "目标目录已有内容。请选择空文件夹，不会合并或覆盖。")
    except OSError:
        fail("destination_unreadable", "无法检查目标目录内容。")
    return target


def fingerprint(path):
    before = checked(path)
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            fail("source_changed", "读取期间文件发生变化。请关闭其他写入程序并重新预览。")
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    after = checked(path)
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        fail("source_changed", "读取期间文件发生变化。请重新预览。")
    return {"size": after.st_size, "sha256": digest.hexdigest(), "mtime_ns": after.st_mtime_ns,
            "device": after.st_dev, "inode": after.st_ino}


COORDINATION_ROOTS = ("personal-state", "course-state-locks", ".task-state")


def _exclusion(parts):
    first, name = parts[0], parts[-1]
    if first in EXCLUDED_ROOTS:
        return EXCLUDED_ROOTS[first]
    if first.startswith(".desktop-session.") or first == ".library-access.lock" or re.fullmatch(r"worker(?:-(?:light|download))?(?:-[0-3])?\.lock", first):
        return "进程锁与会话地址不会复制"
    if first in {"upload-budget.sqlite3", "upload-budget.sqlite3-wal", "upload-budget.sqlite3-shm"}:
        return "临时上传配额不会复制"
    if parts == ("assistant-operations", "worker.lock"):
        return "助手操作进程锁不会复制"
    if parts == ("config", "client-update-state.json"):
        return "旧安装包就绪状态不会复制"
    if len(parts) == 3 and first == "tasks" and name in {"cookies.txt", "subtitle_cookies.txt"}:
        return "任务认证 Cookie 不会读取或复制"
    return ""


def inventory(root: Path, *, strict_stage=False):
    root = absolute_directory(root)
    files, directories, excluded = {}, [], []

    def visit(parent, parts=()):
        try:
            entries = sorted(parent.iterdir(), key=lambda entry: entry.name)
        except OSError:
            fail("source_unreadable", "无法完整枚举源数据。")
        folded = set()
        for path in entries:
            name = path.name
            if name.casefold() in folded:
                fail("ambiguous_names", "目录存在大小写冲突，不能安全跨平台复制。")
            folded.add(name.casefold())
            relative = (*parts, name)
            key = "/".join(relative)
            if len(relative) == 1 and name in COORDINATION_ROOTS:
                checked(path, directory=True)
                # Ordinary annotation writes create this coordination directory.
                # Inspect names/types only; a pending restore or unknown entry
                # cannot be treated as a harmless lock folder.
                for entry in path.iterdir():
                    if entry.name != "worker.lock":
                        fail("pending_recovery", "个人数据协调目录包含待恢复或未知内容，请先核对。")
                    checked(entry)
                if strict_stage:
                    fail("stage_changed", "暂存目录出现未批准的进程协调文件。")
                excluded.append({"path": name, "reason": "已验证的进程协调目录不会复制"})
                continue
            excluded_reason = _exclusion(relative)
            if excluded_reason:
                if strict_stage:
                    fail("stage_changed", "暂存目录出现未批准的排除项目。")
                excluded.append({"path": key, "reason": excluded_reason})
                continue
            if name == "restore-pending" or name.endswith(("-journal", ".tmp")):
                fail("pending_recovery", "存在未完成的恢复或数据库日志，请先恢复原目录。")
            info = path.lstat()
            if linked(info):
                fail("unsafe_path", f"{key} 是链接，不能证明独立归属。")
            if not parts:
                db_name = re.sub(r"-(?:wal|shm)$", "", name)
                backup = re.fullmatch(r"task-queue\.sqlite3\.pre-control-[a-f0-9]{32}\.bak", name)
                if name not in DIRECTORIES and name not in FILES and db_name not in DATABASES and not backup:
                    fail("unsupported_data", f"源目录包含未识别的项目 {name}，请保留原目录并先核对。")
            if parts == ("config",) and name not in CONFIG_FILES:
                fail("unsupported_data", f"存在未识别的配置 {name}。")
            if parts == ("tasks",) and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", name):
                fail("invalid_task_directory", "任务目录标识不明确。")
            if stat.S_ISDIR(info.st_mode):
                if not parts and name not in DIRECTORIES:
                    fail("unsafe_path", f"{key} 应为普通文件。")
                directories.append(key)
                visit(path, relative)
            elif stat.S_ISREG(info.st_mode):
                if not parts and name in DIRECTORIES or parts == ("tasks",):
                    fail("unsafe_path", f"{key} 应为普通目录。")
                files[key] = fingerprint(path)
            else:
                fail("unsafe_path", f"{key} 不是普通文件或目录。")
    visit(root)
    for directory in directories:
        if directory.startswith("tasks/") and directory.count("/") == 1 and directory + "/task.json" not in files:
            fail("missing_task_manifest", "存在未完成或没有清单的任务目录，请先恢复。")
    for name in files:
        if name.endswith(("-wal", "-shm")) and (name.rsplit("-", 1)[0] not in files or not files[name.rsplit("-", 1)[0]]["size"]):
            fail("orphaned_database", "存在没有主数据库的日志文件。")
    return {"files": files, "directories": directories, "excluded": excluded}


def same_snapshot(left, right):
    # Excluded process/cache/credential files are deliberately never opened.
    return left["files"] == right["files"] and left["directories"] == right["directories"]


def copy_snapshot(source: Path, target: Path, snapshot):
    """Target is a newly-created exclusive staging directory, never a merge."""
    checked(target, directory=True)
    if next(target.iterdir(), None) is not None:
        fail("stage_not_empty", "暂存目录已有内容。")
    for relative in snapshot["directories"]:
        (target / relative).mkdir()
    for relative, expected in snapshot["files"].items():
        origin, copied = source / relative, target / relative
        # Parent directories are rechecked immediately before opening.
        for parent in origin.parents:
            checked(parent, directory=True)
            if parent == source:
                break
        if fingerprint(origin) != expected:
            fail("source_changed", "源文件已变化，请重新预览。")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(origin, flags), "rb") as incoming, copied.open("xb") as outgoing:
            for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        os.utime(copied, ns=(expected["mtime_ns"], expected["mtime_ns"]))
        result = fingerprint(copied)
        if (result["size"], result["sha256"]) != (expected["size"], expected["sha256"]) or fingerprint(origin) != expected:
            fail("source_changed", "复制校验失败，原目录仍保留。")
    if not same_snapshot(snapshot, inventory(source)):
        fail("source_changed", "复制期间源数据已变化，请重新预览。")
