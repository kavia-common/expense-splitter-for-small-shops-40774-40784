import os
import sqlite3
from typing import Optional
from flask import g, Flask


# PUBLIC_INTERFACE
def get_db() -> sqlite3.Connection:
    """Return a per-request SQLite connection stored on Flask g.

    The DB path is resolved by:
    - SQLITE_DB environment variable if set
    - Otherwise defaults to '../../expense-splitter-for-small-shops-40774-40785/expense_database/myapp.db'
      relative to this container.

    The connection:
    - Enables foreign key constraints (PRAGMA foreign_keys=ON)
    - Uses row factory to return dict-like rows

    Returns:
        sqlite3.Connection: The active SQLite connection for the current request context.
    """
    if "db_conn" in g:
        return g.db_conn  # type: ignore[attr-defined]

    # Determine database path with safe defaults
    env_path: Optional[str] = os.getenv("SQLITE_DB")
    if env_path and isinstance(env_path, str) and env_path.strip():
        db_path = env_path.strip()
    else:
        # Default path relative to this container directory
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_path = os.path.normpath(
            os.path.join(
                base_dir,
                "..",
                "..",
                "expense-splitter-for-small-shops-40774-40785",
                "expense_database",
                "myapp.db",
            )
        )

    # Ensure directory exists (skip if not, sqlite will create file if parent dir exists)
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        # Avoid attempting to create unexpected dirs; raise a clear error instead.
        raise FileNotFoundError(
            f"Database directory does not exist: {db_dir}. "
            "Please ensure the expense_database container volume is available or set SQLITE_DB."
        )

    # Establish connection with safe defaults
    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        check_same_thread=False,  # allow use within threads managed by the server
        timeout=10.0,
    )

    # Return rows as dictionaries
    conn.row_factory = _dict_factory

    # Enforce foreign key constraints
    with conn:  # ensures the PRAGMA is applied within a transaction context
        conn.execute("PRAGMA foreign_keys = ON;")

    # Store on g for reuse within the same request
    g.db_conn = conn  # type: ignore[attr-defined]
    return conn


def _dict_factory(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    """Convert sqlite3.Row to a dict for consistent JSON serialization."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _close_db_conn(_: Optional[BaseException] = None) -> None:
    """Close the DB connection if it exists on g."""
    conn: Optional[sqlite3.Connection] = getattr(g, "db_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            # Avoid logging sensitive paths or details; swallow to not mask original teardown errors
            pass
        finally:
            try:
                del g.db_conn  # type: ignore[attr-defined]
            except Exception:
                pass


# PUBLIC_INTERFACE
def init_app(app: Flask) -> None:
    """Register DB teardown handler to close per-request connection.

    Call this during app initialization:
        from .db import init_app
        init_app(app)
    """
    app.teardown_appcontext(_close_db_conn)
