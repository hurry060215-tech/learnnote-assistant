"""The optional search receipt is copied unchanged, never trusted as task data."""
from contextlib import closing
import sqlite3
import unittest

from desktop.data_migration_catalog import CATALOG_SCHEMA_SQL, PROJECTION_REVISION_SQL, _validate_schema
from desktop.data_migration_paths import ReferenceMappingError


class CatalogProjectionRevisionTests(unittest.TestCase):
    def catalog(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript(CATALOG_SCHEMA_SQL)
        connection.execute("INSERT INTO library_meta VALUES ('schema_version', '3')")
        return connection

    def test_old_and_new_catalogs_keep_their_exact_schema_and_receipt(self):
        with closing(self.catalog()) as connection:
            old = _validate_schema(connection)
            connection.executescript(PROJECTION_REVISION_SQL)
            connection.execute("INSERT INTO task_projection_revisions VALUES ('synthetic', ?)", ("a" * 64,))
            new = _validate_schema(connection)
            self.assertTrue(set(old).issubset(new))
            self.assertEqual(connection.execute("SELECT * FROM task_projection_revisions").fetchall(), [("synthetic", "a" * 64)])

    def test_changed_receipt_schema_is_not_a_general_unknown_table_exemption(self):
        with closing(self.catalog()) as connection:
            connection.execute("CREATE TABLE task_projection_revisions(task_id TEXT PRIMARY KEY, signature TEXT)")
            with self.assertRaisesRegex(ReferenceMappingError, "unsupported_catalog_schema"):
                _validate_schema(connection)


if __name__ == "__main__":
    unittest.main()
