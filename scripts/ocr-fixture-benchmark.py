"""Local synthetic OCR/cache report; never a vision-model quality benchmark."""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    from app.local_ocr import create_ocr_engine, recognize_frames
    from app.models import FrameSample

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    latin = next((path for path in [Path("C:/Windows/Fonts/arial.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/System/Library/Fonts/Supplemental/Arial.ttf")] if path.is_file()), None)
    cjk = next((path for path in [Path("C:/Windows/Fonts/msyh.ttc"), Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"), Path("/System/Library/Fonts/PingFang.ttc")] if path.is_file()), None)
    if latin is None:
        raise RuntimeError("Synthetic OCR benchmark requires a Latin fixture font")
    fixtures = [
        ("english", "LEARNING RATE", latin, False),
        ("chinese", "学习笔记", cjk, False),
        ("code", "for i in range(3):", latin, False),
        ("formula", "E = mc²", latin, False),
        ("slide", "课程目标 2026", cjk, False),
        ("low-resolution", "LEARNING RATE", latin, True),
    ]
    samples, expected, missing = [], [], []
    for index, (name, text, font_path, low_resolution) in enumerate(fixtures):
        if font_path is None:
            missing.append(name)
            continue
        image = Image.new("RGB", (900, 180), "white")
        ImageDraw.Draw(image).text((30, 50), text, font=ImageFont.truetype(str(font_path), 48), fill="black")
        if low_resolution:
            image = image.resize((90, 18)).resize((900, 180)).filter(ImageFilter.GaussianBlur(1.5))
        path = output / (name + ".png")
        image.save(path)
        samples.append(FrameSample(path=str(path), timestamp=index * 10))
        expected.append((name, text, index * 10))
    engine = create_ocr_engine()
    calls = 0
    def counted(path):
        nonlocal calls
        calls += 1
        return engine(path)
    started = time.monotonic()
    first = recognize_frames(samples, limit=12, engine=counted, cache_dir=output / "cache")
    first_seconds, first_calls = time.monotonic() - started, calls
    started = time.monotonic()
    second = recognize_frames(samples, limit=12, engine=counted, cache_dir=output / "cache")
    second_seconds, second_calls = time.monotonic() - started, calls - first_calls
    rows = []
    for name, truth, timestamp in expected:
        frame = next((value for value in first["frames"] if value["timestamp"] == timestamp), {})
        recognized = " ".join(line["text"] for line in frame.get("lines", []))
        rows.append({"fixture": name, "expected": truth, "recognized": recognized,
                     "character_similarity": round(SequenceMatcher(None, truth, recognized).ratio(), 3),
                     "status": frame.get("status", "failed"), "requires_review": True})
    unreviewed = all(line["verification"] == "unreviewed" for frame in first["frames"] for line in frame["lines"])
    passed = first["status"] == "ready" and second_calls == 0 and second["cache_hits"] == len(samples) and unreviewed
    report = {"schema_version": 1, "status": "pass" if passed else "fail", "fixtures": rows,
              "missing_font_fixtures": missing, "first_engine_calls": first_calls, "repeat_engine_calls": second_calls,
              "first_seconds": round(first_seconds, 3), "repeat_seconds": round(second_seconds, 3),
              "all_output_unreviewed": unreviewed, "remote_calls": 0,
              "visual_model_call_reduction": "not measured; OCR cache reuse is not a remote-vision benchmark",
              "privacy": "self-generated images only; no URLs, credentials, real course media or network"}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
