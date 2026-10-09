"""Offline emoji glyphs and Unicode text extraction for local PDF exports."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
import sys
from threading import Lock

_FONT_LOCK = Lock()
def bundled_emoji_font_path() -> Path:
    relative = Path('fonts/noto-emoji/NotoEmoji.ttf')
    adjacent = Path(__file__).parent / relative
    if adjacent.is_file():
        return adjacent
    # A frozen module can originate from PYZ at _MEIPASS/app while the
    # existing application data Tree lives under _MEIPASS/backend/app.
    bundle = getattr(sys, '_MEIPASS', None)
    return Path(bundle) / 'backend/app' / relative if bundle else adjacent


@lru_cache(maxsize=1)
def emoji_font():
    """Keep the optional PDF dependency lazy and never download a font."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    class UnicodeTTFont(TTFont):
        def addObjects(self, doc):
            # ReportLab 5.0 emits scalar hex for astral ToUnicode entries;
            # PDF requires UTF-16BE. Repair only this font's newly created
            # CMap streams, without changing library/global functions.
            existing = set(doc.idToObject)
            super().addObjects(doc)
            for name in set(doc.idToObject) - existing:
                if name.startswith('toUnicodeCMap:'):
                    stream = doc.idToObject[name]
                    stream.content = re.sub(
                        r'(<[0-9A-F]{2}>\s*)<([0-9A-F]{5,6})>',
                        lambda m: m[1] + '<' + chr(int(m[2], 16)).encode('utf-16-be').hex().upper() + '>',
                        stream.content,
                    )

    with _FONT_LOCK:
        name = 'LearnNoteEmoji'
        if name not in pdfmetrics.getRegisteredFontNames():
            path = bundled_emoji_font_path()
            if not path.is_file():
                return None
            pdfmetrics.registerFont(UnicodeTTFont(name, str(path)))
        return pdfmetrics.getFont(name)


def emoji_font_for(character: str) -> str:
    # ASCII/digits and ordinary prose keep their existing text font. ZWJ and
    # variation selectors stay in the text layer rather than being dropped.
    point = ord(character)
    if point < 0x2300 and point not in {0x200D, 0xFE0E, 0xFE0F}:
        return ''
    if not (point >= 0x1F000 or 0x2300 <= point <= 0x2BFF or point in {0x200D, 0xFE0E, 0xFE0F}):
        return ''
    font = emoji_font()
    return font.fontName if font and point in font.face.charToGlyph else ''
