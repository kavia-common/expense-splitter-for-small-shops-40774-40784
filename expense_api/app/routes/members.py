from flask_smorest import Blueprint
from flask.views import MethodView
from marshmallow import ValidationError
import sqlite3
from typing import Any, Dict, List

from ..db import get_db
from ..schemas import MemberIn, MemberOut

blp = Blueprint(
    "Members",
    "members",
    url_prefix="/members",
    description="Manage members participating in expense splitting",
)


@blp.route("/")
class MembersCollection(MethodView):
    """Collection endpoints for members."""

    @blp.response(200, MemberOut(many=True))
    @blp.doc(summary="List all members", description="Returns all members ordered by created_at desc.")
    def get(self) -> List[Dict[str, Any]]:
        """List members ordered by created_at descending."""
        conn = get_db()
        cur = conn.execute(
            """
            SELECT id, name, created_at
            FROM members
            ORDER BY datetime(created_at) DESC, id DESC;
            """
        )
        rows = cur.fetchall() or []
        # Rows already dict-like from row_factory in get_db
        return rows

    @blp.arguments(MemberIn)
    @blp.response(201, MemberOut)
    @blp.doc(
        summary="Create a member",
        description="Creates a new member with a unique name. Returns the created member.",
        responses={409: {"description": "Member with the same name already exists"}},
    )
    def post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create a member with unique name."""
        name: str = payload.get("name", "").strip()
        if not name:
            # This is normally caught by schema; double-check to be safe.
            raise ValidationError({"name": ["Name is required."]})

        conn = get_db()
        try:
            with conn:
                # Enforce uniqueness at DB level if a UNIQUE constraint exists,
                # otherwise check manually to provide a consistent 409 response.
                cur = conn.execute("SELECT id FROM members WHERE LOWER(name) = LOWER(?)", (name,))
                if cur.fetchone() is not None:
                    blp.abort(409, message="A member with this name already exists.")

                conn.execute("INSERT INTO members (name) VALUES (?)", (name,))
                new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]  # type: ignore[index]

                created = conn.execute(
                    "SELECT id, name, created_at FROM members WHERE id = ?",
                    (new_id,),
                ).fetchone()
        except sqlite3.IntegrityError as e:
            # Covers UNIQUE(name) violations if present at DB level
            if "UNIQUE" in str(e).upper() or "unique" in str(e):
                blp.abort(409, message="A member with this name already exists.")
            # Unknown integrity error
            blp.abort(400, message="Invalid data.")
        except Exception:
            blp.abort(500, message="Failed to create member.")
        if not created:
            blp.abort(500, message="Member creation failed.")
        return created  # dict-like row
        

@blp.route("/<int:member_id>")
class MemberResource(MethodView):
    """Single member resource."""

    @blp.response(204)
    @blp.doc(
        summary="Delete a member",
        description="Deletes a member by ID. If the member has related records via foreign keys, returns 409.",
        responses={
            404: {"description": "Member not found"},
            409: {"description": "Cannot delete member due to existing references"},
        },
    )
    def delete(self, member_id: int):
        """Delete a member by ID with FK-safe handling."""
        conn = get_db()
        try:
            with conn:
                # Check existence
                row = conn.execute("SELECT id FROM members WHERE id = ?", (member_id,)).fetchone()
                if row is None:
                    blp.abort(404, message="Member not found.")
                try:
                    conn.execute("DELETE FROM members WHERE id = ?", (member_id,))
                except sqlite3.IntegrityError as e:
                    # Foreign key restriction error
                    # For SQLite, message often contains 'FOREIGN KEY constraint failed'
                    if "FOREIGN KEY" in str(e).upper():
                        blp.abort(
                            409,
                            message="Cannot delete member because it is referenced by other records.",
                            errors={"member_id": [f"{member_id} has related records."]},
                        )
                    # Other integrity issues
                    blp.abort(400, message="Integrity error while deleting member.")
        except sqlite3.Error:
            blp.abort(500, message="Database error while deleting member.")
        except Exception:
            blp.abort(500, message="Unexpected error while deleting member.")
        # 204 No Content
        return "", 204
