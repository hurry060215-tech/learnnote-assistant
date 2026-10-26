"""Reproduce task progress indexing costs using synthetic data only.

Pass --backend-path to compare a clean archived revision with this checkout.
No model, media download, user task, or external service is involved.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-path", type=Path, default=Path(__file__).resolve().parents[1] / "backend")
    parser.add_argument("--segments", type=int, default=1000)
    parser.add_argument("--updates", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.segments <= 10000 or not 1 <= args.updates <= 100:
        parser.error("Use 1..10000 segments and 1..100 updates")
    sys.path.insert(0, str(args.backend_path.resolve()))
    from app import knowledge, library, storage
    from app.models import TaskRecord

    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        tasks = root / "tasks"
        task_root = tasks / "synthetic-benchmark"
        task_root.mkdir(parents=True)
        for module in (library, knowledge, storage):
            stack.enter_context(patch.object(module, "DATA_DIR", root))
            stack.enter_context(patch.object(module, "ensure_dirs", return_value=None))
        for module in (library, storage):
            stack.enter_context(patch.object(module, "TASK_DIR", tasks))
        stack.enter_context(patch.object(storage, "record_task_event"))
        stack.enter_context(patch.object(storage, "record_status"))
        note, transcript = task_root / "note.md", task_root / "transcript.json"
        note.write_text("# Synthetic benchmark\n\nA test note.", encoding="utf-8")
        transcript.write_text(json.dumps({"segments": [
            {"start": i, "end": i + 1, "text": f"Synthetic source cue {i}"} for i in range(args.segments)
        ]}), encoding="utf-8")
        record = TaskRecord(id=task_root.name, source_type="local", title="Synthetic benchmark",
                            note_path=str(note), transcript_path=str(transcript),
                            created_at="2026-10-23", updated_at="2026-10-23")
        storage.save_task(record)
        statements = []

        def traced_connect(original):
            def connect(*values, **options):
                result = original(*values, **options)
                connection = result[0] if isinstance(result, tuple) else result
                connection.set_trace_callback(statements.append)
                return result
            return connect

        for module in (library, knowledge):
            stack.enter_context(patch.object(module, "_connect", traced_connect(module._connect)))
        reads = stack.enter_context(patch.object(library, "read_canonical_text", wraps=library.read_canonical_text))
        started = time.perf_counter()
        for tick in range(args.updates):
            storage.update_task(record.id, progress=tick, message=f"Synthetic progress {tick}")
        elapsed = time.perf_counter() - started
        normalized = [" ".join(statement.upper().split()) for statement in statements]
        print(json.dumps({
            "segments": args.segments, "progress_updates": args.updates,
            "seconds": round(elapsed, 6), "content_reads": reads.call_count,
            "evidence_deletes": sum(value.startswith("DELETE FROM SOURCE_EVIDENCE WHERE") for value in normalized),
            "evidence_inserts": sum(value.startswith("INSERT OR REPLACE INTO SOURCE_EVIDENCE (") for value in normalized),
            "evidence_fts_inserts": sum(value.startswith("INSERT INTO SOURCE_EVIDENCE_FTS(") for value in normalized),
        }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
