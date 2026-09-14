import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktop import main as desktop

ROOT = Path(__file__).resolve().parents[2]


class UpdateRecoveryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell.exe"), "Windows updater contract")
    def test_real_rollback_preserves_nested_data_and_restart_port(self):
        with tempfile.TemporaryDirectory(prefix="update-rollback-test-", dir=ROOT / "build") as directory:
            sandbox=Path(directory).resolve()
            self.assertTrue(sandbox.is_relative_to((ROOT / "build").resolve()))
            root=sandbox/"app";data=root/"storage"/"notes";data.mkdir(parents=True)
            (data/"note.txt").write_text("personal note")
            (root/"LearnNote.exe").write_bytes(b"old program")
            installer=data/"installers/v9.8.7/LearnNote-Setup-x64.exe"
            installer.parent.mkdir(parents=True);installer.write_bytes(b"test package")
            api=desktop.DesktopApi(data, "http://127.0.0.1:18898", app_root=root)
            api._bind_window(Mock())
            receipt={"path":str(installer),"version":"9.8.7","bytes":installer.stat().st_size,"sha256":hashlib.sha256(installer.read_bytes()).hexdigest()}
            api._remember_download(receipt)
            restarted=desktop.DesktopApi(data, app_root=root)
            self.assertEqual(restarted._update_state["phase"],"ready")
            with patch.object(desktop,"application_root",return_value=root),patch.object(desktop.subprocess,"Popen"),patch.object(desktop.threading,"Timer"):
                result=api.install_update("9.8.7",str(installer))
            script=(installer.parent/"install-update.ps1").read_text(encoding="utf-8-sig")
            self.assertIn("$restartPort = 18898",script)
            self.assertEqual(script.count("'-"+"-port', $restartPort"),4)
            function=script[script.index("function Copy-RollbackFiles"):script.index("function Write-UpdateResult")]
            (root/"LearnNote.exe").write_bytes(b"broken update")
            (root/"new-file.dll").write_bytes(b"new file")
            quote=lambda p:"'"+str(p).replace("'","''")+"'"
            helper=sandbox/"test-rollback.ps1"
            helper.write_text("$ErrorActionPreference='Stop'\n"+function+"\nCopy-RollbackFiles "+" ".join(map(quote,[result["rollback"],root,data])),encoding="utf-8-sig")
            subprocess.run(["powershell.exe","-NoProfile","-File",str(helper)],check=True,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual((data/"note.txt").read_text(),"personal note")
            self.assertEqual((root/"LearnNote.exe").read_bytes(),b"old program")
            self.assertFalse((root/"new-file.dll").exists())
            installer.write_bytes(b"tampered")
            api=desktop.DesktopApi(data, "http://127.0.0.1:18898", app_root=root)
            with patch.object(desktop.subprocess,"Popen") as launch:
                with self.assertRaisesRegex(ValueError,"更新包已变化"):
                    api.install_update("9.8.7",str(installer))
                launch.assert_not_called()
