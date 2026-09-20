"""Execute the real publisher against a disk-backed, offline gh fixture."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
param([string]$Publisher)
function global:gh {
    $global:LASTEXITCODE = 0
    $op = $args[1]
    Add-Content -LiteralPath operations.log -Value $op
    switch ($op) {
        'view' { Write-Output (Get-Content remote/state.json -Raw) }
        'upload' {
            $name = Split-Path $args[3] -Leaf
            if ((Get-Content remote/state.json -Raw | ConvertFrom-Json).isDraft -eq $false) { throw 'Published asset upload attempted' }
            if ($name -eq 'b.exe' -and (Test-Path fail-once)) {
                Move-Item -LiteralPath fail-once -Destination failed-once
                $global:LASTEXITCODE = 1
                return
            }
            Copy-Item -LiteralPath $args[3] -Destination (Join-Path remote $name) -Force
        }
        'download' {
            $name = $args[([array]::IndexOf($args, '--pattern') + 1)]
            $destination = $args[([array]::IndexOf($args, '--dir') + 1)]
            Copy-Item -LiteralPath (Join-Path remote $name) -Destination (Join-Path $destination $name)
        }
        'edit' { Set-Content -LiteralPath remote/state.json -Value '{"isDraft":false,"tagName":"v0.0.0"}' }
        default { throw "Unexpected gh operation: $op" }
    }
}
& $Publisher -Tag v0.0.0 -Repository fixture/example
'''


class ReleaseResumeTests(unittest.TestCase):
    def test_partial_draft_recovers_and_published_rerun_is_read_only(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote'
            remote.mkdir()
            (remote / 'state.json').write_text(json.dumps({'isDraft': True}))
            (root / 'harness.ps1').write_text(HARNESS, encoding='utf-8')
            entries = []
            for name in ('a.zip', 'b.exe', 'c.json'):
                payload = ('fixture-' + name).encode()
                (root / name).write_bytes(payload)
                entries.append(f'{hashlib.sha256(payload).hexdigest()}  {name}')
            (root / 'SHA256SUMS.txt').write_text('\n'.join(entries), encoding='ascii')
            (root / 'fail-once').touch()
            command = [pwsh, '-NoProfile', '-File', str(root / 'harness.ps1'), str(ROOT / 'scripts/publish-release.ps1')]
            def run():
                return subprocess.run(command, cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
            failed = run()
            self.assertNotEqual(failed.returncode, 0)
            self.assertTrue(json.loads((remote / 'state.json').read_text())['isDraft'])
            resumed = run()
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertFalse(json.loads((remote / 'state.json').read_text())['isDraft'])
            before = (root / 'operations.log').read_text().splitlines()
            rerun = run()
            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            after = (root / 'operations.log').read_text().splitlines()[len(before):]
            self.assertNotIn('upload', after)
            self.assertNotIn('edit', after)
            (remote / 'a.zip').write_bytes(b'corrupted-public-asset')
            before = (root / 'operations.log').read_text().splitlines()
            corrupted = run()
            self.assertNotEqual(corrupted.returncode, 0)
            after = (root / 'operations.log').read_text().splitlines()[len(before):]
            self.assertNotIn('upload', after)
            self.assertNotIn('edit', after)
            self.assertEqual((remote / 'a.zip').read_bytes(), b'corrupted-public-asset')
