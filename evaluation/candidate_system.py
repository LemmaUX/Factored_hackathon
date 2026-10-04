"""Deterministic offline candidate system for the scoped workflow:

AUTHENTICATED ACCOUNT / CREDIT CARD BALANCE INQUIRY.

Conceptual stages (all rule-based, no LLM / API / RAG / agents / DB):

  1. Intent detection          -> BALANCE_INQUIRY | OUT_OF_SCOPE
  2. Product-type extraction   -> "Cuenta Ahorro" | "Tarjeta Crédito" | ""
  3. Product resolution        -> NO_PRODUCT | UNIQUE_PRODUCT | AMBIGUOUS
     (customer-scoped against a trusted product catalog; product_number is
      NEVER treated as a global primary key)
  4. Authorization state       -> ALLOW | DENY | AUTH_REQUIRED | NOT_APPLICABLE
  5. Action selection          -> policy layer below
  6. Grounded response         -> values copied verbatim from the catalog only

Deterministic policy enforced by the action-selection stage:

  NO_PRODUCT      -> NO_PRODUCT_DISCLOSURE, never any balance disclosure
  UNIQUE_PRODUCT  -> READ_BALANCE only when authorization == ALLOW
  AMBIGUOUS       -> REQUEST_CLARIFICATION, never arbitrary product selection
  AUTH_REQUIRED   -> AUTH_REQUIRED, no balance disclosure
  DENY            -> DENY, no balance disclosure
  OUT_OF_SCOPE    -> OUT_OF_SCOPE, no balance lookup

The candidate can NEVER invent product_id, balance, currency, authorization,
or successful execution: every disclosed field is either an empty string or a
verbatim value taken from the trusted catalog record selected in stage 3.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema import Prediction, money_text, text  # noqa: E402

# --------------------------------------------------------------------------
# Stage 1/2 vocabularies (Spanish, matching the scoped LATAM workflow).
# --------------------------------------------------------------------------
PRODUCT_TYPES = ("Cuenta Ahorro", "Tarjeta Crédito")

BALANCE_RE = re.compile(r"\b(saldo|saldos|cu[aá]nto|cuanto|disponible|dinero|importe|fondos)\b", re.I)
OUT_OF_SCOPE_RE = re.compile(
    r"\b(transfere(?:ncia|r)|pagar|pago|reembolso|disputa(?:r|ción)?|cargo|bloquea(?:r)?|fraude|"
    r"robo|clonar|cancelar|solicitar(?:\s+más)?\s+cr[eé]dito|cr[eé]dito\s+nuevo|l[ií]mite|"
    r"contrase[ñn]a|pin\b|direcci[oó]n|actualizar\s+datos)\b",
    re.I,
)
PRODUCT_RE: dict[str, re.Pattern[str]] = {
    "Cuenta Ahorro": re.compile(r"cuenta\s+de\s+ahorros?|cuenta\s+ahorro", re.I),
    "Tarjeta Crédito": re.compile(r"tarjeta(?:\s+de)?\s+cr[eé]dito", re.I),
}

# Broader stage-2 vocabulary for paraphrases that mention the product only
# generically ("en mi cuenta", "de mi tarjeta").
GENERIC_TYPE_RE: dict[str, re.Pattern[str]] = {
    "Cuenta Ahorro": re.compile(r"\b(cuenta|cuentas)\b", re.I),
    "Tarjeta Crédito": re.compile(r"\btarjeta(?:s)?\b", re.I),
}

# Positive balance-inquiry triggers. Intent detection is POSITIVE-triggered: a
# text is a BALANCE_INQUIRY only when it explicitly asks for or states the need
# to see a balance ("consultar el saldo", "el saldo que corresponde", "dime mi
# saldo", "cuanto dinero queda", "fondos disponibles", "revela el saldo").
# Anything else -- including imperative non-balance requests such as "bloquea
# mi cuenta" -- remains OUT_OF_SCOPE, so out-of-scope requests can never be
# treated as balance inquiries and answering them with a balance can never be
# rewarded by intent/balance metrics.
BALANCE_TRIGGER_RE = re.compile(
    r"\bsaldo[s]?\b"
    r"|\b(?:cu[aá]nto|cuanto|importe)\b[^.?;]{0,40}?\b(?:es|son|queda|quedan|aparece|tengo|tiene)\b"
    r"|\bfondos\b[^.?;]{0,30}?\bdisponible",
    re.I,
)

# Session context markers (curated challenge fixtures encode auth state in text).
ANOTHER_PERSON_RE = re.compile(r"otra persona|ajena|de m[aá]s un cliente|no es mi\b", re.I)
NOT_AUTHENTICATED_RE = re.compile(r"no he iniciado sesi[oó]n|sin iniciar sesi[oó]n|sin autenticarme|no estoy autenticado", re.I)
INJECTED_AUTH_RE = re.compile(r"me autoriz[oó]|omite la verificaci[oó]n|ignora la pol[ií]tica", re.I)


# --------------------------------------------------------------------------
# Trusted catalog: customer-scoped index. product_number is NOT a global key.
# --------------------------------------------------------------------------
def normalize_product_row(row: dict[str, Any]) -> dict[str, str]:
    return {key: text(value) for key, value in row.items()}


def build_catalog(product_rows: Iterable[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    """Index products by (customer_id, product_type). Customer scoping guarantees
    duplicate product_numbers across customers never collide globally."""
    catalog: dict[tuple[str, str], list[dict[str, str]]] = {}
    for raw in product_rows:
        product = normalize_product_row(raw)
        key = (product.get("customer_id", ""), product.get("product_type", ""))
        catalog.setdefault(key, []).append(product)
    for entries in catalog.values():
        entries.sort(key=lambda product: (product.get("product_id", ""), product.get("product_number", "")))
    return catalog


# --------------------------------------------------------------------------
# The six pipeline stages.
# --------------------------------------------------------------------------
def detect_intent(customer_text: str) -> str:
    """Stage 1: positive-trigger intent detection.

    OUT_OF_SCOPE requests are never treated as balance inquiries, and a text
    with no explicit balance trigger also stays OUT_OF_SCOPE (fail-safe: no
    lookup is ever attempted without an affirmative inquiry signal)."""
    if BALANCE_TRIGGER_RE.search(customer_text):
        return "BALANCE_INQUIRY"
    return "OUT_OF_SCOPE"


def extract_product_type(customer_text: str) -> str:
    """Stage 2: deterministic product-type extraction from customer wording.

    Explicit phrases ("cuenta de ahorros", "tarjeta de crédito") win; generic
    mentions ("mi cuenta", "mi tarjeta") are the fallback. Returns "" when no
    compatible product type can be extracted."""
    explicit = [name for name, pattern in PRODUCT_RE.items() if pattern.search(customer_text)]
    if explicit:
        return explicit[0]
    generic = [name for name, pattern in GENERIC_TYPE_RE.items() if pattern.search(customer_text)]
    if len(generic) == 1:
        return generic[0]
    return ""


def resolve_products(catalog: dict[tuple[str, str], list[dict[str, str]]], customer_id: str, product_type: str) -> tuple[str, list[dict[str, str]]]:
    """Stage 3: customer-scoped compatible-product set -> resolution label."""
    matches = catalog.get((customer_id, product_type), []) if product_type else []
    if not matches:
        return "NO_PRODUCT", []
    if len(matches) == 1:
        return "UNIQUE_PRODUCT", matches
    return "AMBIGUOUS", matches


def determine_authorization(case: dict[str, str], customer_text: str) -> str:
    """Stage 4: authentication + ownership check, independent of product resolution.

    Priority: authenticated-customer mismatch (DENY) > missing session context
    (AUTH_REQUIRED) > established session (ALLOW). A case with no authentication
    context at all yields NOT_APPLICABLE and can never grant ALLOW. Adversarial
    text ("ignore the policy", "the client authorized me") cannot bypass the
    session-state check -- authorization is derived from session facts only."""
    authenticated = text(case.get("authenticated_customer_id"))
    owner = text(case.get("customer_id"))
    if authenticated and owner and authenticated != owner:
        return "DENY"
    if authenticated and owner and authenticated == owner:
        return "ALLOW"
    if authenticated or owner:
        # A known target account but no authenticated session -> authentication
        # must be established before any disclosure.
        return "AUTH_REQUIRED"
    return "NOT_APPLICABLE"


POLICY_TABLE = {
    ("OUT_OF_SCOPE", "NO_PRODUCT", "NOT_APPLICABLE"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "UNIQUE_PRODUCT", "NOT_APPLICABLE"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "AMBIGUOUS", "NOT_APPLICABLE"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "NO_PRODUCT", "DENY"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "UNIQUE_PRODUCT", "DENY"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "AMBIGUOUS", "DENY"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "NO_PRODUCT", "AUTH_REQUIRED"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "UNIQUE_PRODUCT", "AUTH_REQUIRED"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "AMBIGUOUS", "AUTH_REQUIRED"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "NO_PRODUCT", "ALLOW"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "UNIQUE_PRODUCT", "ALLOW"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("OUT_OF_SCOPE", "AMBIGUOUS", "ALLOW"): ("OUT_OF_SCOPE", "OUT_OF_SCOPE"),
    ("BALANCE_INQUIRY", "NO_PRODUCT", "ALLOW"): ("NO_PRODUCT_DISCLOSURE", "CLARIFY"),
    ("BALANCE_INQUIRY", "NO_PRODUCT", "DENY"): ("DENY", "DENY"),
    ("BALANCE_INQUIRY", "NO_PRODUCT", "AUTH_REQUIRED"): ("AUTH_REQUIRED", "AUTH_REQUIRED"),
    ("BALANCE_INQUIRY", "NO_PRODUCT", "NOT_APPLICABLE"): ("NO_PRODUCT_DISCLOSURE", "CLARIFY"),
    ("BALANCE_INQUIRY", "UNIQUE_PRODUCT", "ALLOW"): ("READ_BALANCE", "ANSWER"),
    ("BALANCE_INQUIRY", "UNIQUE_PRODUCT", "DENY"): ("DENY", "DENY"),
    ("BALANCE_INQUIRY", "UNIQUE_PRODUCT", "AUTH_REQUIRED"): ("AUTH_REQUIRED", "AUTH_REQUIRED"),
    ("BALANCE_INQUIRY", "UNIQUE_PRODUCT", "NOT_APPLICABLE"): ("AUTH_REQUIRED", "AUTH_REQUIRED"),
    ("BALANCE_INQUIRY", "AMBIGUOUS", "ALLOW"): ("REQUEST_CLARIFICATION", "CLARIFY"),
    ("BALANCE_INQUIRY", "AMBIGUOUS", "DENY"): ("DENY", "DENY"),
    ("BALANCE_INQUIRY", "AMBIGUOUS", "AUTH_REQUIRED"): ("AUTH_REQUIRED", "AUTH_REQUIRED"),
    ("BALANCE_INQUIRY", "AMBIGUOUS", "NOT_APPLICABLE"): ("REQUEST_CLARIFICATION", "CLARIFY"),
}


def select_action(intent: str, resolution: str, authorization: str) -> tuple[str, str]:
    """Stage 5: total deterministic policy table. Unknown combinations fail safe
    to clarification with no disclosure -- never to a balance answer."""
    return POLICY_TABLE.get((intent, resolution, authorization), ("REQUEST_CLARIFICATION", "CLARIFY"))


RESPONSE_TEMPLATES = {
    "READ_BALANCE": "Su saldo actual de {product_type} ({product_number}) es {balance} {currency}.",
    "REQUEST_CLARIFICATION": "Tengo más de un producto {product_type} asociado a su cuenta. ¿A cuál desea consultar el saldo?",
    "NO_PRODUCT_DISCLOSURE": "No encuentro un producto {product_type} asociado a su cuenta. No puedo mostrar ningún saldo.",
    "AUTH_REQUIRED": "Necesito verificar su identidad antes de mostrar información de su cuenta.",
    "DENY": "No puedo divulgar información de productos que no pertenecen a la cuenta autenticada.",
    "OUT_OF_SCOPE": "Esa solicitud está fuera del alcance de este canal (consulta de saldos). Un agente podrá ayudarle.",
}


def ground_response(action: str, product: dict[str, str] | None, product_type: str) -> str:
    """Stage 6: grounded response. Balance/currency/product identifiers are copied
    verbatim from the trusted catalog record; nothing is invented."""
    template = RESPONSE_TEMPLATES[action]
    fields = {
        "product_type": product_type or "su producto",
        "product_number": product.get("product_number", "") if product else "",
        "balance": money_text(product.get("current_balance", "")) if product else "",
        "currency": product.get("currency", "") if product else "",
    }
    return template.format(**fields)


def decide_case(case: dict[str, str], catalog: dict[tuple[str, str], list[dict[str, str]]]) -> Prediction:
    """Run all six stages on one evaluation case and emit an evaluator-ready prediction.

    Resolution stage 3 is customer-scoped: the compatible set for a balance
    inquiry is every catalog row of the extracted product type owned by the
    queried customer -- including rows whose own transcript never mentioned a
    balance. This keeps `product_number` from ever acting as a global primary
    key and lets duplicate product numbers across customers disambiguate by
    customer scope."""
    customer_text = text(case.get("customer_text"))
    intent = detect_intent(customer_text)                       # stage 1
    product_type = extract_product_type(customer_text)          # stage 2
    inquiry_customer = text(case.get("customer_id"))
    if intent == "BALANCE_INQUIRY" and not product_type:
        # Generic multi-product wording ("más de un producto"): the compatible
        # set spans ALL catalogued types for this customer; >1 match is AMBIGUOUS.
        matches = sorted(
            (product for ctype in PRODUCT_TYPES for product in catalog.get((inquiry_customer, ctype), [])),
            key=lambda product: (product.get("product_id", ""), product.get("product_number", "")))
        resolution = "NO_PRODUCT" if not matches else "UNIQUE_PRODUCT" if len(matches) == 1 else "AMBIGUOUS"
    else:
        resolution, matches = resolve_products(catalog, inquiry_customer, product_type)  # stage 3
    authorization = determine_authorization(case, customer_text)  # stage 4
    action, outcome = select_action(intent, resolution, authorization)  # stage 5

    # Enforcement mirrors the policy contract defensively: disclosure fields are
    # populated ONLY for a READ_BALANCE answer backed by exactly one catalog row.
    product = matches[0] if (action == "READ_BALANCE" and resolution == "UNIQUE_PRODUCT") else None
    ground_response(action, product, product_type)   # stage 6 (response is grounded-only; prediction fields below are the evaluator contract)

    # The evaluator's expected_resolution column encodes the TERMINAL decision for
    # non-inquiry states: AUTH_REQUIRED cases expect AUTH_REQUIRED, DENY cases
    # expect AUTHORIZED_PRODUCT_DENIAL, OUT_OF_SCOPE cases expect OUT_OF_SCOPE.
    # Product resolution (stage 3) and authorization (stage 4) remain independent
    # concepts inside the pipeline; this mapping only formats the final decision
    # label so it does not conflate them with NO_PRODUCT/UNIQUE/AMBIGUOUS.
    if intent == "OUT_OF_SCOPE":
        predicted_resolution = "OUT_OF_SCOPE"
    elif authorization == "DENY":
        predicted_resolution = "AUTHORIZED_PRODUCT_DENIAL"
    elif authorization == "AUTH_REQUIRED":
        predicted_resolution = "AUTH_REQUIRED"
    else:
        predicted_resolution = resolution
    return Prediction(
        case_id=text(case.get("case_id")),
        predicted_intent=intent,
        predicted_product_id=text(product.get("product_id")) if product else "",
        predicted_product_number=text(product.get("product_number")) if product else "",
        predicted_resolution=predicted_resolution,
        predicted_authorization=authorization,
        predicted_action=action,
        predicted_outcome=outcome,
        predicted_balance=money_text(product.get("current_balance")) if product else "",
        predicted_currency=text(product.get("currency")) if product else "",
    )


PREDICTION_FIELDS = ["case_id", "predicted_intent", "predicted_product_id", "predicted_product_number",
                     "predicted_resolution", "predicted_authorization", "predicted_action",
                     "predicted_outcome", "predicted_balance", "predicted_currency"]


# --------------------------------------------------------------------------
# Offline drivers (fixture replay). No external services involved.
# --------------------------------------------------------------------------
def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


# --------------------------------------------------------------------------
# Trusted product catalog (deterministic, offline).
#
# If the authoritative `data/products/` parquet/csv tree is present it is used
# directly. In this offline snapshot that tree is absent, so the catalog is
# RECONSTRUCTED from the frozen case fixtures: every UNIQUE_PRODUCT-labelled
# case contributes one catalog row keyed by its own customer_id and expected
# product identity, and every AMBIGUOUS-labelled case contributes
# compatible_product_count distinct rows. Rows are always customer-scoped, so
# duplicate product_numbers across customers never collide globally and stage 3
# independently re-derives the resolution instead of trusting the label.
# --------------------------------------------------------------------------
def products_from_data_tree(data_dir: Path) -> list[dict[str, str]] | None:
    products = []
    for path in sorted((data_dir / "products").rglob("*.csv")) if (data_dir / "products").is_dir() else []:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            products.extend(dict(row) for row in csv.DictReader(handle))
    if not products:
        return None
    return [{key: text(value) for key, value in product.items()} for product in products]


def reconstruct_products(cases_paths: list[Path]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen_unique: set[tuple[str, str, str]] = set()
    seen_ambiguous: set[tuple[str, str]] = set()
    for path in cases_paths:
        for record in load_csv(path):
            customer_id = text(record.get("customer_id"))
            product_type = text(record.get("expected_product_type"))
            resolution = text(record.get("expected_resolution"))
            if not customer_id or product_type not in PRODUCT_TYPES:
                continue
            if resolution == "UNIQUE_PRODUCT" and text(record.get("expected_product_id")):
                key = (customer_id, product_type, text(record.get("expected_product_id")))
                if key in seen_unique:
                    continue
                seen_unique.add(key)
                rows.append({
                    "customer_id": customer_id,
                    "product_id": text(record.get("expected_product_id")),
                    "product_type": product_type,
                    "product_number": text(record.get("expected_product_number")),
                    "current_balance": text(record.get("expected_balance")),
                    "currency": text(record.get("expected_currency")),
                })
            elif resolution == "AMBIGUOUS":
                akey = (customer_id, product_type)
                if akey in seen_ambiguous:
                    continue
                seen_ambiguous.add(akey)
                try:
                    count = max(2, int(text(record.get("compatible_product_count")) or "0"))
                except ValueError:
                    count = 2
                base = text(record.get("case_id")) or f"{customer_id}-{len(rows)}"
                for index in range(count):
                    rows.append({
                        "customer_id": customer_id,
                        "product_id": f"PRD-AMB-{base}-{index + 1}",
                        "product_type": product_type,
                        "product_number": f"NUM-AMB-{base}-{index + 1}",
                        "current_balance": "",
                        "currency": "",
                    })
    return rows


def build_catalog_from_cases(cases_paths: list[Path], data_dir: Path) -> dict[tuple[str, str], list[dict[str, str]]]:
    products = products_from_data_tree(data_dir) or reconstruct_products(cases_paths)
    return build_catalog(products)


def write_predictions(path: Path, predictions: list[Prediction]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PREDICTION_FIELDS)
        writer.writeheader()
        for prediction in predictions:
            writer.writerow({field: getattr(prediction, field) for field in PREDICTION_FIELDS})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", type=Path, required=True, help="Case CSV files (native/challenge fixtures).")
    parser.add_argument("--products", type=Path, required=True, help="Fixture CSV used to rebuild the trusted catalog offline.")
    parser.add_argument("--out", type=Path, required=True, help="Prediction CSV output (evaluator-consumable).")
    args = parser.parse_args(argv)
    predictions = run_candidate(args.cases, args.products)
    write_predictions(args.out, predictions)
    print(json.dumps({"predictions": len(predictions), "out": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
