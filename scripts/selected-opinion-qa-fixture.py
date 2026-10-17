"""Real selected-opinion routes with isolated data and a held, offline completion seam."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
from unittest.mock import patch


def configure_fixture(root, data, stack):
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError("Fixture data directory must exist and be empty")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local", PYTHONUTF8="1")
    sys.path[:0] = [str(root), str(root / "backend")]
    spec = importlib.util.spec_from_file_location("offline_acceptance", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec); spec.loader.exec_module(offline)
    stack.enter_context(offline.offline_network())
    from app import assistant_stream, community, main, model_connections, storage, selected_opinion_qa
    from app.models import TranscriptResult, TranscriptSegment
    stack.enter_context(patch.object(model_connections, "connection_storage", return_value="session"))
    stack.enter_context(patch.object(main, "recover_processing"))
    stack.enter_context(patch("app.activation.record"))
    stack.enter_context(patch.object(main, "record_activation"))
    route = {"base_url": "http://127.0.0.1:19877/v1", "model": "synthetic-opinion"}
    model_connections.save_selected_connection("custom", **route)
    url = "https://www.bilibili.com/video/BV1xx411c7mD?p=2"
    task = storage.create_task("current_page", "合成资料 · 所选观点问答", page_url=url)
    transcript = TranscriptResult(source="fixture", language="zh", full_text="合成原始字幕不保证收敛。",
        segments=[TranscriptSegment(start=0, end=12, text="合成原始字幕不保证收敛。"),
                  TranscriptSegment(start=12, end=24, text="不同条件下结果可能不同。")])
    caption = storage.write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
    note = storage.task_dir(task.id) / "note.md"
    note.write_text("# 合成学习笔记\n\n## 原始字幕\n\n合成原始字幕不保证收敛。", encoding="utf-8")
    storage.update_task(task.id, status="success", phase="completed", mode="subtitle_only", checkpoint="transcribed",
                        transcript_path=str(caption), note_path=str(note), summary_source="llm")
    community.set_community_enabled(True)
    items = community.add_community_context(task.id, [
        {"kind": "comment", "text": "<img src=x onerror=alert(1)> 手动观点：我认为条件很重要。"},
        {"kind": "danmaku", "text": "关联观点：这个结论是否适用于所有情况？", "timestamp_seconds": 12, "source_uri": url}])["items"]
    original = {"transcript.json": caption.read_bytes(), "note.md": note.read_bytes()}
    baseline = {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob("*") if p.is_file()}
    state, release = {"calls": [], "mutations": [], "completion_active": 0}, threading.Event()

    def complete(**kwargs):
        kwargs["before_dispatch"]()
        state["calls"].append({key: deepcopy(value) for key, value in kwargs.items()
                               if key not in {"api_key", "emit", "control", "before_dispatch"}})
        state["completion_active"] += 1
        try:
            while not release.wait(0.02):
                if kwargs.get("control") is not None:
                    kwargs["control"].check()
            if kwargs.get("control") is not None:
                kwargs["control"].check()
            return "<img src=x onerror=alert(1)> Mixed answer [E1]"
        finally:
            state["completion_active"] -= 1
    stack.enter_context(patch.object(assistant_stream, "qa_completion", side_effect=complete))

    def safety():
        current = {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob("*") if p.is_file()}
        forbidden = ("qa_history.json", "qa.md", "assistant-history.json", "assistant-runs/", "assistant-operations/", "events.jsonl")
        return {"original_artifacts_unchanged": all((storage.task_dir(task.id) / name).read_bytes() == content for name, content in original.items()),
                "no_history_or_run_files": not any(any(part in name for part in forbidden) and current.get(name) != baseline.get(name)
                                                   for name in set(current) | set(baseline)),
                "changed_files": sorted(name for name in set(current) | set(baseline) if current.get(name) != baseline.get(name)),
                "no_mixed_output_persisted": not any(b"Mixed answer" in value for value in current.values())}

    @main.app.get("/_fixture/state")
    def fixture_state():
        return {**state, "count": len(state["calls"]), "task_id": task.id, "item_ids": [item["item_id"] for item in items],
                "persistence": safety(), "offline_network": True, "selected_opinion_inflight": len(selected_opinion_qa._inflight)}

    @main.app.post("/_fixture/release")
    def fixture_release():
        release.set(); return {"ok": True}

    @main.app.post("/_fixture/reset")
    def fixture_reset():
        if state["completion_active"] or selected_opinion_qa._inflight:
            from fastapi import HTTPException
            raise HTTPException(409, "Wait for the active fixture request to settle")
        for name, content in baseline.items():
            (data / name).write_bytes(content)
        restored = TranscriptResult.model_validate_json(original["transcript.json"])
        transcript.segments = restored.segments
        model_connections.save_selected_connection("custom", **route)
        selected_opinion_qa._previews.clear()
        release.clear(); state["calls"].clear(); state["mutations"].clear()
        return {"ok": True}

    @main.app.post("/_fixture/mutate")
    def fixture_mutate(payload: dict):
        action = payload.get("action")
        if action == "delete_opinion":
            community.delete_community_item(task.id, payload.get("item_id", items[0]["item_id"]))
        elif action == "disable":
            community.set_community_enabled(False)
        elif action == "source_change":
            transcript.segments[0].text += " 已改变"
            caption.write_text(transcript.model_dump_json(), encoding="utf-8")
        elif action == "model_change":
            model_connections.save_selected_connection("custom", base_url=route["base_url"], model="synthetic-changed")
        else:
            from fastapi import HTTPException
            raise HTTPException(422, "Unknown fixture mutation")
        state["mutations"].append(action); return {"ok": True}

    return main.app, {"task_id": task.id, "item_ids": [item["item_id"] for item in items], "connection": route,
                      "offline_network": True, "completion_held": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--data-dir", required=True)
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    with ExitStack() as stack:
        app, fixture = configure_fixture(root, Path(args.data_dir).resolve(), stack)
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(128)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = origin
            print(json.dumps({"fixture_origin": origin, **fixture}), flush=True)
            uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])


if __name__ == "__main__":
    main()
