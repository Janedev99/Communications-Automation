from __future__ import annotations
import uuid
from app.models.email import SavedFolderRow


def test_saved_folder_row_columns():
    row = SavedFolderRow(name="Acme Corp", source="app")
    assert row.name == "Acme Corp"
    assert row.source == "app"
    assert row.parent_id is None
    assert row.outlook_folder_id is None
    assert row.outlook_item_count is None


def test_saved_folder_row_tablename():
    assert SavedFolderRow.__tablename__ == "saved_folders"
