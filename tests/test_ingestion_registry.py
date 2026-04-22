from backend.ingestion.registry import IngestStatus, TaskRegistry


def test_create_returns_uuid_and_sets_pending():
    reg = TaskRegistry()
    task_id = reg.create()
    assert len(task_id) == 36  # UUID string
    status = reg.get(task_id)
    assert status is not None
    assert status.status == "pending"
    assert status.chunks_stored is None
    assert status.error_msg is None


def test_update_changes_status_fields():
    reg = TaskRegistry()
    task_id = reg.create()
    reg.update(task_id, status="complete", chunks_stored=42)
    status = reg.get(task_id)
    assert status.status == "complete"
    assert status.chunks_stored == 42
    assert status.error_msg is None


def test_update_with_error():
    reg = TaskRegistry()
    task_id = reg.create()
    reg.update(task_id, status="error", error_msg="embedding failed")
    status = reg.get(task_id)
    assert status.status == "error"
    assert status.error_msg == "embedding failed"


def test_get_returns_none_for_unknown_id():
    reg = TaskRegistry()
    assert reg.get("nonexistent-id") is None


def test_update_unknown_id_does_not_raise():
    reg = TaskRegistry()
    reg.update("nonexistent-id", status="complete")  # should not raise


def test_multiple_tasks_are_independent():
    reg = TaskRegistry()
    id1 = reg.create()
    id2 = reg.create()
    reg.update(id1, status="complete", chunks_stored=10)
    assert reg.get(id2).status == "pending"
    assert reg.get(id1).chunks_stored == 10


def test_module_level_registry_is_task_registry_instance():
    from backend.ingestion.registry import registry
    assert isinstance(registry, TaskRegistry)
