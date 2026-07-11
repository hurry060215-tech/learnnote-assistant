from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "learnnote-version.txt"
    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    version = str(manifest["version"])
    parts = [int(item) for item in version.split(".")]
    if len(parts) != 3:
        raise ValueError(f"Expected MAJOR.MINOR.PATCH, got {version}")
    numeric = tuple(parts + [0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numeric}, prodvers={numeric}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('080404b0', [
    StringStruct('CompanyName', 'LearnNote'),
    StringStruct('FileDescription', 'LearnNote 视频学习笔记'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('InternalName', 'LearnNote'),
    StringStruct('OriginalFilename', 'LearnNote.exe'),
    StringStruct('ProductName', 'LearnNote'),
    StringStruct('ProductVersion', '{version}')
  ])]), VarFileInfo([VarStruct('Translation', [2052, 1200])])]
)
""",
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
