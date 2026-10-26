"""SQLite metadata, immutable artifact directories, and compressed repair copies."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import threading
import uuid
import zlib

from ..drawing.errors import DrawingError
from ..models import HistoryEntry, HistoryResponse

ID = re.compile(r"[a-f0-9]{32}")
FILES = {"draft.json", "drawing.nc", "preview.svg", "job.json"}
ACTIVE_RUN_STATES = {"starting", "streaming", "pausing", "paused", "resuming", "stopping"}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes):
    return hashlib.sha256(data).hexdigest()


def directory(path: Path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise DrawingError("UNSAFE_PATH", "An application storage directory is a symlink.", 409)
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise DrawingError("UNSAFE_PATH", "Expected an application storage directory.", 409)
    return path


def read_regular(path: Path, limit=16_000_000):
    if any(parent.is_symlink() for parent in path.parents):
        raise DrawingError("UNSAFE_PATH", "Refusing a symlink in an artifact path.", 409)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise DrawingError("UNSAFE_FILE", "Expected a bounded regular artifact file.", 409)
        result = stream.read(limit + 1)
        if len(result) > limit:
            raise DrawingError("UNSAFE_FILE", "Artifact exceeds its size limit.", 409)
        return result


def sync_directory(path: Path):
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write(path: Path, data: bytes):
    if path.is_symlink():
        raise DrawingError("UNSAFE_PATH", "Refusing to replace a symlink.", 409)
    directory(path.parent)
    temp = path.parent / f".picasso-{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("xb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        if temp.exists():
            temp.unlink()


class Repository:
    def __init__(self, root: Path):
        self.root = directory(root.absolute())
        self.artifacts = directory(self.root / "artifacts")
        self.staging = directory(self.root / ".staging")
        self.recovery = directory(self.root / "recovery")
        self.backups = directory(self.root / "backups")
        self.database = self.root / "picasso.sqlite3"
        for name in ("picasso.sqlite3", "picasso.sqlite3-wal", "picasso.sqlite3-shm"):
            if (self.root / name).is_symlink():
                raise DrawingError("UNSAFE_PATH", "Database files must not be symlinks.", 409)
        self.lock = threading.RLock()
        self.recovery_notices = []
        with self.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("The history database was created by a newer Picasso version.")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS artifacts(
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, drawing_id TEXT NOT NULL,
                    parent_id TEXT, ordinal INTEGER NOT NULL, title TEXT NOT NULL, prompt TEXT NOT NULL,
                    generator TEXT NOT NULL, created_at TEXT NOT NULL, hashes TEXT NOT NULL, backup BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS history_order ON artifacts(kind,created_at DESC);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, revision TEXT NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profile_versions(id TEXT, revision TEXT, document TEXT NOT NULL, PRIMARY KEY(id,revision));
                CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, document TEXT NOT NULL);
                PRAGMA user_version=1;
            ''')
        self._recover()

    @contextmanager
    def connection(self):
        with self.lock:
            directory(self.root)
            if any((self.root / name).is_symlink() for name in ('picasso.sqlite3', 'picasso.sqlite3-wal', 'picasso.sqlite3-shm')):
                raise DrawingError("UNSAFE_PATH", "Database path changed to a symlink.", 409)
            db = sqlite3.connect(self.database, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            try:
                with db:
                    yield db
            finally:
                db.close()

    def _recover(self):
        with self.connection() as db:
            known = {row[0] for row in db.execute("SELECT id FROM artifacts")}
            for row in db.execute("SELECT id,document FROM transfers").fetchall():
                document = json.loads(row["document"])
                if document["status"] == "copying":
                    document.update(status="interrupted", message="Service restarted during export. Inspect target and retry explicitly.")
                    db.execute("UPDATE transfers SET document=? WHERE id=?", (json.dumps(document), row["id"]))
                    self.recovery_notices.append("An interrupted export requires review.")
            for row in db.execute("SELECT id,document FROM runs").fetchall():
                document = json.loads(row["document"])
                if document["state"] in ACTIVE_RUN_STATES:
                    document.update(state="interrupted", message="The application stopped during this USB run. The firmware stops host jobs after 3 s without the host; nothing resumes automatically. Re-check the machine before another run.")
                    db.execute("UPDATE runs SET document=? WHERE id=?", (json.dumps(document), row["id"]))
                    self.recovery_notices.append("An interrupted USB run requires review.")
        for parent in (self.staging, self.artifacts):
            for item in parent.iterdir():
                if item.is_symlink():
                    self.recovery_notices.append("A symlink in managed artifact storage was ignored.")
                    continue
                if item.is_dir() and (parent == self.staging or item.name not in known):
                    os.replace(item, self.recovery / f"orphan-{uuid.uuid4().hex}")
                    self.recovery_notices.append("Uncommitted save preserved in data/recovery; it was not reported as saved.")

    def artifact_path(self, identity: str):
        directory(self.artifacts)
        if not ID.fullmatch(identity):
            raise DrawingError("DRAFT_NOT_FOUND", "Drawing or job not found.", 404)
        path = self.artifacts / identity
        if path.is_symlink():
            raise DrawingError("UNSAFE_PATH", "Artifact directory is a symlink.", 409)
        return path

    def save(self, identity: str, kind: str, files: dict[str, bytes], metadata: dict):
        if not set(files) <= FILES:
            raise ValueError("Unknown managed artifact filename")
        final = self.artifact_path(identity)
        hashes = {name: sha(content) for name, content in files.items()}
        backup = zlib.compress(json.dumps({name: content.decode("utf-8") for name, content in files.items()}).encode())
        with self.lock:
            stage = directory(self.staging / uuid.uuid4().hex)
            try:
                for name, content in files.items():
                    atomic_write(stage / name, content)
                sync_directory(stage)
                if final.exists():
                    raise DrawingError("IMMUTABLE_CONFLICT", "A revision with this identity already exists.", 409)
                os.replace(stage, final)
                sync_directory(self.artifacts)
                with self.connection() as db:
                    db.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                        identity, kind, metadata["drawing_id"], metadata.get("parent_id"), metadata.get("ordinal", 1),
                        metadata["title"], metadata.get("prompt", ""), metadata.get("generator", ""), now(), json.dumps(hashes), backup))
            except BaseException:
                for path in (stage, final):
                    if path.exists() and not path.is_symlink():
                        with self.connection() as db:
                            committed = db.execute("SELECT 1 FROM artifacts WHERE id=?", (identity,)).fetchone()
                        if path == final and committed:
                            continue
                        os.replace(path, self.recovery / f"failed-save-{uuid.uuid4().hex}")
                raise

    def row(self, identity: str, kind: str | None = None):
        self.artifact_path(identity)
        with self.connection() as db:
            row = db.execute("SELECT * FROM artifacts WHERE id=?", (identity,)).fetchone()
        if row is None or (kind is not None and row["kind"] != kind):
            raise DrawingError("DRAFT_NOT_FOUND", "Drawing or job not found in saved history.", 404)
        return row

    def load(self, identity: str, kind: str | None = None):
        row = self.row(identity, kind)
        path = self.artifact_path(identity)
        files = {}
        try:
            for name, expected in json.loads(row["hashes"]).items():
                if name not in FILES:
                    raise ValueError("Unexpected manifest path")
                content = read_regular(path / name)
                if sha(content) != expected:
                    raise ValueError("Checksum mismatch")
                files[name] = content
        except (OSError, ValueError, DrawingError) as exc:
            raise DrawingError("ARTIFACT_DAMAGED", "Saved artifact is missing or damaged. Use Repair from history to restore its verified recovery copy.", 409) from exc
        return files

    def repair(self, identity: str):
        row = self.row(identity)
        files = {name: content.encode() for name, content in json.loads(zlib.decompress(row["backup"])).items()}
        if not set(files) <= FILES or {name: sha(content) for name, content in files.items()} != json.loads(row["hashes"]):
            raise DrawingError("RECOVERY_DAMAGED", "Recovery copy is damaged. Restore your database/artifact backup.", 409)
        with self.lock:
            final = self.artifact_path(identity)
            if final.exists():
                os.replace(final, self.recovery / f"before-repair-{identity}-{uuid.uuid4().hex}")
            directory(final)
            for name, content in files.items():
                atomic_write(final / name, content)
        return self.load(identity)

    def history(self, query="", offset=0, limit=20, drawing_id=None):
        where, params = "kind='revision'", []
        if query:
            where += " AND (title LIKE ? ESCAPE '\\' OR prompt LIKE ? ESCAPE '\\')"
            escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            params += [f"%{escaped}%"] * 2
        if drawing_id:
            where += " AND drawing_id=?"; params.append(drawing_id)
        with self.connection() as db:
            total = db.execute(f"SELECT COUNT(*) FROM artifacts WHERE {where}", params).fetchone()[0]
            rows = db.execute(f"SELECT * FROM artifacts WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        items = []
        for row in rows:
            message = None
            try:
                self.load(row["id"], "revision")
            except DrawingError as exc:
                message = exc.message
            items.append(HistoryEntry(revision_id=row["id"], drawing_id=row["drawing_id"], title=row["title"],
                                      revision=row["ordinal"], prompt=row["prompt"], generator=row["generator"], created_at=row["created_at"],
                                      integrity="damaged" if message else "ok", integrity_message=message))
        return HistoryResponse(items=items, total=total, offset=offset, limit=limit, recovery_notices=self.recovery_notices)

    def setting(self, key, default=None):
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key, value):
        with self.connection() as db:
            db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    def record_transfer(self, record):
        with self.connection() as db:
            db.execute("INSERT INTO transfers VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document", (record.id, record.model_dump_json()))

    def record_run(self, run):
        with self.connection() as db:
            db.execute("INSERT INTO runs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document", (run.id, run.model_dump_json()))

    def runs(self, limit=10):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT document FROM runs ORDER BY rowid DESC LIMIT ?", (limit,))]

    def transfers(self, limit=30):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT document FROM transfers ORDER BY rowid DESC LIMIT ?", (limit,))]
