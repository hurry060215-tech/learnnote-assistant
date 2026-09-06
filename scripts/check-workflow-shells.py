"""Parse Windows workflow run blocks with PowerShell without executing them."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def windows_blocks(path: Path):
    lines = path.read_text(encoding="utf-8").splitlines()
    windows = False
    shell = ""
    for index, line in enumerate(lines):
        if "runs-on:" in line:
            windows = "windows" in line
        if re.match(r"\s+- (?:name|uses):", line):
            shell = ""
        if re.match(r"\s+shell:", line):
            shell = line.split(":", 1)[1].strip()
        if not re.match(r"\s+run:\s*[|>]", line) or not (shell == "pwsh" or windows and not shell):
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for candidate in lines[index + 1:]:
            if candidate.strip() and len(candidate) - len(candidate.lstrip()) <= indent:
                break
            body.append(candidate[indent + 2:])
        script = (" " if line.rstrip().endswith(">") else "\n").join(body)
        # Expressions are expanded by Actions before PowerShell sees the block.
        yield index + 1, re.sub(r"\$\{\{.*?\}\}", "fixture", script)


def main() -> int:
    pwsh = shutil.which("pwsh") or shutil.which("powershell")
    if not pwsh:
        raise RuntimeError("PowerShell is required to validate Windows workflow syntax")
    failures, checked = [], 0
    parser = "$t=$null; $e=$null; [System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$t,[ref]$e) | Out-Null; if($e.Count){$e | ForEach-Object {$_.Message}; exit 1}"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        helper = root / "parse.ps1"
        helper.write_text(parser, encoding="utf-8-sig")
        for workflow in sorted((ROOT / ".github/workflows").glob("*.yml")):
            for line, source in windows_blocks(workflow):
                script = root / "block.ps1"
                script.write_text(source, encoding="utf-8-sig")
                result = subprocess.run([pwsh, "-NoProfile", "-File", str(helper), str(script)], capture_output=True, text=True, encoding="utf-8", errors="replace")
                checked += 1
                if result.returncode:
                    failures.append({"workflow": workflow.name, "line": line, "error": result.stdout.strip() or result.stderr.strip()})
    print(json.dumps({"blocks_checked": checked, "failures": failures}, ensure_ascii=False))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
