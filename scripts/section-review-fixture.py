"""Isolated, loopback-only chapter review UI fixture with a synthetic model."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    args = parser.parse_args()
    root, data = Path(__file__).resolve().parents[1], Path(args.data_dir).resolve()
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError("Fixture data directory must exist and be empty")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local", PYTHONUTF8="1")
    sys.path.insert(0, str(root / "backend"))
    spec = importlib.util.spec_from_file_location("offline_acceptance", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec); spec.loader.exec_module(offline)
    with offline.offline_network():
        state = {"calls": 0, "mode": "normal", "payloads": []}
        release = threading.Event()
        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                state["calls"] += 1; state["payloads"].append(payload)
                mode = state["mode"]
                if mode == "delay": release.wait(20)
                inputs = json.loads(payload["messages"][1]["content"])
                source = inputs["sources"][0]
                judgments = [{"claim_alias": item["claim_alias"], "verdict": ("supported", "contradicted", "insufficient")[index % 3],
                    "reason": "合成模型返回，用于检验交互与边界，不代表真实模型质量。",
                    "citations": [{"source_alias": source["source_alias"], "quote": source["text"]}]}
                    for index, item in enumerate(inputs["claims"])]
                response = {"id": "synthetic-review", "object": "chat.completion", "created": 0, "model": "synthetic-review",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant",
                    "content": "not json" if mode == "reject" else json.dumps({"judgments": judgments}, ensure_ascii=False)}}],
                    "usage": {"prompt_tokens": 80, "completion_tokens": 45, "total_tokens": 125}}
                content = json.dumps(response).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(content))); self.end_headers()
                self.wfile.write(content)
        provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        from app.model_connections import save_selected_connection
        from app.models import TranscriptResult, TranscriptSegment
        from app.storage import create_task, task_dir, update_task, write_json
        from app.pipeline_progress import start_pipeline_attempt, write_progressive_draft
        from app.progressive_sections import partial_section_callback
        from app.chapter_sections import chapter_payload
        from app.reading_notes import source_block_entries
        from app.main import app
        import uvicorn
        save_selected_connection("custom", f"http://127.0.0.1:{provider.server_port}/v1", "synthetic-review")
        transcript = TranscriptResult(source="fixture", full_text="学习率控制步长。较小的学习率不保证收敛。",
            segments=[TranscriptSegment(start=0, end=10, text="学习率控制每次参数更新的步长。"),
                      TranscriptSegment(start=10, end=20, text="学习率为 0.01，并不保证收敛。"),
                      TranscriptSegment(start=20, end=30, text="如果条件变化，需要重新检查结论。")])
        prose = "学习率控制每次参数更新的步长。\n\n学习率为 0.10，保证收敛。\n\n步长较小可能让变化更平缓。\n\n" + "\n\n".join(f"第 {i} 条概括仍需结合原文核对。" for i in range(4, 15))
        tasks = []
        for partial in (False, True):
            task = create_task("local", "章节核对合成验收" + ("（草稿）" if partial else ""))
            work = task_dir(task.id)
            source = write_json(task.id, "transcript.json", transcript.model_dump(mode="json"))
            if partial:
                start_pipeline_attempt(task.id)
                draft = write_progressive_draft(task.id, task.title, transcript)
                update_task(task.id, status="running", phase="summarizing", note_path=str(draft), transcript_path=str(source), summary_source="transcript-draft")
                partial_section_callback(task.id, transcript)(chapter_payload({"title": "学习率与收敛", "source_blocks": [0],
                    "markdown": prose}, 0, source_block_entries(transcript), "a" * 64))
                update_task(task.id, status="failed", phase="failed", error_code="summary_unavailable")
            else:
                note = work / "note.md"; note.write_text("# 章节核对合成验收\n\n## 学习率与收敛\n\n" + prose, encoding="utf-8")
                update_task(task.id, status="success", phase="completed", note_path=str(note), transcript_path=str(source), summary_source="text-llm")
            tasks.append(task.id)
        @app.get("/_fixture/state")
        def fixture_state(): return state
        @app.post("/_fixture/mode/{mode}")
        def fixture_mode(mode: str):
            if mode == "release": release.set()
            elif mode in {"normal", "reject", "delay"}: state["mode"] = mode; release.clear()
            return {"ok": True}
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(128)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = origin
            print(json.dumps({"fixture_origin": origin, "offline_network": True, "task_id": tasks[0], "partial_task_id": tasks[1]}), flush=True)
            uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[listener])
        provider.shutdown(); provider.server_close()


if __name__ == "__main__": main()
