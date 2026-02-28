"""
Compliance verdict generator.

Takes per-step StepAnalysis results and produces an overall compliance report:
  - Verdict: SAFE / UNSAFE / PROFESSIONAL_REQUIRED
  - Aggregate severity score
  - Violation/missing precaution/high-risk summaries
"""

import logging
from dataclasses import dataclass, field
from typing import Any

from src.matcher import StepAnalysis, RuleMatch

logger = logging.getLogger("safety_extraction.compliance")


@dataclass
class ComplianceReport:
    """Overall compliance verdict for a DIY procedure."""

    # Verdict: "SAFE", "UNSAFE", or "PROFESSIONAL_REQUIRED"
    verdict: str = "SAFE"

    # Weighted severity score (0–5 scale)
    severity_score: float = 0.0

    # Aggregate counts
    total_steps: int = 0
    total_violations: int = 0
    total_missing_precautions: int = 0
    total_high_risk_flags: int = 0
    total_matched_rules: int = 0

    # Flattened lists (all steps combined)
    violations: list[dict[str, Any]] = field(default_factory=list)
    missing_precautions: list[dict[str, Any]] = field(default_factory=list)
    high_risk_flags: list[dict[str, Any]] = field(default_factory=list)

    # Per-step breakdown
    step_analyses: list[dict[str, Any]] = field(default_factory=list)

    # Hazard categories found across all steps
    hazard_categories: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "severity_score": round(self.severity_score, 2),
            "total_steps": self.total_steps,
            "total_violations": self.total_violations,
            "total_missing_precautions": self.total_missing_precautions,
            "total_high_risk_flags": self.total_high_risk_flags,
            "total_matched_rules": self.total_matched_rules,
            "violations": self.violations,
            "missing_precautions": self.missing_precautions,
            "high_risk_flags": self.high_risk_flags,
            "step_analyses": self.step_analyses,
            "hazard_categories": self.hazard_categories,
        }


def _match_to_dict(match: RuleMatch, step_number: int) -> dict[str, Any]:
    """Convert a RuleMatch to a dict, adding step_number for context."""
    return {
        "step_number": step_number,
        "rule_id": match.rule_id,
        "rule_text": match.rule_text,
        "severity": match.severity,
        "category": match.category,
        "similarity": round(match.similarity, 3),
        "match_type": match.match_type,
        "explanation": match.explanation,
        "source_document": match.source_document,
    }


def generate_compliance_report(
    step_analyses: list[StepAnalysis],
    total_steps: int,
) -> ComplianceReport:

    report = ComplianceReport(total_steps=total_steps)

    all_severities: list[int] = []
    all_hazards: set[str] = set()

    for sa in step_analyses:
        report.step_analyses.append(sa.to_dict())
        all_hazards.update(sa.hazard_categories)

        # Flatten violations
        for v in sa.violations:
            report.violations.append(_match_to_dict(v, sa.step_number))
            all_severities.append(v.severity)

        # Flatten missing precautions
        for mp in sa.missing_precautions:
            report.missing_precautions.append(_match_to_dict(mp, sa.step_number))
            all_severities.append(mp.severity)

        # Flatten high-risk flags
        for hr in sa.high_risk_flags:
            report.high_risk_flags.append(_match_to_dict(hr, sa.step_number))
            all_severities.append(hr.severity)

    report.total_violations = len(report.violations)
    report.total_missing_precautions = len(report.missing_precautions)
    report.total_high_risk_flags = len(report.high_risk_flags)
    report.total_matched_rules = (
        report.total_violations
        + report.total_missing_precautions
        + report.total_high_risk_flags
    )
    report.hazard_categories = sorted(all_hazards)

    # Compute weighted severity score
    if all_severities:
        # Weight: violations count 3x, missing precautions 2x, high-risk 1.5x
        weighted_sum = 0.0
        weight_total = 0.0

        for v in report.violations:
            weighted_sum += v["severity"] * 3.0
            weight_total += 3.0
        for mp in report.missing_precautions:
            weighted_sum += mp["severity"] * 2.0
            weight_total += 2.0
        for hr in report.high_risk_flags:
            weighted_sum += hr["severity"] * 1.5
            weight_total += 1.5

        report.severity_score = weighted_sum / weight_total if weight_total > 0 else 0.0
    else:
        report.severity_score = 0.0

    # --- Determine verdict ---
    sev5_high_risk = any(hr["severity"] >= 5 for hr in report.high_risk_flags)
    sev4_violations = [v for v in report.violations if v["severity"] >= 4]
    sev4_missing = [mp for mp in report.missing_precautions if mp["severity"] >= 4]

    if sev5_high_risk:
        report.verdict = "PROFESSIONAL_REQUIRED"
        logger.warning("Verdict: PROFESSIONAL_REQUIRED — severity-5 high-risk flag")
    elif len(sev4_violations) >= 2:
        report.verdict = "PROFESSIONAL_REQUIRED"
        logger.warning("Verdict: PROFESSIONAL_REQUIRED — 2+ severity-4 violations")
    elif len(sev4_missing) >= 3:
        report.verdict = "PROFESSIONAL_REQUIRED"
        logger.warning("Verdict: PROFESSIONAL_REQUIRED — 3+ severity-4 missing precautions")
    elif report.total_violations > 0:
        report.verdict = "UNSAFE"
        logger.warning("Verdict: UNSAFE — %d violation(s)", report.total_violations)
    elif len(sev4_missing) > 0:
        report.verdict = "UNSAFE"
        logger.warning("Verdict: UNSAFE — severity-4 missing precaution(s)")
    elif report.total_missing_precautions >= 3:
        report.verdict = "UNSAFE"
        logger.warning("Verdict: UNSAFE — 3+ missing precautions")
    else:
        report.verdict = "SAFE"
        logger.info("Verdict: SAFE")

    return report
