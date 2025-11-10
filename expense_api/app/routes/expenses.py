from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import ValidationError

from ..db import get_db
from ..schemas import ExpenseIn, ExpenseOut


blp = Blueprint(
    "Expenses",
    "expenses",
    url_prefix="/expenses",
    description="Manage expenses and their participant shares",
)


def _to_cents(amount: float) -> int:
    """Convert a float amount to integer cents with safe rounding."""
    # Using round to nearest cent before int to handle floating point representation
    # e.g. 10.10 -> 1010, 10.235 -> 1024
    return int(round(amount * 100))


def _from_cents(cents: int) -> float:
    """Convert integer cents to float dollars."""
    return round(cents / 100.0, 2)


def _compute_equal_shares_cents(total_cents: int, participant_ids: List[int]) -> List[Tuple[int, int]]:
    """Compute equal shares in cents for each participant.

    The remainder is adjusted by adding 1 cent to the last participant to ensure sum equals total.

    Args:
        total_cents: Total amount in cents (>= 1)
        participant_ids: non-empty list of unique member IDs

    Returns:
        List of tuples (member_id, share_cents)
    """
    n = len(participant_ids)
    base = total_cents // n
    remainder = total_cents - base * n
    # Assign base to all, and adjust remainder by adding 1 cent to the last participant
    shares: List[Tuple[int, int]] = [(pid, base) for pid in participant_ids]
    if remainder:
        # Add the remainder to the last participant for determinism
        last_pid = participant_ids[-1]
        shares[-1] = (last_pid, shares[-1][1] + remainder)
    return shares


@blp.route("/")
class ExpensesCollection(MethodView):
    """Collection endpoints for expenses."""

    @blp.response(200, ExpenseOut(many=True))
    @blp.doc(
        summary="List all expenses",
        description=(
            "Returns all expenses ordered by created_at desc, including aggregated participants with their shares."
        ),
    )
    def get(self) -> List[Dict[str, Any]]:
        """List expenses with participants aggregated into a single structure."""
        conn = get_db()
        # We'll retrieve expenses and join participants; then aggregate in Python for clarity.
        # This assumes schema:
        # expenses(id, description, amount_cents, payer_id, created_at)
        # expense_participants(id, expense_id, member_id, share_cents)
        try:
            cur = conn.execute(
                """
                SELECT
                    e.id AS expense_id,
                    e.description,
                    e.amount_cents,
                    e.payer_id,
                    e.created_at,
                    ep.member_id,
                    ep.share_cents
                FROM expenses e
                LEFT JOIN expense_participants ep ON ep.expense_id = e.id
                ORDER BY datetime(e.created_at) DESC, e.id DESC, ep.member_id ASC;
                """
            )
            rows = cur.fetchall() or []
        except sqlite3.Error:
            blp.abort(500, message="Database error while fetching expenses.")

        # Aggregate rows by expense_id
        by_expense: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            eid = r["expense_id"]  # type: ignore[index]
            if eid not in by_expense:
                by_expense[eid] = {
                    "id": eid,
                    "description": r["description"],
                    "amount": _from_cents(r["amount_cents"]),
                    "payer_id": r["payer_id"],
                    "participants": [],
                    "created_at": r["created_at"],
                }
            if r["member_id"] is not None:
                by_expense[eid]["participants"].append(
                    {"member_id": r["member_id"], "share": _from_cents(r["share_cents"])}
                )

        # In case an expense exists with no participants (shouldn't happen), ensure participants is list
        for exp in by_expense.values():
            if not isinstance(exp.get("participants"), list):
                exp["participants"] = []

        # Return list ordered by created_at desc as queried (dict preserves insertion order in Python 3.7+)
        return list(by_expense.values())

    @blp.arguments(ExpenseIn)
    @blp.response(201, ExpenseOut)
    @blp.doc(
        summary="Create an expense",
        description=(
            "Creates a new expense, splitting the total equally among participants (in cents). "
            "Remainder cents, if any, are added to the last participant deterministically."
        ),
        responses={
            400: {"description": "Validation error or bad data"},
            409: {"description": "Foreign key or integrity constraint violation"},
        },
    )
    def post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create an expense with equal participant shares computed in cents."""
        description: str = (payload.get("description") or "").strip()
        amount: float = payload.get("amount")  # type: ignore[assignment]
        payer_id: int = payload.get("payer_id")  # type: ignore[assignment]
        participant_ids: List[int] = payload.get("participant_ids") or []  # type: ignore[assignment]

        if not description:
            raise ValidationError({"description": ["Description is required."]})
        if not isinstance(amount, (int, float)) or amount <= 0:
            raise ValidationError({"amount": ["Amount must be a number greater than 0."]})
        if not isinstance(payer_id, int):
            raise ValidationError({"payer_id": ["Payer ID must be an integer."]})
        if not isinstance(participant_ids, list) or len(participant_ids) == 0:
            raise ValidationError({"participant_ids": ["At least one participant is required."]})
        if len(set(participant_ids)) != len(participant_ids):
            raise ValidationError({"participant_ids": ["Participant IDs must be unique."]})

        total_cents = _to_cents(float(amount))
        if total_cents <= 0:
            raise ValidationError({"amount": ["Amount must be at least 0.01."]})

        shares_cents = _compute_equal_shares_cents(total_cents, participant_ids)

        conn = get_db()
        try:
            with conn:
                # Verify foreign keys exist (payer and participants)
                # The FK constraints should enforce this, but we check proactively to return clearer errors.
                # Check payer
                payer_row = conn.execute("SELECT id FROM members WHERE id = ?", (payer_id,)).fetchone()
                if payer_row is None:
                    blp.abort(409, message="Payer ID does not reference an existing member.")

                # Check all participants exist
                qmarks = ",".join(["?"] * len(participant_ids))
                part_rows = conn.execute(
                    f"SELECT id FROM members WHERE id IN ({qmarks})",
                    tuple(participant_ids),
                ).fetchall()
                if len(part_rows or []) != len(participant_ids):
                    blp.abort(409, message="One or more participant IDs do not reference existing members.")

                # Insert expense
                conn.execute(
                    """
                    INSERT INTO expenses (description, amount_cents, payer_id)
                    VALUES (?, ?, ?)
                    """,
                    (description, total_cents, payer_id),
                )
                new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]  # type: ignore[index]

                # Insert participants shares
                for member_id, share_cents in shares_cents:
                    conn.execute(
                        """
                        INSERT INTO expense_participants (expense_id, member_id, share_cents)
                        VALUES (?, ?, ?)
                        """,
                        (new_id, member_id, share_cents),
                    )

                # Fetch created resource with aggregation
                cur = conn.execute(
                    """
                    SELECT
                        e.id AS expense_id,
                        e.description,
                        e.amount_cents,
                        e.payer_id,
                        e.created_at,
                        ep.member_id,
                        ep.share_cents
                    FROM expenses e
                    LEFT JOIN expense_participants ep ON ep.expense_id = e.id
                    WHERE e.id = ?
                    ORDER BY ep.member_id ASC
                    """,
                    (new_id,),
                )
                rows = cur.fetchall() or []
        except sqlite3.IntegrityError as e:
            # SQLite FK error typically includes 'FOREIGN KEY constraint failed'
            msg = str(e).upper()
            if "FOREIGN KEY" in msg or "UNIQUE" in msg or "NOT NULL" in msg:
                blp.abort(409, message="Constraint violation while creating expense.")
            blp.abort(400, message="Invalid data provided.")
        except sqlite3.Error:
            blp.abort(500, message="Database error while creating expense.")
        except Exception:
            blp.abort(500, message="Unexpected error while creating expense.")

        if not rows:
            blp.abort(500, message="Failed to load created expense.")

        # Build response
        first = rows[0]
        resp = {
            "id": first["expense_id"],
            "description": first["description"],
            "amount": _from_cents(first["amount_cents"]),
            "payer_id": first["payer_id"],
            "participants": [],
            "created_at": first["created_at"],
        }
        for r in rows:
            if r["member_id"] is not None:
                resp["participants"].append(
                    {"member_id": r["member_id"], "share": _from_cents(r["share_cents"])}
                )
        return resp
