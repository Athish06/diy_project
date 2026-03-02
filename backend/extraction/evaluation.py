"""Hallucination evaluation for extracted safety rules.

Includes:
  - run_brutal_evaluation: 4-check evaluation with PDF text verification
  - run_structure_evaluation: 3-check structural evaluation (no PDF needed)
  - save_evaluation_results: persist results to DB
"""

import json

from db.connection import get_db_connection


def save_evaluation_results(run_id: int, evaluation: dict) -> None:
    """Store evaluation results JSON in the extraction_runs table."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE extraction_runs SET evaluation_results = %s WHERE id = %s",
                (json.dumps(evaluation), run_id),
            )
        conn.commit()
    finally:
        conn.close()


def run_brutal_evaluation(pdf_path: str, extraction_data: dict) -> dict:
    """
    4-check brutal evaluation to detect hallucination.

    Checks:
      1. Text Presence: Is original_text actually in the PDF?
      2. Page Accuracy: Is original_text on the claimed page?
      3. Category Validity: Are categories in the allowed set?
      4. Severity Consistency: Is validated_severity >= suggested_severity for hazardous rules?
    """
    import fitz  # PyMuPDF

    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

    # Load PDF pages
    doc = fitz.open(pdf_path)
    page_texts: dict[int, str] = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_texts[page_num + 1] = page.get_text().strip().lower()

    doc.close()

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

    results_per_rule = []
    check_totals = {
        "text_presence": {"passed": 0, "total": 0},
        "page_accuracy": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "severity_consistency": {"passed": 0, "total": 0},
    }

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
        combined_text = (original_text + " " + actionable.lower())
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

    # Aggregate scores
    total_rules = len(rules)
    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())

    per_check_accuracy = {}
    for check_name, ct in check_totals.items():
        if ct["total"] > 0:
            per_check_accuracy[check_name] = round(ct["passed"] / ct["total"] * 100, 1)
        else:
            per_check_accuracy[check_name] = 100.0

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


def run_structure_evaluation(extraction_data: dict) -> dict:
    """Structural evaluation (no PDF needed): rule structure, categories, severity."""
    rules = extraction_data.get("rules", [])
    if not rules:
        return {"total_rules": 0, "overall_accuracy": 100.0, "checks": {}}

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
    IMPERATIVE_STARTERS = {
        "wear", "use", "ensure", "inspect", "verify", "check", "avoid",
        "maintain", "keep", "store", "place", "install", "remove", "clean",
        "replace", "test", "secure", "ground", "disconnect", "apply",
        "protect", "follow", "do", "provide", "label", "mark", "cover",
        "ventilate", "monitor", "report", "shut", "turn", "lock",
        "never", "always", "immediately", "properly", "regularly",
        "operate", "handle", "dispose", "measure", "attach",
    }

    check_totals = {
        "rule_structure": {"passed": 0, "total": 0},
        "category_validity": {"passed": 0, "total": 0},
        "severity_consistency": {"passed": 0, "total": 0},
    }
    results_per_rule = []

    for rule in rules:
        actionable = (rule.get("actionable_rule") or "").strip()
        categories = rule.get("categories", [])
        suggested_sev = rule.get("suggested_severity") or 1
        validated_sev = rule.get("validated_severity") or suggested_sev
        original_text = (rule.get("original_text") or "").lower()

        checks = {}
        failed = []

        # Rule structure
        rule_ok = False
        if actionable:
            first_word = actionable.split()[0].lower().rstrip(".,;:")
            rule_ok = first_word in IMPERATIVE_STARTERS
            if not rule_ok and len(actionable.split()) > 1:
                second_word = actionable.split()[1].lower().rstrip(".,;:")
                if first_word in {
                    "always", "never", "immediately", "properly",
                    "regularly", "strictly", "not", "do",
                }:
                    rule_ok = second_word in IMPERATIVE_STARTERS
        checks["rule_structure"] = rule_ok
        check_totals["rule_structure"]["total"] += 1
        if rule_ok:
            check_totals["rule_structure"]["passed"] += 1
        else:
            failed.append("rule_structure")

        # Category validity
        cats_valid = all(c in ALLOWED_CATEGORIES for c in categories) if categories else True
        checks["category_validity"] = cats_valid
        check_totals["category_validity"]["total"] += 1
        if cats_valid:
            check_totals["category_validity"]["passed"] += 1
        else:
            failed.append("category_validity")

        # Severity consistency
        combined = original_text + " " + actionable.lower()
        has_hazard = any(kw in combined for kw in HAZARD_KEYWORDS)
        sev_ok = True
        if has_hazard and validated_sev < 3:
            sev_ok = False
        if validated_sev < suggested_sev:
            sev_ok = False
        checks["severity_consistency"] = sev_ok
        check_totals["severity_consistency"]["total"] += 1
        if sev_ok:
            check_totals["severity_consistency"]["passed"] += 1
        else:
            failed.append("severity_consistency")

        results_per_rule.append({
            "rule_id": str(rule.get("rule_id", "")),
            "actionable_rule": actionable[:100],
            "checks": checks,
            "all_passed": len(failed) == 0,
            "failed_checks": failed,
        })

    total_checks = sum(ct["total"] for ct in check_totals.values())
    total_passed = sum(ct["passed"] for ct in check_totals.values())
    per_check_accuracy = {}
    for name, ct in check_totals.items():
        per_check_accuracy[name] = (
            round(ct["passed"] / ct["total"] * 100, 1) if ct["total"] > 0 else 100.0
        )

    overall = round(total_passed / total_checks * 100, 1) if total_checks > 0 else 100.0
    failed_rules = [r for r in results_per_rule if not r["all_passed"]]

    return {
        "total_rules": len(rules),
        "total_checks": total_checks,
        "checks_passed": total_passed,
        "overall_accuracy": overall,
        "per_check_accuracy": per_check_accuracy,
        "rules_all_passed": len(rules) - len(failed_rules),
        "rules_with_failures": len(failed_rules),
        "failed_rules": failed_rules[:50],
        "evaluation_type": "structural",
    }
