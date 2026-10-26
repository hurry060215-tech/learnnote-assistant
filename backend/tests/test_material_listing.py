from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import library
from app.library_listing import browse_materials


class MaterialListingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for target, value in [("app.library.DATA_DIR", self.root), ("app.library.ensure_dirs", lambda: None)]:
            self.enterContext(patch(target, value))
        connection, _ = library._connect()
        columns = connection.execute("PRAGMA table_info(library_materials)").fetchall()
        defaults = {row[1]: 0 if row[2] == "INTEGER" else "" for row in columns}
        self.names = list(defaults)
        records = []
        for index in range(605):
            row = {**defaults, "material_id": f"m-{index:04}", "sha256": str(index), "title": f"Synthetic {index}",
                   "updated_at": "same", "linked_task_id": f"task-{index}" if index >= 105 else "",
                   "metadata_json": "{}", "evidence_ids_json": "[]"}
            records.append(tuple(row[name] for name in self.names))
        connection.executemany(f"INSERT INTO library_materials ({','.join(self.names)}) VALUES ({','.join('?' for _ in self.names)})", records)
        connection.commit()
        connection.close()

    def test_linked_tasks_cannot_consume_the_standalone_page(self):
        first = browse_materials(limit=1000)
        self.assertEqual(first["total"], 105)
        self.assertEqual(len(first["materials"]), 100)
        self.assertTrue(first["has_more"])
        self.assertTrue(all(not row["linked_task_id"] for row in first["materials"]))
        second = browse_materials(cursor=first["next_cursor"])
        self.assertEqual(len(second["materials"]), 5)
        self.assertFalse(second["has_more"])
        self.assertEqual(len({row["material_id"] for row in first["materials"] + second["materials"]}), 105)

    def test_search_finds_old_material_without_loading_other_pages(self):
        result = browse_materials(query="Synthetic 0")
        self.assertEqual([row["material_id"] for row in result["materials"]], ["m-0000"])
        self.assertEqual(result["total"], 105)
        self.assertEqual(result["matched_total"], 1)
        self.assertEqual(library.get_material("m-0000")["title"], "Synthetic 0")

    def test_cursor_is_bound_to_query_and_literal_search_does_not_expand_wildcards(self):
        cursor = browse_materials(limit=1)["next_cursor"]
        for bad in ["not-base64", "a" * 2049, cursor]:
            with self.assertRaisesRegex(ValueError, "material_cursor_invalid"):
                browse_materials(query="changed", cursor=bad)
        self.assertEqual(browse_materials(query="%_")["materials"], [])

    def test_deleted_cursor_row_does_not_skip_or_duplicate_remaining_rows(self):
        first = browse_materials(limit=2)
        connection, _ = library._connect()
        connection.execute("DELETE FROM library_materials WHERE material_id=?", (first["materials"][-1]["material_id"],))
        connection.commit()
        connection.close()
        second = browse_materials(limit=2, cursor=first["next_cursor"])
        self.assertEqual([row["material_id"] for row in second["materials"]], ["m-0102", "m-0101"])


if __name__ == "__main__":
    unittest.main()
