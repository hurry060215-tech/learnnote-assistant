"""Read-only Windows sharing flags and descriptor-transfer failure contracts."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app import personal_anchors as anchors


class SharedArtifactReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'draft.md'
        self.path.write_bytes(b'original')
        self.windows_os = SimpleNamespace(**vars(os))
        self.windows_os.name = 'nt'
        self.windows_os.O_BINARY, self.windows_os.O_NOINHERIT = 0x8000, 0x80

    def test_native_handle_flags_and_successful_transfer_have_one_owner(self):
        kernel = SimpleNamespace(CreateFileW=Mock(return_value=123), CloseHandle=Mock())
        convert = Mock(return_value=45)
        with patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                patch.dict(sys.modules, {'msvcrt': SimpleNamespace(open_osfhandle=convert)}), \
                patch.object(anchors, 'os', self.windows_os):
            self.assertEqual(anchors._shared_read_descriptor(self.path), 45)
        kernel.CreateFileW.assert_called_once_with(str(self.path), 0x80000000, 7, None, 3, 0x00200000, None)
        convert.assert_called_once_with(123, os.O_RDONLY | 0x8000 | 0x80)
        kernel.CloseHandle.assert_not_called()

    def test_native_open_and_conversion_failures_do_not_leak_handles(self):
        for invalid in (True, False):
            kernel = SimpleNamespace(CreateFileW=Mock(return_value=ctypes.c_void_p(-1).value if invalid else 123), CloseHandle=Mock())
            primary = OSError('synthetic transfer failure')
            convert = Mock(side_effect=primary)
            with self.subTest(invalid=invalid), \
                    patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
                    patch.object(ctypes, 'WinError', return_value=primary, create=True), \
                    patch.object(ctypes, 'get_last_error', return_value=5, create=True), \
                    patch.dict(sys.modules, {'msvcrt': SimpleNamespace(open_osfhandle=convert)}), \
                    patch.object(anchors, 'os', self.windows_os), self.assertRaises(OSError) as caught:
                anchors._shared_read_descriptor(self.path)
            self.assertIs(caught.exception, primary)
            if invalid:
                convert.assert_not_called(); kernel.CloseHandle.assert_not_called()
            else:
                kernel.CloseHandle.assert_called_once_with(123)

    def test_default_callers_keep_original_opener_and_fdopen_failure_closes_descriptor(self):
        with patch.object(anchors, 'owned_task_artifact', return_value=self.path), \
                patch.object(anchors, '_shared_read_descriptor') as shared:
            with anchors._opened_artifact('fixture', str(self.path)) as stream:
                self.assertEqual(stream.read(), b'original')
            shared.assert_not_called()
        descriptor = os.open(self.path, os.O_RDONLY)
        with patch.object(anchors, 'owned_task_artifact', return_value=self.path), \
                patch.object(anchors, 'os', self.windows_os), \
                patch.object(anchors, '_shared_read_descriptor', return_value=descriptor), \
                patch.object(self.windows_os, 'fdopen', side_effect=OSError('synthetic fdopen failure')):
            with anchors._opened_artifact('fixture', str(self.path), share_delete=True) as stream:
                self.assertIsNone(stream)
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_opt_in_rejects_swapped_descriptor_and_revoked_path_ownership_before_read(self):
        for swapped in (True, False):
            descriptors = []
            def opening(path):
                if swapped:
                    other = path.with_name('replacement.md'); other.write_bytes(b'not the opened artifact')
                    other.replace(path)
                descriptor = os.open(path, os.O_RDONLY)
                descriptors.append(descriptor)
                return descriptor
            ownership = [self.path, self.path if swapped else None]
            with self.subTest(swapped=swapped), \
                    patch.object(anchors, 'owned_task_artifact', side_effect=ownership), \
                    patch.object(anchors, 'os', self.windows_os), \
                    patch.object(anchors, '_shared_read_descriptor', side_effect=opening):
                with anchors._opened_artifact('fixture', str(self.path), share_delete=True) as stream:
                    self.assertIsNone(stream)
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])


if __name__ == '__main__':
    unittest.main()
