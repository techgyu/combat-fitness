"""SQLite persistence. Seed once; never overwrite web entries on restart."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
if __package__:
    from .module1_core import DomainError, validator
else:
    from module1_core import DomainError, validator


class SoldierStore:
    def __init__(self, db_path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS soldiers (
                    soldier_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL CHECK(source IN ('synthetic','web')),
                    age INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_soldiers_source ON soldiers(source);
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                    request_id TEXT PRIMARY KEY, soldier_id TEXT NOT NULL,
                    status TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed_once(self, seed_path):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT value FROM metadata WHERE key='seed_sha256'").fetchone():
                return 0
            raw, digest = validator.load_records(Path(seed_path))
            report = validator.validate_and_compute(raw)
            if report["status"] != "passed":
                raise DomainError("invalid_seed", "합성 데이터를 2분 측정 조건으로 다시 생성하세요.", report["errors"][:10])
            stamp = datetime.now(timezone.utc).isoformat()
            db.executemany("INSERT INTO soldiers VALUES (?,?,?,?,?)", [
                (r["soldier_id"], "synthetic", r["age"], json.dumps(r, ensure_ascii=False), stamp)
                for r in report["records"]])
            db.execute("INSERT INTO metadata VALUES ('seed_sha256',?)", (digest,))
            return len(report["records"])

    def add(self, row):
        try:
            with self.connect() as db:
                db.execute("INSERT INTO soldiers VALUES (?,?,?,?,?)", (
                    row["soldier_id"], "web", row["age"], json.dumps(row, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError as exc:
            raise DomainError("duplicate_id", "이미 존재하는 장병 ID입니다.") from exc
        return self.get(row["soldier_id"])

    @staticmethod
    def unpack(row):
        return {**json.loads(row["record_json"]), "source": row["source"], "created_at": row["created_at"]}

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM soldiers WHERE soldier_id=?", (identifier,)).fetchone()
        if row is None:
            raise DomainError("not_found", "해당 장병을 찾을 수 없습니다.")
        return self.unpack(row)

    def list(self, page=1, page_size=20, query="", source=""):
        clauses, args = [], []
        if query:
            clauses.append("instr(soldier_id, ?) > 0")
            args.append(query)
        if source:
            clauses.append("source=?")
            args.append(source)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM soldiers" + where, args).fetchone()[0]
            rows = db.execute("SELECT * FROM soldiers" + where +
                              " ORDER BY created_at DESC, soldier_id LIMIT ? OFFSET ?",
                              [*args, page_size, (page - 1) * page_size]).fetchall()
            counts = dict(db.execute("SELECT source,COUNT(*) FROM soldiers GROUP BY source").fetchall())
        return {"items": [self.unpack(r) for r in rows], "total": total,
                "page": page, "page_size": page_size, "source_counts": counts}

    def log_delivery(self, request_id, identifier, status, result):
        with self.connect() as db:
            db.execute("INSERT INTO deliveries VALUES (?,?,?,?,?)", (
                request_id, identifier, status, json.dumps(result, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat()))

    def latest_plan(self, identifier):
        with self.connect() as db:
            rows = db.execute("SELECT result_json FROM deliveries WHERE soldier_id=? AND status='accepted' ORDER BY created_at DESC LIMIT 1",
                              (identifier,)).fetchall()
        response = json.loads(rows[0]["result_json"]) if rows else None
        return response if response and response.get("result") else None
