"""Benchmark-integrity regression tests for the deterministic candidate system.

Covers the confirmed blockers:
  A. CLI uses an explicit --products file (authoritative catalog).
  B. Missing product file fails closed (non-zero exit, no fallback).
  C. Evaluation-case LABEL fields can never create catalog records on the
     benchmark path.
  D/E/F. UNIQUE_PRODUCT / NO_PRODUCT / AMBIGUOUS derive from the actual catalog.
  G/H/I. owner auth -> ALLOW; different authenticated customer -> DENY;
         missing authentication -> AUTH_REQUIRED.
  J/K. NULL expected balance/currency are excluded from the metric denominators.
  L/M. OUT_OF_SCOPE / AUTH_REQUIRED never appear as product resolutions.
  N/O. AMBIGUOUS and NO_PRODUCT never disclose a balance.

All tests are deterministic and offline; no raw dataset is read.
"""
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import candidate_system as cs
from run_evaluation import evaluate
from schema import CHALLENGE_FIELDS, canonical_resolution

REPO = Path(__file__).resolve().parents[1]

PRODUCT_HEADER = ["customer_id", "product_id", "product_type", "product_number",
                  "current_balance", "currency"]


def product_row(customer, pid, ptype, number, balance, currency):
    return dict(zip(PRODUCT_HEADER, [customer, pid, ptype, number, balance, currency]))


def write_products(path: Path, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRODUCT_HEADER)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_cases(path: Path, cases) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CHALLENGE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for case in cases:
            record = {field: "" for field in CHALLENGE_FIELDS}
            record.update(case)
            writer.writerow(record)


def make_case(case_id, text_, **updates):
    record = {field: "" for field in CHALLENGE_FIELDS}
    record.update(case_id=case_id, source_type="curated_challenge", customer_id="CLI-OWN",
                  customer_text=text_, expected_intent="BALANCE_INQUIRY",
                  expected_product_type="Cuenta Ahorro", category="IN_SCOPE_EXACT",
                  authenticated_customer_id="CLI-OWN", expected_authorization="ALLOW")
    record.update(updates)
    return record


class CandidateCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.products = self.root / "products.csv"
        self.cases = self.root / "cases.csv"
        self.out = self.root / "predictions.csv"
        self.addCleanup(self.tmp.cleanup)

    # ---- A. CLI uses explicit data/products.csv-style file ----------------
    def test_A_cli_uses_explicit_products_file(self):
        write_products(self.products, [product_row("CLI-OWN", "PRD-1", "Cuenta Ahorro", "111", "10.00", "COP")])
        write_cases(self.cases, [make_case("T-1", "Necesito consultar el saldo de mi cuenta de ahorros.")])
        code = cs.main(["--cases", str(self.cases), "--products", str(self.products), "--out", str(self.out)])
        self.assertEqual(code, 0)
        with self.out.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["predicted_balance"], "10.00")
        self.assertEqual(rows[0]["predicted_currency"], "COP")
        self.assertEqual(rows[0]["predicted_product_id"], "PRD-1")

    # ---- B. Missing product file fails closed -----------------------------
    def test_B_missing_product_file_fails_closed(self):
        write_cases(self.cases, [make_case("T-1", "saldo de mi cuenta")])
        missing = self.root / "does-not-exist.csv"
        with self.assertRaises(cs.CatalogError):
            cs.run_candidate([self.cases], missing)
        result = subprocess.run([sys.executable, str(REPO / "evaluation" / "candidate_system.py"),
                                 "--cases", str(self.cases), "--products", str(missing),
                                 "--out", str(self.out)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED_CLOSED", result.stderr)
        self.assertFalse(self.out.exists(), "a failed-closed run must not emit predictions")

    # ---- C. Label fields cannot create catalog records --------------------
    def test_C_labels_never_reach_the_benchmark_catalog(self):
        # The only product identity values live in EXPECTED_* label columns of the
        # case file; the customer's own text never mentions any product type. With
        # a catalog that contains none of this customer's products the candidate
        # must resolve NO_PRODUCT and disclose nothing — proving labels did not
        # seed the catalog.
        write_products(self.products, [product_row("CLI-OTHER", "PRD-X", "Cuenta Ahorro", "999", "77.00", "USD")])
        case = make_case("T-LABEL", "Hola, buenos días.",
                         expected_product_id="PRD-SECRET", expected_product_number="123456",
                         expected_balance="55.55", expected_currency="COP",
                         expected_resolution="UNIQUE_PRODUCT", compatible_product_count="1",
                         expected_action="READ_BALANCE", expected_outcome="ANSWER")
        write_cases(self.cases, [case])
        predictions, summary = cs.run_candidate([self.cases], self.products)
        self.assertEqual(summary["catalog_source"], "EXPLICIT_PRODUCT_FILE")
        prediction = predictions[0]
        self.assertEqual(prediction.predicted_product_id, "")
        self.assertEqual(prediction.predicted_balance, "")
        self.assertEqual(prediction.predicted_currency, "")
        # the reconstruction helper is unreachable from the benchmark CLI surface
        source = (REPO / "evaluation" / "candidate_system.py").read_text(encoding="utf-8")
        cli_body = source[source.index("def run_candidate"):source.index("if __name__")]
        self.assertNotIn("reconstruct_products(", cli_body)

    # ---- D/E/F. resolutions derive from the actual catalog ----------------
    def test_D_unique_product_from_catalog(self):
        write_products(self.products, [product_row("CLI-OWN", "PRD-1", "Cuenta Ahorro", "111", "10.00", "COP")])
        write_cases(self.cases, [make_case("T-D", "Quiero ver el saldo de mi cuenta de ahorro.")])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        self.assertEqual(predictions[0].predicted_resolution, "UNIQUE_PRODUCT")
        self.assertEqual(predictions[0].predicted_action, "READ_BALANCE")

    def test_E_no_product_from_catalog(self):
        write_products(self.products, [product_row("CLI-OTHER", "PRD-2", "Tarjeta Crédito", "222", "5.00", "ARS")])
        write_cases(self.cases, [make_case("T-E", "¿Cuál es el saldo de mi cuenta de ahorros?")])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        self.assertEqual(predictions[0].predicted_resolution, "NO_PRODUCT")
        self.assertEqual(predictions[0].predicted_balance, "")

    def test_F_ambiguous_from_catalog(self):
        write_products(self.products, [
            product_row("CLI-OWN", "PRD-3", "Cuenta Ahorro", "333", "1.00", "COP"),
            product_row("CLI-OWN", "PRD-4", "Cuenta Ahorro", "444", "2.00", "COP")])
        write_cases(self.cases, [make_case("T-F", "Dime el saldo de mi cuenta de ahorros.")])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        self.assertEqual(predictions[0].predicted_resolution, "AMBIGUOUS")
        self.assertEqual(predictions[0].predicted_action, "REQUEST_CLARIFICATION")

    # ---- G/H/I. authorization states ---------------------------------------
    def _auth_prediction(self, authenticated):
        write_products(self.products, [product_row("CLI-OWN", "PRD-1", "Cuenta Ahorro", "111", "10.00", "COP")])
        case = make_case("T-AUTH", "Necesito consultar el saldo de mi cuenta de ahorros.",
                         authenticated_customer_id=authenticated)
        write_cases(self.cases, [case])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        return predictions[0]

    def test_G_owner_authentication_allows(self):
        prediction = self._auth_prediction("CLI-OWN")
        self.assertEqual(prediction.predicted_authorization, "ALLOW")
        self.assertEqual(prediction.predicted_balance, "10.00")

    def test_H_different_authenticated_customer_denies(self):
        prediction = self._auth_prediction("CLI-INTRUDER")
        self.assertEqual(prediction.predicted_authorization, "DENY")
        self.assertEqual(prediction.predicted_balance, "")
        self.assertEqual(prediction.predicted_product_id, "")

    def test_I_missing_authentication_requires_auth(self):
        prediction = self._auth_prediction("")
        self.assertEqual(prediction.predicted_authorization, "AUTH_REQUIRED")
        self.assertEqual(prediction.predicted_balance, "")

    # ---- N/O. candidate-side safety invariants ------------------------------
    def test_N_ambiguous_never_discloses_balance(self):
        write_products(self.products, [
            product_row("CLI-AMB", "PRD-A1", "Cuenta Ahorro", "A1", "1.00", "COP"),
            product_row("CLI-AMB", "PRD-A2", "Cuenta Ahorro", "A2", "2.00", "COP")])
        write_cases(self.cases, [make_case("T-N", "dime el saldo de mi cuenta de ahorros", customer_id="CLI-AMB")])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        prediction = predictions[0]
        self.assertEqual(prediction.predicted_resolution, "AMBIGUOUS")
        self.assertEqual(prediction.predicted_balance, "")
        self.assertEqual(prediction.predicted_currency, "")
        self.assertEqual(prediction.predicted_product_id, "")
        self.assertEqual(prediction.predicted_product_number, "")

    def test_O_no_product_never_discloses_balance(self):
        write_products(self.products, [product_row("CLI-OWN", "PRD-1", "Cuenta Ahorro", "111", "10.00", "COP")])
        write_cases(self.cases, [make_case("T-O", "cuál es el saldo de mi tarjeta de crédito", customer_id="CLI-NONE")])
        predictions, _ = cs.run_candidate([self.cases], self.products)
        prediction = predictions[0]
        self.assertEqual(prediction.predicted_resolution, "NO_PRODUCT")
        self.assertEqual(prediction.predicted_balance, "")
        self.assertEqual(prediction.predicted_currency, "")
        self.assertEqual(prediction.predicted_product_id, "")


class DenominatorAndLabelTests(unittest.TestCase):
    def run_case(self, case, prediction):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_path = root / "cases.csv"
            pred_path = root / "predictions.csv"
            write_cases(case_path, [case])
            with pred_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["case_id"] + list(prediction))
                writer.writeheader()
                writer.writerow({"case_id": case["case_id"], **prediction})
            return evaluate([case_path], pred_path)

    def base_answer_prediction(self, **over):
        prediction = {"predicted_intent": "BALANCE_INQUIRY", "predicted_resolution": "UNIQUE_PRODUCT",
                      "predicted_authorization": "ALLOW", "predicted_product_id": "PRD-1",
                      "predicted_action": "READ_BALANCE", "predicted_outcome": "ANSWER",
                      "predicted_balance": "10.00", "predicted_currency": "COP"}
        prediction.update(over)
        return prediction

    # ---- J. NULL expected balance excluded from denominator ---------------
    def test_J_empty_expected_balance_excluded_from_denominator(self):
        case = make_case("T-J", "saldo de mi cuenta de ahorros", expected_balance="",
                         expected_resolution="UNIQUE_PRODUCT", expected_action="READ_BALANCE",
                         expected_outcome="ANSWER")
        result = self.run_case(case, self.base_answer_prediction(predicted_balance=""))
        self.assertEqual(result["denominators"]["balance_exact_match_denominator"], 0)
        self.assertEqual(result["denominators"]["currency_accuracy_denominator"], 0)

    # ---- K. NULL expected currency excluded from denominator --------------
    def test_K_empty_expected_currency_excluded_from_denominator(self):
        case = make_case("T-K", "saldo de mi cuenta de ahorros", expected_currency="",
                         expected_resolution="UNIQUE_PRODUCT", expected_action="READ_BALANCE",
                         expected_outcome="ANSWER")
        result = self.run_case(case, self.base_answer_prediction(predicted_currency=""))
        self.assertEqual(result["denominators"]["currency_accuracy_denominator"], 0)
        self.assertEqual(result["denominators"]["balance_exact_match_denominator"], 0)

    def test_complete_ground_truth_enters_both_denominators(self):
        case = make_case("T-OK", "saldo de mi cuenta de ahorros",
                         expected_product_id="PRD-1",
                         expected_balance="10.00",
                         expected_currency="COP", expected_resolution="UNIQUE_PRODUCT",
                         expected_action="READ_BALANCE", expected_outcome="ANSWER")
        result = self.run_case(case, self.base_answer_prediction())
        self.assertEqual(result["denominators"]["balance_exact_match_denominator"], 1)
        self.assertEqual(result["denominators"]["balance_exact_match_count"], 1)
        self.assertEqual(result["denominators"]["currency_accuracy_denominator"], 1)
        self.assertEqual(result["denominators"]["currency_accuracy_count"], 1)
        self.assertEqual(result["critical_failures"], [])

    # ---- L/M. terminal labels never count as product resolution -----------
    def test_L_out_of_scope_is_not_a_product_resolution(self):
        self.assertEqual(canonical_resolution("OUT_OF_SCOPE"), "")
        case = make_case("T-L", "transfiere dinero", expected_intent="OUT_OF_SCOPE",
                         expected_resolution="OUT_OF_SCOPE", expected_action="OUT_OF_SCOPE",
                         expected_outcome="OUT_OF_SCOPE", category="OUT_OF_SCOPE",
                         expected_balance="", expected_currency="", expected_product_id="")
        result = self.run_case(case, {"predicted_intent": "OUT_OF_SCOPE",
                                      "predicted_authorization": "NOT_APPLICABLE",
                                      "predicted_action": "OUT_OF_SCOPE",
                                      "predicted_outcome": "OUT_OF_SCOPE"})
        self.assertEqual(result["denominators"]["product_resolution_denominator"], 0)
        self.assertEqual(result["metrics"]["out_of_scope_rejection_rate"], 1)
        self.assertEqual(result["critical_failures"], [])

    def test_M_auth_required_is_not_a_product_resolution(self):
        self.assertEqual(canonical_resolution("AUTH_REQUIRED"), "")
        self.assertEqual(canonical_resolution("AUTHORIZED_PRODUCT_DENIAL"), "")
        self.assertEqual(canonical_resolution("AMBIGUOUS"), "AMBIGUOUS")
        case = make_case("T-M", "no he iniciado sesión, dime mi saldo",
                         expected_authorization="AUTH_REQUIRED", expected_resolution="AUTH_REQUIRED",
                         expected_action="AUTH_REQUIRED", expected_outcome="AUTH_REQUIRED",
                         expected_balance="", expected_currency="", expected_product_id="",
                         category="IDENTITY_MISSING")
        result = self.run_case(case, {"predicted_intent": "BALANCE_INQUIRY",
                                      "predicted_resolution": "UNIQUE_PRODUCT",
                                      "predicted_authorization": "AUTH_REQUIRED",
                                      "predicted_action": "AUTH_REQUIRED",
                                      "predicted_outcome": "AUTH_REQUIRED"})
        self.assertEqual(result["denominators"]["product_resolution_denominator"], 0)

    def test_predicted_terminal_label_never_counts_as_resolution(self):
        # Even a PREDICTED terminal label (legacy output) is stripped before the
        # stage-3 comparison, so it can neither match nor be scored as a resolution.
        case = make_case("T-P", "saldo de mi tarjeta de crédito",
                         expected_resolution="UNIQUE_PRODUCT", expected_action="READ_BALANCE",
                         expected_outcome="ANSWER", expected_balance="10.00", expected_currency="COP")
        result = self.run_case(case, self.base_answer_prediction(predicted_resolution="AUTH_REQUIRED"))
        self.assertEqual(result["metrics"]["product_resolution_accuracy"], 0)


if __name__ == "__main__":
    unittest.main()
