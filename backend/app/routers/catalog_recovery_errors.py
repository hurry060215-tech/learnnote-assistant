"""Shared public recovery diagnostics; never expose arbitrary exception text."""
from fastapi import HTTPException

MESSAGES = {
    "catalog_snapshot_invalid": "请选择有效的 LearnNote SQLite 备份。",
    "catalog_snapshot_schema_invalid": "备份版本或表结构不兼容，或包含不支持的数据库对象。",
    "catalog_snapshot_metadata_invalid": "备份中的资料或出处字段类型无效；请另选完整快照。",
    "catalog_snapshot_too_large": "所选备份超过恢复条目上限。",
    "catalog_recovery_too_large": "恢复范围超过 512 MB 或 20,000 个文件；请保留完整数据副本后分开处理。",
    "catalog_recovery_unresolved": "仍有无法验证的资料，或没有可恢复内容；未写入资料库。",
    "catalog_changed_preview_again": "资料库、原文件或备份已改变，请重新预览后再确认。",
    "catalog_busy": "另一进程正在使用资料库，请稍后重新预览。",
    "catalog_source_path_unsafe": "检测到资料路径链接或越界，未读取链接目标；请恢复普通本地文件。",
    "catalog_sidecars_unresolved": "损坏或缺失的资料库还保留未确定状态的事务日志；请连同原数据库保存，暂不自动替换。",
    "catalog_partial_corruption_unresolved": "数据库虽损坏但仍有可读记录；为避免丢失备份之外的记录，暂不自动替换。请保留完整数据副本。",
    "catalog_current_schema_invalid": "本机资料表结构无法安全合并，未修改资料库。",
    "task_recovery_manifest_invalid": "任务清单或出处格式无效，未重建；请保留原文件并检查完整备份。",
    "task_recovery_source_missing": "任务引用的本机出处文件缺失或不可读，未重建。",
    "task_recovery_no_tasks": "没有可恢复的本机任务清单，未重建。",
    "task_recovery_tasks_active": "仍有排队或处理中的任务；请先停止任务，再重新预览。",
}


def recovery_error(exc: Exception) -> HTTPException:
    code = str(exc) if str(exc) in MESSAGES else "catalog_recovery_failed"
    return HTTPException(status_code=409 if code in {"catalog_changed_preview_again", "catalog_busy"} else 422,
                         detail={"code": code, "message": MESSAGES.get(code, "恢复未完成；原数据库与原文件已保留。请检查可用空间和完整备份后重试。")})
