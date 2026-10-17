"""Narrow source-literal equivalences for heuristic checks, not fact verification."""
from __future__ import annotations

from decimal import Decimal
import re

from .markdown_structure import structural_lines


_DIGITS = "零一二三四五六七八九"
_NUMERALS = "零〇一二两三四五六七八九十百千"
_UNSUPPORTED_NUMERALS = "万亿兆廿卅壹贰叁肆伍陆柒捌玖拾佰仟"
_SIGNS = "负正+−＋－±-"
_UNITS = {"℃": "摄氏度", "°c": "摄氏度", "％": "%", "kg": "千克", "公斤": "千克", "mg": "毫克"}
_UNIT_PATTERN = r"摄氏度|℃|°c|%|％|美元|人民币|万元|元|公斤|千克|毫克|毫米|厘米|kg|mg"
_NUMBER = (rf"[{re.escape(_SIGNS)}]*[\d{_NUMERALS}{_UNSUPPORTED_NUMERALS}]"
           rf"[\d{_NUMERALS}{_UNSUPPORTED_NUMERALS}.点{re.escape(_SIGNS)}]*?")
_AMOUNT = re.compile(
    rf"(?<![\d.{_NUMERALS}{_UNSUPPORTED_NUMERALS}点{re.escape(_SIGNS)}])"
    rf"(?P<number>{_NUMBER}(?:\s*(?:{_UNIT_PATTERN})?\s*[至到]\s*{_NUMBER})?)"
    rf"(?P<infix>多|余|来)?\s*(?P<unit>{_UNIT_PATTERN})", re.I)
_QUALIFIER_BEFORE = re.compile(r"(?:(?:不超过|不少于|不低于|不高于|不多于|不小于|不大于|不等于|不是|并非|"
    r"约|大概|差不多|将近|超过|不足|至少|至多|不到|多于|少于|估计|预计|估算|可能|大致|接近)\s*(?:有|为|是|在|要)?|第|[~～–—])\s*$")
_QUALIFIER_AFTER = re.compile(r"\s*(?:左右|上下|以上|以下|以内|以外|多|余)")



def without_editorial_headings(markdown: str) -> str:
    # Only whole structural labels. The same words in prose, code, a named
    # entity or a longer heading must still pass the ordinary source check.
    pattern = re.compile(r" {0,3}#{1,6}\s+(?:Highlights|Part [1-9][0-9]{0,3})(?:\s+#+)?\s*", re.I)
    return "\n".join("" if prose and pattern.fullmatch(line) else line
                     for line, prose in structural_lines(markdown.splitlines()))


def _chinese_integer(number: int) -> str:
    if number == 0:
        return "零"
    result, pending_zero = "", False
    for place, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, number = divmod(number, place)
        if digit:
            result += ("零" if pending_zero else "") + _DIGITS[digit] + unit
            pending_zero = False
        elif result and number:
            pending_zero = True
    return result[1:] if result.startswith("一十") else result


def _literal_number(value: str) -> Decimal | None:
    value = value.replace("负", "-", 1) if value.startswith("负") else value.replace("正", "+", 1) if value.startswith("正") else value
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return Decimal(value)
    sign = "-" if value.startswith("-") else ""
    value = (value[1:] if value.startswith(("-", "+")) else value).replace("〇", "零").replace("两", "二")
    integer, dot, fraction = value.partition("点")
    if (dot and not fraction) or any(char not in _DIGITS for char in fraction):
        return None
    total, digit, previous = 0, 0, 10000
    for char in integer:
        if char in _DIGITS:
            digit = _DIGITS.index(char)
        else:
            place = {"十": 10, "百": 100, "千": 1000}.get(char, 0)
            if not place or place >= previous:
                return None
            total += (digit or (1 if not total and place == 10 else 0)) * place
            digit, previous = 0, place
    total += digit
    # Round-trip rejects ambiguous 一百一, serial digits, repeated zero/unit
    # strings and approximation; this is deliberately not a general NLP parser.
    if not 0 <= total <= 9999 or _chinese_integer(total) != integer:
        return None
    decimal = "." + "".join(str(_DIGITS.index(char)) for char in fraction) if dot else ""
    return Decimal(sign + str(total) + decimal)


def literal_quantities(text: str) -> set[tuple[str, str, str, str, str]]:
    """Never drop a candidate amount. Qualified/ambiguous literals retain scope."""
    result = set()
    text = text.lower()
    for match in _AMOUNT.finditer(text):
        before = _QUALIFIER_BEFORE.search(text[max(0, match.start() - 16):match.start()])
        after = _QUALIFIER_AFTER.match(text[match.end():match.end() + 6])
        number = _literal_number(match["number"])
        if number is None:
            value = "literal:" + match["number"]
        else:
            value = format(number, "f")
            if "." in value:
                value = value.rstrip("0").rstrip(".")
            if match["number"].startswith(("正", "+")):
                value = "+" + value
        qualifier = lambda value: re.sub(r"\s+", "", value.group()) if value else ""
        result.add((value, _UNITS.get(match["unit"], match["unit"]),
                    qualifier(before), match["infix"] or "", qualifier(after)))
    return result


def unsupported_quantity_labels(note: str, evidence: str) -> list[str]:
    return [before + value.removeprefix("literal:") + infix + unit + after
            for value, unit, before, infix, after in sorted(literal_quantities(note) - literal_quantities(evidence))]


def source_scoped_duration(note: str, match: re.Match, evidence: str) -> bool:
    """Only exact source sentences with explicit report/quote/negation syntax.

    A generated quotation or a reworded attribution is not enough. This avoids
    treating a faithfully quoted duration of another video as this file's length.
    It makes no claim to understand arbitrary negation or reported opinions.
    """
    separators = re.compile(r"[\n。！？!?]")
    start = max((item.end() for item in separators.finditer(note, 0, match.start())), default=0)
    end_match = separators.search(note, match.end())
    end = end_match.start() if end_match else len(note)
    sentence = note[start:end]
    def canonical(value):
        return value.strip()
    exact = canonical(sentence)
    if not exact or exact not in {canonical(value) for value in separators.split(evidence)}:
        return False
    prefix = note[start:match.start()]
    if re.fullmatch(r"\s*(?:我|我们|他|她|他们|她们|主持人|嘉宾)?\s*(?:不认为|不认同|不同意|否认)\s*", prefix):
        return True
    if re.search(r"(?:说|表示|提到|转述|声称)[：:]\s*$", prefix):
        return True
    for quote in re.finditer(r'“[^”\n]+”|「[^」\n]+」|"[^"\n]+"', sentence):
        if quote.start() <= match.start() - start and quote.end() >= match.end() - start:
            return True
    return False
