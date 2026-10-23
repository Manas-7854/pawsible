import os
import stat
import threading
from types import SimpleNamespace

from google.genai import types

from jamun.app import load_private_env, migrate_legacy_data
from jamun.storage import Store
from jamun.provider import GeminiProvider, execute_task_call


def test_persistence_and_task_validation(tmp_path):
    path = tmp_path / "jamun.sqlite3"
    store = Store(path)
    conversation = store.new_conversation("First")
    store.add_message(conversation, "user", "hello")
    assert execute_task_call(store, "add_task", {"title": "Buy fish", "due_date": "2026-10-20"}) == {"success": True, "task_id": 1}
    assert execute_task_call(store, "complete_task", {"task_id": 99})["success"] is False
    assert execute_task_call(store, "complete_task", {"task_id": 1})["success"] is True
    store.add_memory("I like short replies")
    store.set_setting("size", 6)
    store.db.close()

    reopened = Store(path)
    assert reopened.messages(conversation)[0]["content"] == "hello"
    assert reopened.tasks()[0]["status"] == "done"
    assert reopened.memories()[0]["content"] == "I like short replies"
    assert reopened.setting("size") == "6"
    assert execute_task_call(reopened, "update_task", {"task_id": 1, "status": "invalid"})["success"] is False
    assert reopened.tasks()[0]["status"] == "done"


def test_existing_data_and_key_files_become_private(tmp_path, monkeypatch):
    data_dir = tmp_path / "jamun"
    store = Store(data_dir / "jamun.sqlite3")
    store.db.close()
    data_dir.chmod(0o755)
    (data_dir / "jamun.sqlite3").chmod(0o644)
    reopened = Store(data_dir / "jamun.sqlite3")
    reopened.db.close()
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((data_dir / "jamun.sqlite3").stat().st_mode) == 0o600

    key_file = tmp_path / ".env"
    key_file.write_text("GEMINI_API_KEY=test-only-key\n")
    key_file.chmod(0o644)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    load_private_env(key_file)
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert os.environ["GEMINI_API_KEY"] == "test-only-key"


def test_ambiguous_duplicate_task_requires_id(tmp_path):
    store = Store(tmp_path / "todos.sqlite3")
    store.add_task("Call Alex")
    store.add_task("Call Alex")
    assert execute_task_call(store, "complete_task", {"task_id": 1}, "Complete Call Alex")["success"] is False
    assert execute_task_call(store, "complete_task", {"task_id": 1}, "Complete #1")["success"] is True


def test_model_cannot_change_tasks_without_approval(tmp_path, monkeypatch):
    store = Store(tmp_path / "jamun.sqlite3")
    store.add_task("Keep this task")

    class FakeModels:
        def generate_content_stream(self, *, contents, **kwargs):
            part = (types.Part.from_function_call(name="complete_task", args={"task_id": 1})
                    if not contents else types.Part.from_text(text="Finished"))
            yield SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    class FakeClient:
        models = FakeModels()

        def close(self):
            pass

    monkeypatch.setattr("jamun.provider.genai.Client", lambda **kwargs: FakeClient())
    provider = GeminiProvider("test-key", "test-model", tmp_path / "jamun.sqlite3")
    provider.stream([], [], [], lambda text: None, threading.Event())
    assert store.tasks()[0]["status"] == "open"

    provider.approve_task_change = lambda name, args: name == "complete_task" and args == {"task_id": 1}
    provider.stream([], [], [], lambda text: None, threading.Event())
    assert store.tasks()[0]["status"] == "done"


def test_failed_stream_discards_partial_task_calls_before_retry(tmp_path, monkeypatch):
    class RetryableError(Exception):
        code = 503

    class FakeModels:
        attempts = 0

        def generate_content_stream(self, *, contents, **kwargs):
            if contents:
                assert len(contents[-2].parts) == 1
                assert len(contents[-1].parts) == 1
                yield SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[types.Part.from_text(text="Saved")]))])
                return
            self.attempts += 1
            yield SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[types.Part.from_function_call(name="add_task", args={"title": "Buy milk"})]))])
            if self.attempts == 1:
                raise RetryableError()

    class FakeClient:
        models = FakeModels()

        def close(self):
            pass

    monkeypatch.setattr("jamun.provider.genai.Client", lambda **kwargs: FakeClient())
    path = tmp_path / "jamun.sqlite3"
    approvals = []
    provider = GeminiProvider("test-key", "test-model", path)
    provider.approve_task_change = lambda name, args: approvals.append((name, args)) or True
    provider.stream([], [], [], lambda text: None, threading.Event())

    assert FakeClient.models.attempts == 2
    assert approvals == []
    assert [row["title"] for row in Store(path).tasks()] == ["Buy milk"]


def test_legacy_data_migrates_without_overwriting_or_deleting_source(tmp_path):
    old_path = tmp_path / "Pengu" / "pengu.sqlite3"
    old = Store(old_path)
    ident = old.new_conversation("Existing chat")
    old.add_message(ident, "user", "keep this")
    old.add_task("existing todo")
    old.add_memory("existing memory")
    old.set_setting("size", "7")
    old.db.close()

    new_path = migrate_legacy_data(tmp_path / "jamun", old_path)
    assert stat.S_IMODE(new_path.stat().st_mode) == 0o600
    migrated = Store(new_path)
    assert migrated.messages(ident)[0]["content"] == "keep this"
    assert migrated.tasks()[0]["title"] == "existing todo"
    assert migrated.memories()[0]["content"] == "existing memory"
    assert migrated.setting("size") == "7"
    migrated.add_memory("new-only memory")
    migrated.db.close()

    assert migrate_legacy_data(tmp_path / "jamun", old_path) == new_path
    assert len(Store(new_path).memories()) == 2
    assert len(Store(old_path).memories()) == 1
