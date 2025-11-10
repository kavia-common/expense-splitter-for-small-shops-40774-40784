from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Tuple

from flask.views import MethodView
from flask_smorest import Blueprint

from ..db import get_db
from ..schemas import BalanceOut, SettlementOut


blp = Blueprint(
    "Balances",
    "balances",
    url_prefix="/balances",
    description="View per-member net balances and suggested settlements",
)


def _from_cents(cents: int) -> float:
    """Convert integer cents to float dollars rounded to 2 decimals."""
    return round(cents / 100.0, 2)


def _compute_settlements(balances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compute suggested settlements using a greedy algorithm.

    Input balances are dicts containing:
      - member_id: int
      - name: str
      - net: float (positive => should receive, negative => should pay)

    Returns a list of transfers:
      {from_member_id, to_member_id, amount} with amount > 0
    """
    # Separate creditors and debtors
    debtors: List[Tuple[int, float]] = []   # (member_id, amount_to_pay_positive)
    creditors: List[Tuple[int, float]] = []  # (member_id, amount_to_receive_positive)

    for b in balances:
        net = float(b.get("net") or 0.0)
        mid = int(b["member_id"])
        if net < -1e-9:
            debtors.append((mid, round(-net, 2)))
        elif net > 1e-9:
            creditors.append((mid, round(net, 2)))

    # Sort to have deterministic behavior: largest amounts first
    debtors.sort(key=lambda x: x[1], reverse=True)
    creditors.sort(key=lambda x: x[1], reverse=True)

    settlements: List[Dict[str, Any]] = []
    i, j = 0, 0
    while i < len(debtors) and j < len(creditors):
        debtor_id, d_amt = debtors[i]
        creditor_id, c_amt = creditors[j]

        # Pay the minimum of the two
        pay = min(d_amt, c_amt)
        pay = round(pay, 2)

        if pay > 0:
            settlements.append(
                {"from_member_id": debtor_id, "to_member_id": creditor_id, "amount": pay}
            )

        # Update remaining amounts
        d_amt = round(d_amt - pay, 2)
        c_amt = round(c_amt - pay, 2)

        if d_amt <= 1e-9:
            i += 1
        else:
            debtors[i] = (debtor_id, d_amt)

        if c_amt <= 1e-9:
            j += 1
        else:
            creditors[j] = (creditor_id, c_amt)

    return settlements


@blp.route("/")
class BalancesCollection(MethodView):
    """Provide per-member balances and suggested settlements.

    The balances are read from a database view 'balances_view' which should return:
      - member_id INTEGER
      - name TEXT
      - net_cents INTEGER (positive means member is owed money; negative means member owes)
    """

    @blp.response(200, BalanceOut(many=True))
    @blp.doc(
        summary="List per-member net balances",
        description=(
            "Reads balances from balances_view and returns net amounts as floats (dollars). "
            "Positive net => member should receive, negative net => member should pay."
        ),
        responses={500: {"description": "Database error"}},
    )
    def get(self) -> List[Dict[str, Any]]:
        """Return list of {member_id, name, net} with net in dollars."""
        conn = get_db()
        try:
            # Ensure foreign keys are on (done in get_db), but leaving here for clarity; no-op if already set.
            conn.execute("PRAGMA foreign_keys = ON;")

            cur = conn.execute(
                """
                SELECT member_id, name, net_cents
                FROM balances_view
                ORDER BY name COLLATE NOCASE ASC, member_id ASC;
                """
            )
            rows = cur.fetchall() or []
        except sqlite3.Error:
            blp.abort(500, message="Database error while fetching balances.")

        result: List[Dict[str, Any]] = []
        for r in rows:
            try:
                member_id = int(r["member_id"])  # type: ignore[index]
                name = str(r["name"])
                net_cents = int(r["net_cents"])
            except Exception:
                # Validation/safety: malformed view row
                blp.abort(500, message="Malformed data in balances_view.")
                return []  # for type checker

            result.append({"member_id": member_id, "name": name, "net": _from_cents(net_cents)})

        return result


@blp.route("/settlements")
class SettlementsCollection(MethodView):
    """Suggest settlement transfers between members based on current balances."""

    @blp.response(200, SettlementOut(many=True))
    @blp.doc(
        summary="Compute suggested settlements",
        description=(
            "Greedy algorithm between debtors (net < 0) and creditors (net > 0) computed from balances_view. "
            "Produces a minimal set of transfers to settle balances."
        ),
        responses={500: {"description": "Database error"}},
    )
    def get(self) -> List[Dict[str, Any]]:
        """Return suggested settlements as a list of transfers."""
        conn = get_db()
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            cur = conn.execute(
                """
                SELECT member_id, name, net_cents
                FROM balances_view
                ORDER BY member_id ASC;
                """
            )
            rows = cur.fetchall() or []
        except sqlite3.Error:
            blp.abort(500, message="Database error while computing settlements.")

        balances: List[Dict[str, Any]] = []
        for r in rows:
            try:
                member_id = int(r["member_id"])  # type: ignore[index]
                net_cents = int(r["net_cents"])
            except Exception:
                blp.abort(500, message="Malformed data in balances_view.")
                return []
            balances.append({"member_id": member_id, "net": _from_cents(net_cents), "name": r.get("name")})

        return _compute_settlements(balances)
