from __future__ import annotations

import unittest

from app.main import app


class DataExposureTests(unittest.TestCase):
    def test_private_data_root_is_not_mounted_as_static_content(self) -> None:
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertNotIn("/data", paths)
        self.assertNotIn("/data/{path:path}", paths)


if __name__ == "__main__":
    unittest.main()
