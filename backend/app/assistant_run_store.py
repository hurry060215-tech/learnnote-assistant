"""Small run journals: goals and operation references, never note snapshots or keys.

The existing operation lease also protects this journal and source deletion.
It is never held while awaiting a provider. Sixteen fixed 32 KiB slots reserve
enough space for every accepted run's terminal receipt.
"""
from datetime import datetime, timezone
import json
import re

from fastapi import HTTPException
from . import config
from .assistant_run_persistence import atomic_write_text, digest
from .assistant_operation_types import SourceRef

MAX_RUNS = 16
MAX_RECORD_BYTES = 32 * 1024
STATUSES = {"ready", "planning", "executing", "awaiting_approval", "completed", "stopped", "cancelled", "failed"}
TERMINAL = {"completed", "stopped", "cancelled", "failed"}


def root(data_dir=None):
    directory = (config.DATA_DIR if data_dir is None else data_dir) / "assistant-runs"
    if directory.is_symlink():
        raise HTTPException(409, "任务记录目录不可用。")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def path_for(run_id, data_dir=None):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", run_id):
        raise HTTPException(422, "任务 ID 无效。")
    path = root(data_dir) / (run_id + ".json")
    if path.is_symlink():
        raise HTTPException(409, "任务记录不可用。")
    return path


def load(run_id, data_dir=None):
    path = path_for(run_id, data_dir)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_RECORD_BYTES:
            raise ValueError("oversized")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value["schema_version"] != 1 or value["id"] != run_id or value["status"] not in STATUSES
                or type(value["version"]) is not int or value["version"] < 1
                or not isinstance(value["question"], str) or not 1 <= len(value["question"]) <= 1000
                or type(value["model_attempts"]) is not int or not 0 <= value["model_attempts"] <= 8
                or not isinstance(value["active_seconds"], (float, int)) or not 0 <= value["active_seconds"] <= 100000
                or len(value["steps"]) > 9):
            raise ValueError("invalid_record")
        SourceRef.model_validate(value["source"])
        SourceRef.model_validate(value["initial_source"])
        if any(value["source"][key] != value["initial_source"][key] for key in ("kind", "id")):
            raise ValueError("changed_source")
        identity = {key: value[key] for key in ("question", "initial_source", "connection_fingerprint")}
        if digest(identity) != value["request_digest"]:
            raise ValueError("changed_request")
        for step in value["steps"]:
            if (step["tool"] not in {"read_note", "edit_note", "export_note"}
                    or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", step["operation_id"])
                    or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", step["step_id"])):
                raise ValueError("invalid_step")
        for key in ("edit_operation_id", "artifact_operation_id", "pending_operation_id", "expected_write_id"):
            if value.get(key) is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value[key]):
                raise ValueError("invalid_reference")
        return value
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(409, "任务记录损坏，已保留原文件。") from None


def save(value):
    path = path_for(value["id"])
    if not path.exists() and len(list(root().glob("*.json"))) >= MAX_RUNS:
        raise HTTPException(409, "本机助手任务已达 16 条上限，请先删除不再需要的任务记录。")
    value["updated_at"] = datetime.now(timezone.utc).isoformat()
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_RECORD_BYTES:
        raise HTTPException(409, "任务记录超出预留范围，未继续执行。")
    try:
        atomic_write_text(path, encoded)
    except OSError:
        raise HTTPException(503, "任务回执暂时无法保存，请刷新核对实际结果，勿重复创建。") from None


def cancellation_path(run_id):
    return path_for(run_id).with_suffix(".cancel")


def matching_sources(kind, source_id, data_dir):
    """Called under the shared lease, before deleting any source bytes."""
    matches = []
    for path in root(data_dir).iterdir():
        if re.fullmatch(r"\.[A-Za-z0-9_-]{8,64}\.json\.[0-9a-f]{32}\.tmp", path.name):
            path.unlink(missing_ok=True)
    for path in root(data_dir).glob("*.json"):
        value = load(path.stem, data_dir)
        if value["source"]["kind"] == kind and value["source"]["id"] == source_id:
            matches.append(value["id"])
    return matches


def purge(run_id, data_dir=None):
    path = path_for(run_id, data_dir)
    path.with_suffix(".cancel").unlink(missing_ok=True)
    path.unlink(missing_ok=True)
