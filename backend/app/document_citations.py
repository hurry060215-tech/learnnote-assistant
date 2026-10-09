"""Revision-bound, local claim citation projection for portable documents."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Callable

from .claims import CLAIM_SCHEMA_VERSION
from .note_document import section_anchor_id


_CITATION_WARNING = "claim_citations_require_current_map"


def _evidence_index(task_id: str, evidence: list, revision: str, transcript: dict | None) -> dict | None:
    """Reject ambiguous, altered or foreign-task source records before linking."""
    by_id = {}
    rows = []
    segments = transcript.get("segments", []) if isinstance(transcript, dict) else []
    if transcript is not None and not isinstance(segments, list):
        return None
    for item in evidence:
        if not isinstance(item, dict):
            return None
        eid, kind = item.get("evidence_id"), item.get("kind")
        if (not isinstance(eid, str) or not eid or eid in by_id
                or not isinstance(kind, str) or kind not in {"transcript", "visual", "document"}
                or item.get("task_id", task_id) != task_id
                or not isinstance(item.get("source_uri", ""), str)
                or any(not isinstance(item.get(key), str) for key in ("source_type", "locator", "text"))):
            return None
        if kind in {"transcript", "visual"}:
            if not eid.startswith(f"task-{task_id}-{kind}-"):
                return None
            start, end = item.get("start"), item.get("end")
            if (type(start) not in (int, float) or type(end) not in (int, float)
                    or not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end
                    or item["locator"] != f"{float(start):.1f}-{float(end):.1f}s"):
                return None
        if kind == "transcript" and transcript is not None:
            # A replaced transcript must not inherit the old source links even
            # when the note itself has not changed.
            suffix = eid.removeprefix(f"task-{task_id}-transcript-")
            if not re.fullmatch(r"[0-9]{5,}", suffix):
                return None
            index = int(suffix)
            if index >= len(segments) or not isinstance(segments[index], dict):
                return None
            segment = segments[index]
            if (item["text"] != str(segment.get("text") or "").strip()
                    or item["start"] != segment.get("start") or item["end"] != segment.get("end")):
                return None
        by_id[eid] = item
        rows.append(f"{eid}|{kind}|{item['source_type']}|{item['locator']}|{item.get('source_uri', '')}|{item['text']}")
    expected = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    return by_id if revision == expected else None


def project_claim_citations(task, note: str, claim_map: dict | None, settings: dict,
                            *, safe_url: Callable, timed_url: Callable,
                            sanitize: Callable, heading_texts: list[str], transcript: dict | None = None) -> tuple[str, list[str]]:
    """Never attach an old/different task's claims or promote candidate evidence.

    Stable inline claim IDs target a local evidence appendix, so local-only
    notes remain navigable without inventing a public media URL. Inclusion
    choices also apply to the appendix and it never changes stored note text.
    """
    if not claim_map or not settings['include_note']:
        return note, []
    if (not isinstance(claim_map, dict) or claim_map.get('task_id') != str(task.id)
            or claim_map.get('schema_version') != CLAIM_SCHEMA_VERSION
            or claim_map.get('requires_rebuild')
            or claim_map.get('source_revision_kind') != 'normalized_note_utf8_sha256'
            or claim_map.get('source_revision') != hashlib.sha256(note.encode('utf-8')).hexdigest()):
        return note, [_CITATION_WARNING]
    claims = claim_map.get('claims', [])
    evidence = claim_map.get('evidence', [])
    if not isinstance(claims, list) or not isinstance(evidence, list):
        return note, [_CITATION_WARNING]
    by_id = _evidence_index(str(task.id), evidence, claim_map.get('evidence_revision'), transcript)
    if by_id is None:
        return note, [_CITATION_WARNING]
    headings = Counter(section_anchor_id(text) for text in heading_texts)
    pieces, appendix, seen = [], [], set()
    cursor = 0
    warnings = []
    source_url = safe_url(getattr(task, 'page_url', '')) if settings['include_source_link'] else ''

    def literal(value) -> str:
        value = re.sub(r'\s+', ' ', sanitize(str(value or ''))).strip()
        return re.sub(r'([\\`*_{}\[\]()<>!#|])', r'\\\1', value)

    statuses = {'direct': '原文匹配；请核对来源', 'located_only': '仅定位；未验证支持',
                'inference': '推断；需回源核对', 'pending_review': '待核对；未找到支持来源'}
    for claim in claims:
        if not isinstance(claim, dict):
            warnings.append(_CITATION_WARNING); continue
        cid = str(claim.get('claim_id') or '')
        span = claim.get('source_span')
        if not isinstance(span, dict):
            warnings.append(_CITATION_WARNING); continue
        start, end = span.get('start'), span.get('end')
        status = claim.get('verification')
        if (not re.fullmatch(r'claim-[a-f0-9]{20}', cid) or cid in seen
                or not isinstance(status, str) or status not in statuses or type(start) is not int or type(end) is not int
                or start < cursor or not start < end <= len(note) or note[start:end] != claim.get('text')
                or span.get('unit') != 'unicode_codepoints'):
            warnings.append(_CITATION_WARNING); continue
        direct = status == 'direct'
        selected = claim.get('evidence_ids' if direct else 'candidate_evidence_ids', [])
        if (not isinstance(selected, list) or any(not isinstance(eid, str) or eid not in by_id for eid in selected)
                or direct and not selected):
            warnings.append(_CITATION_WARNING)
            continue
        matched = [by_id[eid] for eid in dict.fromkeys(selected)]
        seen.add(cid)
        heading = '证据引用 ' + cid
        base = section_anchor_id(heading); headings[base] += 1
        target = section_anchor_id(heading, headings[base])
        pieces.extend((note[cursor:end], f' [{cid}](#{target})'))
        cursor = end
        appendix.extend(['#### ' + heading, '', statuses[status] + '。', ''])
        if not matched:
            appendix.extend(['没有可导出的支持来源。', ''])
        for item in matched:
            kind = str(item.get('kind') or '')
            label = ('支持来源' if direct else '候选定位，不代表支持') + '：' + literal(item.get('evidence_id'))
            url = ''
            if kind in {'transcript', 'visual'}:
                label += '；' + ('字幕' if kind == 'transcript' else '画面')
                start_time = item.get('start')
                if isinstance(start_time, (int, float)) and math.isfinite(start_time) and start_time >= 0 and settings['include_timestamps']:
                    seconds = int(start_time)
                    timestamp = f'{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'
                    label += ' ' + timestamp
                    url = timed_url(source_url, timestamp) if source_url else ''
                elif source_url: url = source_url
            elif kind == 'document':
                label += '；' + literal(item.get('locator'))
                if settings['include_source_link']: url = safe_url(item.get('source_uri'))
            # Parentheses are valid in URL paths but delimit Markdown links.
            url = url.replace('(', '%28').replace(')', '%29')
            appendix.extend(['- ' + label + (f' [打开来源]({url})' if url else ''), ''])
            if kind == 'document' or settings['include_transcript'] and kind == 'transcript':
                excerpt = literal(item.get('text'))
                if excerpt: appendix.extend(['> ' + excerpt, ''])
            if kind == 'visual' and settings['include_images']:
                grid = str(item.get('grid_url') or '')
                if re.fullmatch(r'/api/tasks/' + re.escape(str(task.id)) + r'/assets/[A-Za-z0-9_.-]+', grid):
                    appendix.extend([f'![{label}]({grid})', ''])
    pieces.append(note[cursor:])
    if appendix:
        pieces.append('\n\n## 逐条证据引用\n\n' + '\n'.join(appendix))
    return ''.join(pieces), list(dict.fromkeys(warnings))
