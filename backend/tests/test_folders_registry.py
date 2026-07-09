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


def test_folder_schemas_exist():
    from app.schemas.email import (
        CreateFolderRequest, FolderImportResult, FolderSyncResult, SavedFolder,
    )
    req = CreateFolderRequest(name="X")
    assert req.parent_id is None
    sf = SavedFolder(name="X", count=0, thread_count=0, message_count=0)
    assert sf.source is None and sf.outlook_item_count is None
    assert FolderImportResult(imported=1, updated=2, total=3).total == 3
    assert FolderSyncResult(created=1, existing=2, total=3).created == 1
