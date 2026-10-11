"""Versioned, local-only backup and merge restore for learning state."""

from __future__ import annotations

from datetime import datetime, timezone

from .personal_notes import export_personal_data, prepare_personal_restore, validate_personal_data
from .study import export_study_data, restore_study_data, validate_study_backup


LEARNING_BACKUP_SCHEMA_VERSION = 1


def export_learning_backup() -> dict[str, object]:
    return {
        "schema_version": LEARNING_BACKUP_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "scope": "local-study-history-personal-notes-and-editions",
        "study": export_study_data(),
        "personal": export_personal_data(),
    }


def restore_learning_backup(payload: dict) -> dict[str, int]:
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != LEARNING_BACKUP_SCHEMA_VERSION:
        raise ValueError("learning_backup_schema_unsupported")
    study = payload.get("study")
    personal = payload.get("personal")
    # Validate every section before the idempotent merge touches local files.
    validated_study = validate_study_backup(study)
    validated_personal = validate_personal_data(personal)
    with prepare_personal_restore(validated_personal) as plan:
        study_counts = restore_study_data(validated_study, before_commit=plan.apply)
        return {**study_counts, **plan.counts}


__all__ = ["LEARNING_BACKUP_SCHEMA_VERSION", "export_learning_backup", "restore_learning_backup"]
