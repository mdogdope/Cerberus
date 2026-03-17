from contextlib import contextmanager
from pathlib import Path
import sqlite3, threading

_WRITE_LOCK = threading.Lock()
PROJECT_PATH = Path(__file__).resolve().parent.parent # Double parent to reach project folder
DB_PATH = PROJECT_PATH / "cerberus.db"
SCHEMA_PATH = PROJECT_PATH / "schema.sql"

def _open_ro():
	conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5, check_same_thread=False)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA query_only=ON")
	conn.execute("PRAGMA foreign_keys=ON")
	conn.execute("PRAGMA busy_timeout=5000")
	return conn

def _open_rw():
	conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None, check_same_thread=False)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA synchronous=NORMAL")
	conn.execute("PRAGMA foreign_keys=ON")
	conn.execute("PRAGMA busy_timeout=5000")
	return conn

def query_db(query:str, params):
	conn = _open_ro()
	try:
		cur = conn.execute(query, params)
		rows = cur.fetchall()
		return [dict(row) for row in rows]
	finally:
		conn.close()

def execute_db(query: str, params=()):
	with _WRITE_LOCK:
		conn = _open_rw()
		try:
			conn.execute("BEGIN IMMEDIATE")
			cur = conn.execute(query, params)
			conn.execute("COMMIT")
			return cur.lastrowid
		except Exception:
			conn.execute("ROLLBACK")
			raise
		finally:
			conn.close()

@contextmanager
def wr_tx():
	with _WRITE_LOCK:
		conn = _open_rw()
		try:
			conn.execute("BEGIN IMMEDIATE")
			yield conn
			conn.execute("COMMIT")
		except Exception:
			conn.execute("ROLLBACK")
			raise sqlite3.DatabaseError
		finally:
			conn.close()

def db_exists():
	return DB_PATH.exists()

def create_db():
	conn = sqlite3.connect(DB_PATH)
	
	try:
		conn.execute("PRAGMA journal_mode=WAL")
		conn.execute("PRAGMA foreign_keys=ON")
		conn.execute("PRAGMA busy_timeout=5000")
		conn.execute("PRAGMA synchronous=NORMAL")
		with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
			conn.executescript(f.read())
	finally:
		conn.close()

def ensure_device_name_unique():
	with _WRITE_LOCK:
		conn = _open_rw()
		try:
			conn.execute("BEGIN IMMEDIATE")
			conn.execute("PRAGMA foreign_keys=ON")
			dup_names = conn.execute(
				"""
				SELECT device_name, MIN(device_id) AS keep_id
				FROM devices
				GROUP BY device_name
				HAVING COUNT(*) > 1
				"""
			).fetchall()
			for row in dup_names:
				name = row["device_name"]
				keep_id = row["keep_id"]
				dup_ids = conn.execute(
					"SELECT device_id FROM devices WHERE device_name = ? AND device_id <> ?",
					(name, keep_id),
				).fetchall()
				for dup in dup_ids:
					dup_id = dup["device_id"]
					# Re-point events to the kept device id before deleting duplicates.
					conn.execute("UPDATE events SET device = ? WHERE device = ?", (keep_id, dup_id))
					conn.execute("DELETE FROM devices WHERE device_id = ?", (dup_id,))
			conn.execute(
				"CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_device_name_unique ON devices(device_name)"
			)
			conn.execute("COMMIT")
		except Exception:
			conn.execute("ROLLBACK")
			raise
		finally:
			conn.close()
