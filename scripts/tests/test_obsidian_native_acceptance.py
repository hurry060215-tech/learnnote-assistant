from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]


class ObsidianNativeAcceptanceTests(unittest.TestCase):
    def test_official_app_download_is_pinned_and_signature_checked(self):
        text = (ROOT / '.github/workflows/obsidian-native-acceptance.yml').read_text(encoding="utf-8")
        workflow = yaml.safe_load(text)
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        self.assertEqual(workflow['jobs']['native-obsidian']['runs-on'], 'macos-latest')
        self.assertIn("version = '1.14.4'", text)
        self.assertIn('https://api.github.com/repos/obsidianmd/obsidian-releases/', text)
        self.assertIn('codesign --verify --deep --strict', text)
        self.assertNotIn('secrets.', text)
        download = next(step for step in workflow['jobs']['native-obsidian']['steps'] if step.get('name', '').startswith('Download pinned'))
        self.assertEqual(download['env'], {'GH_TOKEN': '${{ github.token }}'})
        native = next(step for step in workflow['jobs']['native-obsidian']['steps'] if step.get('name', '').startswith('Import update'))
        self.assertNotIn('env', native)
        self.assertNotIn('--no-sandbox', text)
        self.assertNotIn('xattr', text)
        self.assertNotIn('spctl --master-disable', text)
        self.assertNotIn('/Applications/', text)

    def test_harness_uses_disposable_profile_real_plugin_and_real_backend(self):
        text = (ROOT / 'scripts/obsidian-native-acceptance.cjs').read_text(encoding="utf-8")
        self.assertIn('fs.mkdtemp', text)
        self.assertIn('--user-data-dir=${profile}', text)
        self.assertIn("'integrations/obsidian-learnnote', name", text)
        self.assertIn("'-m', 'uvicorn', 'app.main:app'", text)
        self.assertIn('plugin.importer.importTask(await plugin.api.task(taskId))', text)
        self.assertNotIn('page.route(', text)
        self.assertNotIn('--no-sandbox', text)
        self.assertIn('assert.notEqual(secondMeta.annotation_snapshot, firstMeta.annotation_snapshot)', text)
        self.assertIn("getByRole('link', {name: '带时间戳字幕'", text)
        self.assertIn("status: 'failed'", text)
        self.assertIn("report.status = 'pass'", text)


if __name__ == '__main__':
    unittest.main()
