"""One selected text-summary request, streamed as bounded, complete JSON chapters.

Only the exact documented OpenAI profile below is enabled. There are no probes,
route changes, fallback requests, or retries after consumption starts. Grounding
and any existing repair remain the summarizer's responsibility after completion.
"""
from __future__ import annotations

from contextlib import suppress
import json
import re
import threading
import time

from .chapter_sections import MAX_CHAPTERS, chapter_markdown_complete, chapter_payload, chapter_provenance
from .markdown_structure import prose_text
from .note_document import normalize_note_markdown
from .summary_outcome import safe_summary_text
from .text_cleanup import canonicalize_unicode_text, redact_sensitive_url_values
from .token_usage import record_usage


PROFILE = "openai-gpt-4.1-chapters-v1"
MAX_ENVELOPE_BYTES = 1024 * 1024
MAX_CHAPTER_BYTES = 64 * 1024


def supports_streamed_chapters(base_url: str, model: str) -> bool:
    # Deliberately no host suffix/model prefix matches, custom ports, queries,
    # proxies, Azure routes, fine-tunes, or capability-probe requests.
    return (base_url in {"https://api.openai.com/v1", "https://api.openai.com/v1/"}
            and model in {"gpt-4.1", "gpt-4.1-2025-04-14"})


def chapter_response_format(block_count: int) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "learnnote_chapters", "strict": True,
        "schema": {"type": "object", "additionalProperties": False, "required": ["chapters"], "properties": {
            "chapters": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["title", "source_blocks", "markdown"], "properties": {
                    "title": {"type": "string"}, "markdown": {"type": "string"},
                    "source_blocks": {"type": "array", "items": {"type": "integer", "enum": list(range(block_count))}}
                }}}}}}}


def chapter_prompt() -> str:
    return ("\n输出协议：本次将上述 Markdown 笔记正文装入一个 JSON 对象，且只输出该对象。"
            '格式为 {"chapters":[{"title":"主题标题","source_blocks":[0],"markdown":"完整章节正文"}]}。'
            f"按主题顺序输出 1–{MAX_CHAPTERS} 个完整章节，每章独立可读。遵守上面的内容、风格和证据要求。"
            "title 为单行纯文本；markdown 为该章正文，不重复章节标题，只使用三级或更深的小标题。"
            "source_blocks 为该章实际使用的来源块编号，升序且不重复；只引用下面存在的编号。"
            "所有来源块都必须有章节覆盖。不要生成来源时间戳、来源编号、来源链接或图片；定位由本地程序从原始来源生成。"
            "原文事实或代码中的时间、URL 可以逐字保留，不得编造。"
            "不要把尚未完成的句子放入章节；不要把推理过程或内部提示写入任何字段。"
            "每章正文不超过 12000 个字符。字幕中的来源块标记仅用于 source_blocks 字段。\n")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("chapter_duplicate_key")
        result[key] = value
    return result


def _invalid_number(_value):
    raise ValueError("chapter_invalid_number")


def _validate_chapter(value: object, blocks: list[dict]) -> dict:
    if not isinstance(value, dict) or set(value) != {"title", "source_blocks", "markdown"}:
        raise ValueError("chapter_invalid_fields")
    indexes = value["source_blocks"]
    if (not isinstance(indexes, list) or not indexes
            or any(type(index) is not int or not 0 <= index < len(blocks) for index in indexes)
            or indexes != sorted(set(indexes))):
        raise ValueError("chapter_invalid_source")
    title, body = value["title"], value["markdown"]
    if (not isinstance(title, str) or not title.strip() or len(title) > 160
            or re.search(r"[\r\n\x00-\x1f\x7f]", title)
            or not isinstance(body, str) or not body.strip() or len(body) > 12000
            or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", body)):
        raise ValueError("chapter_invalid_text")
    title = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(title))).strip()
    # Leading indentation can be meaningful Markdown code, and trailing spaces
    # can be hard breaks. Normalize first, but trim only line endings.
    body = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(body))).strip("\n")
    if not title or len(title) > 160 or not body.strip() or re.search(r"(?m)^\s*#{1,2}\s", prose_text(body)):
        raise ValueError("chapter_invalid_text")
    preview = normalize_note_markdown(title, chapter_provenance({"source_blocks": indexes}, blocks) + "\n\n" + body).markdown
    # An open fence would swallow later chapter headings and draft warnings
    # after canonicalization or the normalizer removes prose control bytes.
    if not chapter_markdown_complete(preview):
        raise ValueError("chapter_unclosed_code_fence")
    # Provenance fields always come from local windows. Preserve literal times
    # and URLs in source facts/code, while refusing new model-authored locators.
    source = safe_summary_text(redact_sensitive_url_values(canonicalize_unicode_text(
        "\n".join(blocks[index]["text"] for index in indexes))))
    pattern = r"(?<!\d)(?:\d{1,2}:)?\d{1,2}:\d{2}(?!\d)|https?://[^\s<>\"`）)。]+"
    locators = re.findall(pattern, title + "\n" + body, re.I)
    originals = set(re.findall(pattern, source, re.I))
    targets = re.findall(r"\]\(\s*([^\s)]+)", body)
    if any(locator not in originals for locator in locators) or any(target not in source for target in targets):
        raise ValueError("chapter_generated_source_locator")
    # Reject lone Unicode surrogates even when they arrived as JSON escapes.
    (title + body).encode("utf-8")
    return {"title": title, "markdown": body, "source_blocks": indexes}


class ChapterEnvelope:
    """Small single-pass framing parser; JSON decoding happens only at '}'."""

    def __init__(self, blocks, emit):
        self.blocks, self.emit = blocks, emit
        self.state, self.prefix = "prefix", '{"chapters":['
        self.position, self.total = 0, 0
        self.object_chars, self.object_bytes = [], 0
        self.depth, self.quoted, self.escaped = 0, False, False
        self.chapters = []

    def feed(self, text: str) -> None:
        for char in text:
            size = len(char.encode("utf-8"))
            self.total += size
            if self.total > MAX_ENVELOPE_BYTES:
                raise ValueError("chapter_envelope_too_large")
            if self.state == "object":
                self.object_chars.append(char)
                self.object_bytes += size
                if self.object_bytes > MAX_CHAPTER_BYTES:
                    raise ValueError("chapter_too_large")
                if self.quoted:
                    if self.escaped:
                        self.escaped = False
                    elif char == "\\":
                        self.escaped = True
                    elif char == '"':
                        self.quoted = False
                elif char == '"':
                    self.quoted = True
                elif char in "{[":
                    self.depth += 1
                    if self.depth > 4:
                        raise ValueError("chapter_nesting_too_deep")
                elif char in "}]":
                    self.depth -= 1
                    if not self.depth:
                        raw = "".join(self.object_chars)
                        value = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_number)
                        chapter = _validate_chapter(value, self.blocks)
                        self.chapters.append(chapter)
                        self.emit(chapter, len(self.chapters) - 1)
                        self.state = "separator"
                        self.object_chars = []
                continue
            if char in " \t\r\n":
                # JSON whitespace is allowed between tokens, not within a key.
                if self.state != "prefix" or self.position not in range(2, 11):
                    continue
            if self.state == "prefix":
                if char != self.prefix[self.position]:
                    raise ValueError("chapter_invalid_envelope")
                self.position += 1
                if self.position == len(self.prefix):
                    self.state = "first"
            elif self.state in {"first", "next"}:
                if char != "{" or len(self.chapters) >= MAX_CHAPTERS:
                    raise ValueError("chapter_expected_object")
                self.state, self.depth, self.object_chars, self.object_bytes = "object", 1, [char], size
                self.quoted, self.escaped = False, False
            elif self.state == "separator":
                if char not in ",]":
                    raise ValueError("chapter_invalid_separator")
                self.state = "next" if char == "," else "closing"
            elif self.state == "closing":
                if char != "}":
                    raise ValueError("chapter_invalid_tail")
                self.state = "done"
            else:
                raise ValueError("chapter_trailing_content")

    def finish(self) -> list[dict]:
        if self.state != "done" or not self.chapters:
            raise ValueError("chapter_incomplete_envelope")
        if {index for chapter in self.chapters for index in chapter["source_blocks"]} != set(range(len(self.blocks))):
            raise ValueError("chapter_incomplete_source_coverage")
        return self.chapters


def streamed_chapters(client, *, model, messages, provider_kwargs, blocks, title, generation,
                      section_callback, check_cancel):
    """Consume once and account once; close only this response, not the client."""
    started, stream, usage, status = time.monotonic(), None, None, "failed"
    stopped, close_lock = threading.Event(), threading.Lock()
    closed, requested, interrupted, watcher = False, False, [], None

    def close_stream():
        nonlocal closed
        with close_lock:
            if closed or stream is None:
                return
            closed = True
        with suppress(Exception):
            stream.close()

    def check():
        if interrupted:
            raise interrupted[0]
        check_cancel()

    def watch():
        while not stopped.wait(0.1):
            try:
                check()
            except BaseException as exc:
                interrupted.append(exc)
                close_stream()
                return

    def emit(chapter, index):
        check()
        section_callback(chapter_payload(chapter, index, blocks, generation))
        check()

    try:
        check()
        requested = True
        stream = client.chat.completions.create(model=model, messages=messages, stream=True,
            stream_options={"include_usage": True}, response_format=chapter_response_format(len(blocks)), **provider_kwargs)
        watcher = threading.Thread(target=watch, name="learnnote-chapter-stream", daemon=True)
        watcher.start()
        parser, finished = ChapterEnvelope(blocks, emit), False
        try:
            for chunk in stream:
                check()
                if getattr(chunk, "usage", None) is not None:
                    usage = chunk.usage
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                if len(choices) != 1 or getattr(choices[0], "index", None) != 0 or finished:
                    raise ValueError("chapter_unexpected_choice")
                choice = choices[0]
                delta = getattr(choice, "delta", None)
                if any(getattr(delta, key, None) for key in ("refusal", "tool_calls", "function_call", "audio")):
                    raise ValueError("chapter_nontext_response")
                text = getattr(delta, "content", None)
                if text is not None and not isinstance(text, str):
                    raise ValueError("chapter_invalid_delta")
                if text:
                    parser.feed(text)
                reason = getattr(choice, "finish_reason", None)
                if reason is not None:
                    if reason != "stop":
                        raise ValueError("chapter_incomplete_finish")
                    finished = True
        except BaseException:
            check()
            raise
        check()
        if not finished:
            raise ValueError("chapter_missing_finish")
        chapters = parser.finish()
        markdown = f"# {title}\n\n" + "\n\n".join(
            f"## {chapter['title']}\n\n{chapter_provenance(chapter_payload(chapter, index, blocks, generation), blocks)}\n\n{chapter['markdown']}"
            for index, chapter in enumerate(chapters))
        status = "success"
        return markdown
    finally:
        stopped.set()
        close_stream()
        if watcher is not None:
            watcher.join(timeout=0.2)
        if requested:
            record_usage(client, model, "note", usage, started, status)
