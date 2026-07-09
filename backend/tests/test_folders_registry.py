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


def test_list_folders_merges_registry_and_counts(logged_in_admin, db_session):
    from app.models.email import EmailThread, EmailCategory, EmailStatus
    # A registry folder with no saved items -> appears with count 0.
    empty = SavedFolderRow(name="Empty Client", source="outlook",
                           outlook_folder_id="OF1", outlook_item_count=147)
    db_session.add(empty)
    # A saved thread filed under a registry-less legacy label -> still surfaces.
    t = EmailThread(id=uuid.uuid4(), client_email="c@x.com", subject="s",
                    category=EmailCategory.general_inquiry, status=EmailStatus.categorized,
                    is_saved=True, saved_folder="Legacy Label")
    db_session.add(t)
    db_session.commit()

    resp = logged_in_admin.get("/api/v1/emails/saved/folders")
    assert resp.status_code == 200, resp.text
    by_name = {f["name"]: f for f in resp.json()}
    assert by_name["Empty Client"]["count"] == 0
    assert by_name["Empty Client"]["source"] == "outlook"
    assert by_name["Empty Client"]["outlook_item_count"] == 147
    assert by_name["Legacy Label"]["count"] == 1  # defensive union
    assert by_name["Legacy Label"]["source"] == "app"
