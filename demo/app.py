"""Small standard-library web adapter for the deterministic candidate system."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from evaluation.candidate_system import (
    CATALOG_SOURCE_EXPLICIT,
    CatalogError,
    build_catalog,
    decide_case,
    extract_product_type,
    ground_response,
    load_product_file,
)

ROOT = Path(__file__).resolve().parent.parent
PRODUCTS_PATH = ROOT / "data" / "products.csv"
TEMPLATES_PATH = Path(__file__).resolve().parent / "templates"
STATIC_PATH = Path(__file__).resolve().parent / "static"
DEMO_CUSTOMER_ID = "CLI-5A1RQN103PRE"
OTHER_CUSTOMER_ID = "CLI-OTHER-OWNER"


class DemoConfigurationError(RuntimeError):
    """Raised when the demo cannot obtain its authoritative catalog."""


def load_demo_catalog() -> tuple[dict[tuple[str, str], list[dict[str, str]]], str]:
    """Load only the explicit product file, failing closed on any catalog error."""
    try:
        rows, source = load_product_file(PRODUCTS_PATH)
    except (CatalogError, OSError) as exc:
        raise DemoConfigurationError(str(exc)) from exc
    return build_catalog(rows), source


def evaluate_request(
    query: str,
    authenticated: bool,
    customer_id: str = DEMO_CUSTOMER_ID,
    authenticated_customer_id: str | None = None,
) -> dict[str, Any]:
    """Adapt UI state into the engine's case shape and expose presentation data."""
    catalog, source = load_demo_catalog()
    auth_id = (
        authenticated_customer_id
        if authenticated_customer_id is not None
        else customer_id if authenticated else ""
    )
    case = {
        "case_id": "demo",
        "customer_id": customer_id,
        "customer_text": query,
        "authenticated_customer_id": auth_id,
    }
    prediction = decide_case(case, catalog)
    product_type = extract_product_type(query)
    product = None
    if prediction.predicted_product_id:
        for entries in catalog.values():
            for candidate in entries:
                if candidate.get("product_id") == prediction.predicted_product_id:
                    product = candidate
                    break
            if product:
                break

    action = prediction.predicted_action
    response = ground_response(action, product, product_type)
    disclosure_allowed = action == "READ_BALANCE" and product is not None
    return {
        "pipeline": {
            "intent": prediction.predicted_intent,
            "product": product_type or "Not identified",
            "resolution": prediction.predicted_resolution,
            "authorization": prediction.predicted_authorization,
            "action": prediction.predicted_action,
            "outcome": prediction.predicted_outcome,
        },
        "result": {
            "message": response,
            "disclosure_allowed": disclosure_allowed,
            "product_type": product.get("product_type", "") if disclosure_allowed else "",
            "product_number": prediction.predicted_product_number if disclosure_allowed else "",
            "balance": prediction.predicted_balance if disclosure_allowed else "",
            "currency": prediction.predicted_currency if disclosure_allowed else "",
        },
        "catalog_source": source,
        "customer_scope": customer_id,
        "scope_note": "Resolution is limited to the requested customer scope.",
    }


class DemoHandler(BaseHTTPRequestHandler):
    """Serve the static demo and its one local evaluation endpoint."""

    server_version = "DeterministicDemo/1.0"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._serve_file(TEMPLATES_PATH / "index.html", "text/html; charset=utf-8")
        elif path == "/static/style.css":
            self._serve_file(STATIC_PATH / "style.css", "text/css; charset=utf-8")
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/evaluate":
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            query = str(payload.get("query", "")).strip()
            if not query:
                raise ValueError("query is required")
            mode = payload.get("session_mode", "authenticated")
            if mode not in {"authenticated", "unauthenticated", "wrong-owner"}:
                raise ValueError("invalid session_mode")
            result = evaluate_request(
                query,
                authenticated=mode == "authenticated",
                authenticated_customer_id=(
                    OTHER_CUSTOMER_ID if mode == "wrong-owner" else None
                ),
            )
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except DemoConfigurationError as exc:
            self._send_json({"error": f"Catalog unavailable: {exc}"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self._send_json(result, HTTPStatus.OK)

    def _serve_file(self, path: Path, content_type: str) -> None:
        try:
            content = path.read_bytes()
        except OSError:
            self._send_json({"error": "Demo asset unavailable"}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[demo] {format % args}")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), DemoHandler)
    print("Deterministic demo running at http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping demo.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
