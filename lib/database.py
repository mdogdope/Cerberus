from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3, stat, threading

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
	_ensure_db_writable()
	conn = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None, check_same_thread=False)
	conn.row_factory = sqlite3.Row
	conn.execute("PRAGMA synchronous=NORMAL")
	conn.execute("PRAGMA foreign_keys=ON")
	conn.execute("PRAGMA busy_timeout=5000")
	return conn

def _ensure_db_writable():
	if DB_PATH.exists():
		mode = DB_PATH.stat().st_mode
		if not mode & stat.S_IWRITE:
			os.chmod(DB_PATH, mode | stat.S_IWRITE)

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
		tx_started = False
		try:
			conn.execute("BEGIN IMMEDIATE")
			tx_started = True
			cur = conn.execute(query, params)
			conn.execute("COMMIT")
			return cur.lastrowid
		except Exception:
			if tx_started:
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
		except Exception as err:
			try:
				conn.execute("ROLLBACK")
			except sqlite3.OperationalError:
				pass
			raise sqlite3.DatabaseError from err
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
