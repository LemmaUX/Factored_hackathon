"""Shared schema and normalization helpers for Evaluation Harness v0.1."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

NATIVE_FIELDS = [
    "case_id", "source_type", "transcript_id", "interaction_id", "customer_id",
    "customer_text", "process_date", "expected_intent", "expected_product_type",
    "compatible_product_count", "expected_resolution", "expected_product_id",
    "expected_product_number", "expected_balance", "expected_currency", "expected_action",
    "expected_outcome", "risk_class", "historical_was_resolved", "historical_was_escalated",
]

CHALLENGE_FIELDS = NATIVE_FIELDS + ["category", "authenticated_customer_id", "expected_authorization"]


@dataclass(frozen=True)
class Prediction:
    case_id: str
    predicted_intent: str = ""
    predicted_product_id: str = ""
    predicted_product_number: str = ""
    predicted_resolution: str = ""
    predicted_authorization: str = ""
    predicted_action: str = ""
    predicted_outcome: str = ""
    predicted_balance: str = ""
    predicted_currency: str = ""


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def lower(value: Any) -> str:
    return text(value).lower()


def is_truthy(value: Any) -> bool:
    return lower(value) in {"1", "true", "yes", "y"}


def money(value: Any) -> Decimal | None:
    value = text(value)
    if not value:
        return None
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def money_text(value: Any) -> str:
    parsed = money(value)
    return "" if parsed is None else format(parsed, "f")


def prediction_from_row(row: dict[str, Any]) -> Prediction:
    return Prediction(
        case_id=text(row.get("case_id")),
        predicted_intent=text(row.get("predicted_intent")),
        predicted_product_id=text(row.get("predicted_product_id")),
        predicted_product_number=text(row.get("predicted_product_number")),
        predicted_resolution=text(row.get("predicted_resolution")),
        predicted_authorization=text(row.get("predicted_authorization")),
        predicted_action=text(row.get("predicted_action")),
        predicted_outcome=text(row.get("predicted_outcome")),
        predicted_balance=text(row.get("predicted_balance")),
        predicted_currency=text(row.get("predicted_currency")),
    )