from __future__ import annotations

import unittest

from app import TASK_SCHEMA_VERSION
from app.migrations import migrate_task_payload


class TaskMigrationTests(unittest.TestCase):
    def test_legacy_payload_gets_schema_version_without_dropping_fields(self) -> None:
        payload = migrate_task_payload({"id": "legacy", "title": "old", "custom": "preserve"})
        self.assertEqual(payload["schema_version"], TASK_SCHEMA_VERSION)
        self.assertEqual(payload["custom"], "preserve")


if __name__ == "__main__":
    unittest.main()
