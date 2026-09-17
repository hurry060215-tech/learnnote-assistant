"""Conservative recovery of a long note with a small unsupported-name passage."""
from __future__ import annotations

import re


def omit_unsupported_name_passages(note: str, issues: list[str]) -> tuple[str, list[str]]:
    if not issues or any(not issue.startswith("unsupported_terms:") for issue in issues):
        return "", []
    # Do not rewrite code or short notes, where omission could change the result.
    if len(note.strip()) < 800 or re.search(r"(?m)^\s*(```|~~~)", note):
        return "", []
    names = {name for issue in issues for name in issue.split(":", 1)[1].split(",") if name}
    if not names:
        return "", []
    pattern = re.compile(r"(?<![A-Za-z0-9+_.-])(?:" + "|".join(re.escape(name) for name in names) + r")(?![A-Za-z0-9+_.-])", re.I)
    kept, omitted = [], []
    for passage in re.split(r"\n\s*\n", note.strip()):
        if pattern.search(passage):
            if re.match(r"\s*#", passage) or "|" in passage:
                return "", []
            omitted.append(passage)
        else:
            kept.append(passage)
    if not omitted or len(omitted) > 2 or sum(map(len, omitted)) > len(note) * .15:
        return "", []
    # Remove a now-empty heading rather than presenting an empty section.
    kept = [p for i, p in enumerate(kept) if not (re.fullmatch(r"#{2,6}[^\n]*", p.strip()) and (i + 1 == len(kept) or kept[i + 1].lstrip().startswith("#")))]
    warning = f"> 来源核对提示：有 {len(omitted)} 段内容中的名称无法与字幕原文对齐，已暂时省略。其余内容仍经过来源检查；收到的字幕原文仍保留，可回到来源核对。"
    kept.insert(1 if kept and kept[0].startswith("# ") else 0, warning)
    return "\n\n".join(kept), omitted
