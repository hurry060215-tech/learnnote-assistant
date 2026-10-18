"""One observed HTTP cancellation after 80 synthetic retained tasks.

Diagnostic only, no browser reader concurrency or release-acceptance claim.
Reuse the offline reference fixture, original seed path and bounded contention
observer. No native profiler, query interception or product behavior changes.
"""
import argparse
from contextlib import ExitStack
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import socket
import subprocess
import threading
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CLIENT_LIMIT = 64


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cancel_and_drain(api, task_id, result, *, clock=time.perf_counter, sleep=time.sleep, timeout=30):
    """Client envelopes include transport/decoding; callback evidence is separate."""
    result.update(client=[], client_limit=CLIENT_LIMIT, client_dropped=0)
    def call(label, route, method="GET"):
        row = dict(name=label, start_s=clock(), raised=True)
        try:
            value = api(route, method=method)
            row["raised"] = False
            if label == "drain_poll":
                row.update(status=value.get("status"), waiting=value.get("waiting"),
                           callback_finished=(value.get("queue") or {}).get("callback_finished"))
            return value
        finally:
            row["end_s"] = clock()
            row["wall_s"] = row["end_s"] - row["start_s"]
            if len(result["client"]) == CLIENT_LIMIT:
                result["client"].pop(0)
                result["client_dropped"] += 1
            result["client"].append(row)
    started = clock()
    result["cancel_start_s"] = started
    call("cancel_http", f"/api/tasks/{task_id}/cancel", "POST")
    result["cancel_response_s"] = clock()
    while clock() - started < timeout:
        state = call("drain_poll", f"/_fixture/tasks/{task_id}")
        if (state.get("status") == "cancelled" and state.get("waiting") is False
                and (state.get("queue") or {}).get("callback_finished") == 1):
            result.update(observed_drained_s=clock(), cancel_and_drain_s=clock() - started)
            return state
        sleep(.025)
    raise TimeoutError("diagnostic_cancel_drain_timeout")


def callback_observation_gap(contention, task_id, observed_s):
    """Same-process perf_counter coordinates; never equate polling with drain."""
    rows = [row for row in contention["operations"] if row["name"] == "callback_finish"
            and row["task_id"] == task_id and not row["raised"]]
    if len(rows) != 1:
        return dict(available=False, reason="callback_boundary_missing_or_ambiguous")
    end = contention["clock"]["monotonic_seconds"] + rows[0]["end_s"]
    return dict(available=True, callback_record_return_s=end,
                observed_after_callback_s=observed_s - end)


def run(output):
    fixture = load("cancel_fixture", "scripts/progressive-slo-fixture.py")
    seed = load("cancel_seed", "scripts/progressive-slo-catalog-diagnostic.py")
    helpers = load("cancel_helpers", "scripts/tests/test_progressive_slo_fixture.py")
    diagnostics = load("cancel_contention", "scripts/progressive-slo-contention.py")
    report = dict(schema_version=1, diagnostic_only=True, acceptance=False, completed=False,
        cancellations=1, browser=False, retained_tasks=80, observer_enabled=True,
        observer_overhead=dict(available=False, reason="No matched observer-off cancellation in this bounded run"),
        scope="One real loopback HTTP/queue/held-summary cancellation after 80 synthetic tasks; no browser reader concurrency",
        caveats=["Does not recreate or attribute the failing hosted browser workload",
                 "Observer overhead is included and unmeasured; no clean latency or acceptance claim",
                 "Nested spans are inclusive; do not sum them",
                 "index_return includes original best-effort indexing and its commits, not an isolated commit timer",
                 "Client envelope includes transport and JSON decoding; callback record return is separately measured"],
        host=dict(platform=platform.system(), python=platform.python_version()),
        source=dict(commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    data = output / "data"
    data.mkdir()
    def save():
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    save()
    collector = None
    primary_failure = False
    try:
        with ExitStack() as stack:
            app, _ = fixture.configure_fixture(ROOT, data, stack)
            rows, elapsed = seed.seed_tasks(data, helpers.reference_request)
            counts = seed.projection_state(data)["counts"]
            if len(rows) != 80 or sum(row["cues"] for row in rows) != 11000 or counts != dict(
                    library_tasks=80, library_tasks_fts=80, source_evidence=11080, source_evidence_fts=11080):
                raise RuntimeError("diagnostic_dataset_count")
            report["seed"] = dict(task_count=len(rows), cue_count=11000, counts=counts, seconds=elapsed)
            save()
            collector = diagnostics.install(app, stack)
            diagnostics.install_cancellation_spans(app, stack, collector)
            import uvicorn
            from app.task_queue import queue_for
            listener = server = worker = None
            worker_started = False
            execution_error = None
            try:
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listener.bind(("127.0.0.1", 0))
                listener.listen(128)
                base = f"http://127.0.0.1:{listener.getsockname()[1]}"
                server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
                worker = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
                worker.start()
                worker_started = True
                deadline = time.monotonic() + 10
                while not server.started:
                    if not worker.is_alive() or time.monotonic() > deadline:
                        raise RuntimeError("diagnostic_http_start_failed")
                    time.sleep(.01)
                def api(route, body=None, method=None):
                    request = Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                        method=method or ("POST" if body is not None else "GET"),
                        headers={"Content-Type": "application/json"})
                    with urlopen(request, timeout=20) as response:
                        return json.load(response)
                created = api("/api/tasks/from-current-page?defer=true", helpers.reference_request(5, "cancel-diagnostic"))
                task_id = report["task_id"] = created["task_id"]
                api(f"/api/tasks/{task_id}/start", helpers.OPTIONS)
                deadline = time.monotonic() + 20
                while True:
                    before = api(f"/_fixture/tasks/{task_id}")
                    if before["waiting"] and before["status"] == "running":
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("diagnostic_held_summary_timeout")
                    time.sleep(.025)
                report["before"] = before
                report["cancellation"] = {}
                after = cancel_and_drain(api, task_id, report["cancellation"])
                report["after"] = after
                if (after["hashes"] != before["hashes"] or after["generation"] != before["generation"]
                        or after["continuation_calls"] != before["continuation_calls"]
                        or after["callback"]["failed"] or not after["callback"]["completed"]):
                    raise AssertionError("diagnostic_cancellation_changed_source_or_callback")
                report["fixture"] = api("/_fixture/state")
                if report["fixture"]["forbidden_attempts"]:
                    raise AssertionError("diagnostic_forbidden_operation")
                report["completed"] = True
            except BaseException as error:
                execution_error = error
                raise
            finally:
                # Attempt bounded worker shutdown before restoring aliases.
                # Each cleanup is independent, including after partial setup.
                if execution_error is not None and report.get("task_id"):
                    try:
                        from app.storage import request_task_cancel
                        request_task_cancel(report["task_id"])
                        report["cleanup_cancel_requested"] = True
                    except BaseException:
                        report["cancel_cleanup_failed"] = True
                try:
                    owned_queue = queue_for(data)
                    owned_queue.stop(timeout=10)
                    report["queue_workers_alive"] = any(thread.is_alive() for thread in owned_queue.workers.values())
                    if report["queue_workers_alive"]:
                        raise RuntimeError("diagnostic_queue_stop_failed")
                except BaseException:
                    report["queue_cleanup_failed"] = True
                report["http_cleanup_failed"] = False
                if server is not None:
                    try:
                        server.should_exit = True
                    except BaseException:
                        report["http_shutdown_failed"] = report["http_cleanup_failed"] = True
                if worker_started:
                    try:
                        worker.join(10)
                    except BaseException:
                        report["http_join_failed"] = report["http_cleanup_failed"] = True
                    try:
                        report["http_worker_alive"] = worker.is_alive()
                        if report["http_worker_alive"]:
                            report["http_cleanup_failed"] = True
                    except BaseException:
                        report["http_state_failed"] = report["http_cleanup_failed"] = True
                if listener is not None:
                    try:
                        listener.close()
                    except BaseException:
                        report["listener_close_failed"] = report["http_cleanup_failed"] = True
                try:
                    report["contention"] = collector.snapshot()
                    if "observed_drained_s" in report.get("cancellation", {}):
                        report["callback_observation"] = callback_observation_gap(report["contention"],
                            report["task_id"], report["cancellation"]["observed_drained_s"])
                except BaseException:
                    report["diagnostic_snapshot_failed"] = True
                    if execution_error is None:
                        raise
                if execution_error is None and (report.get("queue_cleanup_failed") or report["http_cleanup_failed"]):
                    raise RuntimeError("diagnostic_worker_cleanup_failed")
    except BaseException as error:
        primary_failure = True
        report["completed"] = False
        try:
            report["failure"] = fixture.callback_exception_chain(error)
        except BaseException:
            report["failure_format_failed"] = True
        raise
    finally:
        if collector is not None and "contention" not in report:
            try:
                report["contention"] = collector.snapshot()
            except BaseException:
                report["diagnostic_snapshot_failed"] = True
                if not primary_failure:
                    raise
        try:
            save()
        except BaseException:
            if not primary_failure:
                raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    output = parser.parse_args().output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        run(output)
    except Exception:
        print("Synthetic cancellation diagnostic failed; see its redacted report.")
        return 1
    print("Synthetic cancellation diagnostic complete; no browser acceptance claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
