"""
evaluate_rules.py — Hallucination and quality evaluation for extracted safety rules.

Two evaluation modes:
  1. run_brutal_evaluation(pdf_path, extraction_data)
     — Full 4-check evaluation requiring the source PDF (text presence,
       page accuracy, category validity, severity consistency).

  2. run_structure_evaluation(extraction_data)
     — Structural checks only (no PDF needed): actionable rule present,
       original text present, valid categories, severity assigned.

Usage (CLI):
    python evaluate_rules.py output/rules.json [--pdf source.pdf]
"""

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("safety_extraction.evaluate")

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

ALLOWED_CATEGORIES = {
    "electrical", "chemical", "woodworking", "power_tools",
    "heat_fire", "mechanical", "PPE_required", "child_safety",
    "toxic_exposure", "ventilation", "structural", "general_safety",
}

HAZARD_KEYWORDS = [
    "toxic", "fatal", "death", "electrocution", "fire",
    "explosion", "asbestos", "cyanide", "carbon monoxide",
    "burn", "amputation", "crush",
]


# ---------------------------------------------------------------------------
# Brutal evaluation (requires source PDF)
# ---------------------------------------------------------------------------

def run_brutal_evaluation(pdf_path: str, extraction_data: dict) -> dict:
    """
    4-check hallucination evaluation against the source PDF.

    Checks:
      1. text_presence     — Is original_text actually found anywhere in the PDF?
      2. page_accuracy     — Is original_text on the claimed page (±1)?
      3. category_validity — Are all categories in the allowed set?
      4. severity_consistency — Is validated_severity appropriate for hazard keywords?
    """
    try:
        import pymupdf as fitz  # PyMuPDF (preferred)
    except Exception:
        import fitz  # type: ignore  # PyMuPDF fallback

    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

    doc = fitz.open(pdf_path)
    page_texts: dict[int, str] = {}
    for page_num in range(len(doc)):
        page_texts[page_num + 1] = doc[page_num].get_text().strip().lower()
    doc.close()

    check_totals = {
        "text_presence": {"passed": 0, "total": 0},
        "page_accuracy": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "severity_consistency": {"passed": 0, "total": 0},
    }
    results_per_rule = []

    for rule in rules:
        original_text = (rule.get("original_text") or "").lower().strip()
        page_num = rule.get("page_number")
        actionable = (rule.get("actionable_rule") or "").strip()
        categories = rule.get("categories", [])
        suggested_sev = rule.get("suggested_severity") or 1
        validated_sev = rule.get("validated_severity") or suggested_sev

        checks = {}
        failed = []

        # 1. Text Presence
        text_found = False
        if original_text and len(original_text) > 10:
            for pt in page_texts.values():
                if original_text in pt:
                    text_found = True
                    break
            if not text_found:
                words = original_text.split()
                for pt in page_texts.values():
                    matched_words = sum(1 for w in words if w in pt)
                    if len(words) > 0 and matched_words / len(words) >= 0.6:
                        text_found = True
                        break
        elif original_text:
            text_found = True

        checks["text_presence"] = text_found
        check_totals["text_presence"]["total"] += 1
        if text_found:
            check_totals["text_presence"]["passed"] += 1
        else:
            failed.append("text_presence")

        # 2. Page Accuracy
        page_ok = False
        if page_num and original_text and len(original_text) > 10:
            words = original_text.split()[:8]
            search_str = " ".join(words)
            for offset in [0, -1, 1]:
                check_page = page_num + offset
                if check_page in page_texts and search_str in page_texts[check_page]:
                    page_ok = True
                    break
            if not page_ok:
                for offset in [0, -1, 1]:
                    check_page = page_num + offset
                    if check_page in page_texts:
                        matched = sum(1 for w in words if w in page_texts[check_page])
                        if len(words) > 0 and matched / len(words) >= 0.7:
                            page_ok = True
                            break
        else:
            page_ok = True

        checks["page_accuracy"] = page_ok
        check_totals["page_accuracy"]["total"] += 1
        if page_ok:
            check_totals["page_accuracy"]["passed"] += 1
        else:
            failed.append("page_accuracy")

        # 3. Category Validity
        cats_valid = all(c in ALLOWED_CATEGORIES for c in categories) if categories else True
        checks["category_validity"] = cats_valid
        check_totals["category_validity"]["total"] += 1
        if cats_valid:
            check_totals["category_validity"]["passed"] += 1
        else:
            failed.append("category_validity")

        # 4. Severity Consistency
        combined_text = original_text + " " + actionable.lower()
        has_hazard = any(kw in combined_text for kw in HAZARD_KEYWORDS)
        severity_ok = True
        if has_hazard and validated_sev < 3:
            severity_ok = False
        if validated_sev < suggested_sev:
            severity_ok = False

        checks["severity_consistency"] = severity_ok
        check_totals["severity_consistency"]["total"] += 1
        if severity_ok:
            check_totals["severity_consistency"]["passed"] += 1
        else:
            failed.append("severity_consistency")

        results_per_rule.append({
            "rule_id": rule.get("rule_id", ""),
            "actionable_rule": actionable[:100],
            "checks": checks,
            "all_passed": len(failed) == 0,
            "failed_checks": failed,
        })

    total_rules = len(rules)
    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())
    per_check_accuracy = {
        name: round(ct["passed"] / ct["total"] * 100, 1) if ct["total"] > 0 else 100.0
        for name, ct in check_totals.items()
    }
    overall_accuracy = round(total_passed / total_checks * 100, 1) if total_checks > 0 else 100.0
    failed_rules = [r for r in results_per_rule if not r["all_passed"]]

    return {
        "total_rules": total_rules,
        "total_checks": total_checks,
        "checks_passed": total_passed,
        "overall_accuracy": overall_accuracy,
        "per_check_accuracy": per_check_accuracy,
        "rules_all_passed": total_rules - len(failed_rules),
        "rules_with_failures": len(failed_rules),
        "failed_rules": failed_rules[:50],
    }


# ---------------------------------------------------------------------------
# Structure evaluation (no PDF required)
# ---------------------------------------------------------------------------

def run_structure_evaluation(extraction_data: dict) -> dict:
    """
    Structural evaluation — checks rule shape without needing the source PDF.

    Checks:
      1. has_actionable_rule — actionable_rule field is non-empty
      2. has_original_text   — original_text field is non-empty
      3. category_validity   — all categories are in the allowed set
      4. has_severity        — validated_severity is set
    """
    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

    check_totals = {
        "has_actionable_rule": {"passed": 0, "total": 0},
        "has_original_text": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "has_severity": {"passed": 0, "total": 0},
    }
    results_per_rule = []

    for rule in rules:
        checks = {}
        failed = []

        has_action = bool((rule.get("actionable_rule") or "").strip())
        checks["has_actionable_rule"] = has_action
        check_totals["has_actionable_rule"]["total"] += 1
        if has_action:
            check_totals["has_actionable_rule"]["passed"] += 1
        else:
            failed.append("has_actionable_rule")

        has_orig = bool((rule.get("original_text") or "").strip())
        checks["has_original_text"] = has_orig
        check_totals["has_original_text"]["total"] += 1
        if has_orig:
            check_totals["has_original_text"]["passed"] += 1
        else:
            failed.append("has_original_text")

        categories = rule.get("categories", [])
        cats_valid = all(c in ALLOWED_CATEGORIES for c in categories) if categories else True
        checks["category_validity"] = cats_valid
        check_totals["category_validity"]["total"] += 1
        if cats_valid:
            check_totals["category_validity"]["passed"] += 1
        else:
            failed.append("category_validity")

        has_sev = rule.get("validated_severity") is not None
        checks["has_severity"] = has_sev
        check_totals["has_severity"]["total"] += 1
        if has_sev:
            check_totals["has_severity"]["passed"] += 1
        else:
            failed.append("has_severity")

        results_per_rule.append({
            "rule_id": rule.get("rule_id", ""),
            "actionable_rule": (rule.get("actionable_rule") or "")[:100],
            "checks": checks,
            "all_passed": len(failed) == 0,
            "failed_checks": failed,
        })

    total_rules = len(rules)
    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())
    per_check_accuracy = {
        name: round(ct["passed"] / ct["total"] * 100, 1) if ct["total"] > 0 else 100.0
        for name, ct in check_totals.items()
    }
    overall_accuracy = round(total_passed / total_checks * 100, 1) if total_checks > 0 else 100.0
    failed_rules = [r for r in results_per_rule if not r["all_passed"]]

    return {
        "total_rules": total_rules,
        "total_checks": total_checks,
        "checks_passed": total_passed,
        "overall_accuracy": overall_accuracy,
        "per_check_accuracy": per_check_accuracy,
        "rules_all_passed": total_rules - len(failed_rules),
        "rules_with_failures": len(failed_rules),
        "failed_rules": failed_rules[:50],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Evaluate extracted safety rules for hallucination and quality."
    )
    parser.add_argument("json_file", help="Path to the extraction JSON output file.")
    parser.add_argument("--pdf", default=None, help="Source PDF for brutal evaluation (text presence checks).")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        logger.error("File not found: %s", json_path)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as fh:
        extraction_data = json.load(fh)

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            logger.error("PDF not found: %s", pdf_path)
            sys.exit(1)
        logger.info("Running brutal evaluation with PDF: %s", pdf_path.name)
        results = run_brutal_evaluation(str(pdf_path), extraction_data)
    else:
        logger.info("Running structural evaluation (no PDF provided).")
        results = run_structure_evaluation(extraction_data)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
