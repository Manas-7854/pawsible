import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def secure_data_dir(path: Path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def secure_data_file(path: Path):
    secure_data_dir(path.parent)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        secure_data_file(path)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'complete', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open', due_date TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY, content TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        self.db.commit()

    def setting(self, key, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.db:
            self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def new_conversation(self, title="New conversation"):
        stamp = now()
        with self.db:
            return self.db.execute("INSERT INTO conversations(title,created_at,updated_at) VALUES (?,?,?)", (title, stamp, stamp)).lastrowid

    def conversations(self):
        return self.db.execute("SELECT * FROM conversations ORDER BY updated_at DESC, id DESC").fetchall()

    def rename_conversation(self, ident, title):
        title = title.strip()
        if not title:
            raise ValueError("A title is required")
        with self.db:
            self.db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now(), ident))

    def delete_conversation(self, ident):
        with self.db:
            self.db.execute("DELETE FROM conversations WHERE id=?", (ident,))

    def messages(self, ident):
        return self.db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (ident,)).fetchall()

    def add_message(self, ident, role, content, status="complete"):
        stamp = now()
        with self.db:
            mid = self.db.execute("INSERT INTO messages(conversation_id,role,content,status,created_at) VALUES (?,?,?,?,?)", (ident, role, content, status, stamp)).lastrowid
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (stamp, ident))
        return mid

    def update_message(self, ident, content, status):
        with self.db:
            self.db.execute("UPDATE messages SET content=?,status=? WHERE id=?", (content, status, ident))

    def tasks(self, status=None):
        if status:
            return self.db.execute("SELECT * FROM todos WHERE status=? ORDER BY due_date IS NULL,due_date,id", (status,)).fetchall()
        return self.db.execute("SELECT * FROM todos ORDER BY status,due_date IS NULL,due_date,id").fetchall()

    def add_task(self, title, notes="", due_date=None):
        title = title.strip()
        if not title:
            raise ValueError("Task title is required")
        if due_date:
            due_date = datetime.fromisoformat(due_date).date().isoformat()
        stamp = now()
        with self.db:
            return self.db.execute("INSERT INTO todos(title,notes,due_date,created_at,updated_at) VALUES (?,?,?,?,?)", (title, notes.strip(), due_date, stamp, stamp)).lastrowid

    def update_task(self, ident, title=None, notes=None, due_date=None, status=None):
        row = self.db.execute("SELECT * FROM todos WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError(f"Task #{ident} does not exist. Ask which task the user means.")
        title = row["title"] if title is None else title.strip()
        if not title:
            raise ValueError("Task title is required")
        notes = row["notes"] if notes is None else notes.strip()
        due_date = row["due_date"] if due_date is None else (datetime.fromisoformat(due_date).date().isoformat() if due_date else None)
        status = row["status"] if status is None else status
        if status not in ("open", "done"):
            raise ValueError("Status must be open or done")
        with self.db:
            self.db.execute("UPDATE todos SET title=?,notes=?,due_date=?,status=?,updated_at=? WHERE id=?", (title, notes, due_date, status, now(), ident))

    def complete_task(self, ident):
        self.update_task(ident, status="done")

    def delete_task(self, ident):
        with self.db:
            self.db.execute("DELETE FROM todos WHERE id=?", (ident,))

    def memories(self):
        return self.db.execute("SELECT * FROM memories ORDER BY id DESC").fetchall()

    def add_memory(self, content):
        content = content.strip()
        if not content:
            raise ValueError("Memory cannot be empty")
        stamp = now()
        with self.db:
            return self.db.execute("INSERT INTO memories(content,created_at,updated_at) VALUES (?,?,?)", (content, stamp, stamp)).lastrowid

    def update_memory(self, ident, content):
        content = content.strip()
        if not content:
            raise ValueError("Memory cannot be empty")
        with self.db:
            self.db.execute("UPDATE memories SET content=?,updated_at=? WHERE id=?", (content, now(), ident))

    def delete_memory(self, ident):
        with self.db:
            self.db.execute("DELETE FROM memories WHERE id=?", (ident,))
