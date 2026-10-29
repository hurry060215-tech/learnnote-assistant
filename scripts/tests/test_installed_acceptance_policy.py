"""Execute the workflow's real version selection without installs or network."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell is required for the release workflow')
class InstalledAcceptancePolicyTests(unittest.TestCase):
    def test_current_future_and_retained_versions_keep_their_required_gates(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        policy = source.split('          $installedPolicy = ', 1)[1].split('      - uses: actions/setup-python', 1)[0]
        policy = '$installedPolicy = ' + textwrap.dedent(policy)
        architecture = source.split('          $architectureArgs = @()', 1)[1].split('          python scripts/installed-upgrade-acceptance.py', 1)[0]
        architecture = '$architectureArgs = @()\n' + textwrap.dedent(architecture)
        for version, retained, expected_features, baseline, expected_architecture in [
            ('0.2.9', '', False, '', []),
            ('0.2.16', '123', False, 'v0.2.15', []),
            ('0.2.17', '', True, 'v0.2.16', ['--architecture']),
            ('0.2.17', '123', True, 'v0.2.16', []),
            ('0.2.18', '', True, '', ['--architecture']),
            ('0.2.18', '123', True, '', []),
            ('1.0.0', '', True, '', ['--architecture']),
        ]:
            with self.subTest(version=version, retained=retained), tempfile.TemporaryDirectory() as directory:
                env_path = Path(directory) / 'github-env'
                # The harness source version is deliberately newer than retained
                # candidates; retained scope must follow the verified candidate.
                current = '1.0.0' if retained else version
                script = (f"$ErrorActionPreference='Stop'; $version='{current}'; $env:RELEASE_TAG='v{version}'; "
                          f"$env:CANDIDATE_ARTIFACT_ID='{retained}'; $env:GITHUB_ENV=[Console]::In.ReadToEnd().Trim();\n"
                          + policy + "\n$env:INSTALLED_FEATURES=$featuresRequired.ToString().ToLowerInvariant();\n"
                          + architecture + "\n@{features=$featuresRequired;baseline=$previousTag;architecture=@($architectureArgs)} | ConvertTo-Json -Compress")
                result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script], cwd=ROOT,
                                        input=str(env_path), capture_output=True, text=True, timeout=30, check=True)
                observed = json.loads(result.stdout)
                self.assertEqual(observed, {'features': expected_features, 'baseline': baseline, 'architecture': expected_architecture})
                self.assertIn('INSTALLED_FEATURES=' + str(expected_features).lower(), env_path.read_text(encoding='utf-8-sig'))

    def test_previous_release_selection_uses_semantic_older_stable_version(self):
        source = (ROOT / '.github/workflows/desktop-release.yml').read_text(encoding='utf-8')
        selection = source.split('$previous = gh release list', 1)[1].split('            if ($LASTEXITCODE', 1)[0]
        selection = 'Where-Object ' + selection.split('Where-Object ', 1)[1].strip()
        records = [
            {'tagName': 'v0.2.19', 'publishedAt': '2026-11-01'},
            {'tagName': 'v0.2.17', 'publishedAt': '2026-10-26'},
            {'tagName': 'v0.2.16', 'publishedAt': '2026-10-30'},
            {'tagName': 'v0.2.9', 'publishedAt': '2026-10-31'},
            {'tagName': 'v0.2.18', 'publishedAt': '2026-10-29'},
            {'tagName': 'v0.2.17', 'isDraft': True, 'publishedAt': '2026-11-02'},
            {'tagName': 'v0.2.18', 'isPrerelease': True, 'publishedAt': '2026-11-02'},
            {'tagName': 'not-a-version', 'publishedAt': '2026-11-03'},
        ]
        records = [{'isDraft': False, 'isPrerelease': False, **record} for record in records]
        script = "$currentTag='v0.2.18'; [Console]::In.ReadToEnd() | ConvertFrom-Json | " + selection + ' | ConvertTo-Json -Compress'
        result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', script], cwd=ROOT,
                                input=json.dumps(records), capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout), records[1])


if __name__ == '__main__':
    unittest.main()
