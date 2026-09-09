"""Bounded, cancellable assistant streams. Only public answer text is forwarded."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from queue import Empty, Full, Queue
import threading
import time

from fastapi.responses import StreamingResponse
from .token_usage import tracked_completion, record_usage


class StreamCancelled(Exception):
    pass


class StreamFailure(Exception):
    """A public failure with no provider exception or credential in its payload."""

    def __init__(self, code="model_stream_failed", message="回答未能完成，请重试或检查模型连接。"):
        self.code, self.message = code, message
        super().__init__(code)


class StreamControl:
    def __init__(self, timeout=180):
        self.cancelled = threading.Event()
        self.deadline = time.monotonic() + timeout
        self._lock = threading.Lock()
        self._closers = set()

    def check(self):
        if self.cancelled.is_set():
            raise StreamCancelled()
        if time.monotonic() >= self.deadline:
            raise StreamFailure("assistant_timeout", "等待回答超时，已停止此次请求。可以稍后重试。")

    def track(self, close):
        with self._lock:
            cancelled = self.cancelled.is_set()
            if not cancelled:
                self._closers.add(close)
        if cancelled:
            with suppress(Exception):
                close()
            raise StreamCancelled()

    def untrack(self, close):
        with self._lock:
            self._closers.discard(close)

    def cancel(self):
        self.cancelled.set()
        with self._lock:
            closers, self._closers = self._closers, set()
        for close in closers:
            with suppress(Exception):
                close()


def completion_text(client, *, emit=None, control=None, **kwargs):
    """Keep the existing nonstream API; use genuine provider deltas when requested."""
    if emit is None:
        response = tracked_completion(client, purpose="assistant", **kwargs)
        return response.choices[0].message.content or ""
    control.check()
    control.track(client.close)
    stream = None
    started, usage, status = time.monotonic(), None, "failed"
    try:
        try:
            stream = client.chat.completions.create(stream=True, stream_options={"include_usage": True}, **kwargs)
        except Exception as exc:
            # Some compatible providers reject this optional field before starting.
            if getattr(exc, "status_code", None) not in {400, 422} or "stream_options" not in str(exc):
                raise
            stream = client.chat.completions.create(stream=True, **kwargs)
        control.track(stream.close)
        parts, count, finished = [], 0, False
        for chunk in stream:
            control.check()
            if getattr(chunk, "usage", None) is not None:
                usage = chunk.usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            choice = choices[0]
            reason = getattr(choice, "finish_reason", None)
            if reason is not None:
                if reason != "stop":
                    raise StreamFailure("answer_incomplete", "模型未完成回答，已保留收到的内容。请重试或缩小问题范围。")
                finished = True
            text = getattr(getattr(choice, "delta", None), "content", None)
            # Reasoning/tool arguments are deliberately never exposed as answer text.
            if isinstance(text, str) and text:
                count += len(text)
                if count > 32000:
                    raise StreamFailure("answer_too_long", "回答过长，已停止。请将问题拆成几个部分。")
                parts.append(text)
                emit("delta", {"text": text})
        control.check()
        if not finished:
            raise StreamFailure("answer_incomplete", "回答连接提前结束，内容可能不完整。请重试。")
        answer = "".join(parts)
        if not answer.strip():
            raise StreamFailure("empty_model_response", "模型没有返回回答，请重试或更换模型。")
        status = "success"
        return answer
    finally:
        record_usage(client, kwargs.get("model", ""), "assistant", usage, started, status)
        if stream is not None:
            with suppress(Exception):
                stream.close()
            control.untrack(stream.close)
        control.untrack(client.close)


_workers = threading.BoundedSemaphore(4)


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def assistant_stream_response(work, *, timeout=180, heartbeat=3):
    """Run blocking provider IO off-loop with bounded backpressure and lifetime."""
    async def events():
        if not _workers.acquire(blocking=False):
            yield _sse("error", {"code": "assistant_busy", "message": "已有多个回答正在生成，请稍后重试。", "retryable": True})
            return
        control, pending = StreamControl(timeout), Queue(maxsize=32)

        def emit(event, data):
            while True:
                control.check()
                try:
                    pending.put((event, data), timeout=0.1)
                    return
                except Full:
                    continue

        def run():
            try:
                result = work(emit, control)
                control.check()
                emit("result", result)
            except StreamCancelled:
                pass
            except Exception as exc:
                failure = exc if isinstance(exc, StreamFailure) else StreamFailure()
                try:
                    emit("error", {"code": failure.code, "message": failure.message, "retryable": True})
                except (StreamCancelled, StreamFailure):
                    pass
            finally:
                _workers.release()

        worker = threading.Thread(target=run, name="learnnote-assistant-stream", daemon=True)
        started = False
        try:
            yield _sse("start", {"state": "thinking", "message": "正在准备回答…"})
            worker.start()
            started = True
            last_event = time.monotonic()
            while True:
                try:
                    control.check()
                except StreamFailure as exc:
                    yield _sse("error", {"code": exc.code, "message": exc.message, "retryable": True})
                    return
                try:
                    event, payload = pending.get_nowait()
                except Empty:
                    if time.monotonic() - last_event >= heartbeat:
                        yield _sse("status", {"state": "thinking", "message": "正在等待回答…"})
                        last_event = time.monotonic()
                    await asyncio.sleep(0.025)
                    continue
                yield _sse(event, payload)
                last_event = time.monotonic()
                if event in {"result", "error"}:
                    return
        finally:
            # Cancelling fetch / closing the tab tears down the active HTTP stream.
            await asyncio.to_thread(control.cancel)
            if not started:
                _workers.release()

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
    })
