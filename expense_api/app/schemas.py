from typing import List
from marshmallow import Schema, fields, validates, validates_schema, ValidationError, validate


# PUBLIC_INTERFACE
class MemberIn(Schema):
    """Schema for creating a member."""
    name = fields.Str(required=True, validate=validate.Length(min=1, max=100), metadata={"description": "Member name (1-100 chars)"})


# PUBLIC_INTERFACE
class MemberOut(Schema):
    """Schema for returning member details."""
    id = fields.Int(required=True)
    name = fields.Str(required=True)
    created_at = fields.Str(required=True)


# PUBLIC_INTERFACE
class ExpenseParticipantOut(Schema):
    """Schema for an expense share for a participant."""
    member_id = fields.Int(required=True)
    share = fields.Float(required=True)


# PUBLIC_INTERFACE
class ExpenseIn(Schema):
    """Schema for creating an expense."""
    description = fields.Str(required=True, validate=validate.Length(min=1, max=255), metadata={"description": "Short description of the expense"})
    amount = fields.Float(required=True, metadata={"description": "Total amount paid (> 0)"})
    payer_id = fields.Int(required=True, metadata={"description": "Member ID who paid"})
    participant_ids = fields.List(fields.Int(), required=True, metadata={"description": "Non-empty list of participant member IDs"})

    @validates("amount")
    def validate_amount(self, value: float) -> None:
        if value is None or not isinstance(value, (int, float)):
            raise ValidationError("Amount must be a number.")
        if value <= 0:
            raise ValidationError("Amount must be greater than 0.")
        # Limit precision to reasonable number to prevent floating-point extremes
        if value > 1e10:
            raise ValidationError("Amount is unrealistically large.")

    @validates("participant_ids")
    def validate_participants(self, value: List[int]) -> None:
        if not isinstance(value, list) or len(value) == 0:
            raise ValidationError("At least one participant is required.")
        if any((pid is None) for pid in value):
            raise ValidationError("Participant IDs must not contain nulls.")
        if len(set(value)) != len(value):
            raise ValidationError("Participant IDs must be unique.")

    @validates("description")
    def validate_desc(self, value: str) -> None:
        if value.strip() == "":
            raise ValidationError("Description cannot be empty or whitespace only.")

    @validates_schema
    def validate_relationships(self, data, **kwargs):
        payer_id = data.get("payer_id")
        participants = data.get("participant_ids") or []
        if payer_id is None:
            raise ValidationError({"payer_id": ["Payer ID is required."]})
        if not isinstance(payer_id, int):
            raise ValidationError({"payer_id": ["Payer ID must be an integer."]})
        if payer_id not in participants:
            # It is acceptable for payer to not be in participants; some systems require it.
            # We'll allow both, but provide a gentle tip if omitted.
            pass


# PUBLIC_INTERFACE
class ExpenseOut(Schema):
    """Schema for returning an expense with computed participants/shares."""
    id = fields.Int(required=True)
    description = fields.Str(required=True)
    amount = fields.Float(required=True)
    payer_id = fields.Int(required=True)
    participants = fields.List(fields.Nested(ExpenseParticipantOut), required=True)
    created_at = fields.Str(required=True)


# PUBLIC_INTERFACE
class BalanceOut(Schema):
    """Schema for returning net balance of a member."""
    member_id = fields.Int(required=True)
    name = fields.Str(required=True)
    net = fields.Float(required=True)


# PUBLIC_INTERFACE
class SettlementOut(Schema):
    """Optional schema describing a settlement transfer from one member to another."""
    from_member_id = fields.Int(required=True)
    to_member_id = fields.Int(required=True)
    amount = fields.Float(required=True)

    @validates("amount")
    def validate_amount(self, value: float) -> None:
        if value is None or value <= 0:
            raise ValidationError("Settlement amount must be greater than 0.")
