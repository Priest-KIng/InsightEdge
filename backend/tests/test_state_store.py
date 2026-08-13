from app.schemas import ChatTurn
from app.services.state_store import StateStore


def test_ingest_job_updates_are_whitelisted(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.create_ingest_job("job-1", 2)

    store.update_ingest_job("job-1", status="running", files_processed=1, unsafe_field="ignored")
    job = store.get_ingest_job("job-1")

    assert job is not None
    assert job["status"] == "running"
    assert job["files_processed"] == 1


def test_clear_workspace_removes_chat_history(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.set_chat_history(
        "session-1",
        [ChatTurn(role="user", content="hello")],
        workspace_id="research",
    )

    store.clear_workspace("research")

    assert store.get_chat_history("session-1", "research") == []


def test_chat_turn_timestamp_round_trips(tmp_path) -> None:
    store = StateStore(tmp_path / "state.db")
    store.set_chat_history(
        "session-2",
        [ChatTurn(role="user", content="hello", created_at="2026-08-07T00:00:00Z")],
        workspace_id="research",
    )

    history = store.get_chat_history("session-2", "research")

    assert history[0].created_at == "2026-08-07T00:00:00Z"
