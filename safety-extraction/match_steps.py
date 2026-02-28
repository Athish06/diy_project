"""
CLI bridge for matching DIY steps against safety rules database.

Called by the Tauri Rust backend via subprocess:

    python match_steps.py --steps-file <path_to_json> --analyze

Input JSON format (--steps-file):
[
  {
    "step_number": 1,
    "title": "Prepare the wiring",
    "action": "strip wire ends",
    "instructions": ["Strip 1/2 inch of insulation from each wire"],
    "tools": ["wire stripper"],
    "materials": ["14-gauge romex"],
    "safety_context": "Working with electrical wiring",
    "estimated_time": "5 minutes"
  },
  ...
]

Output JSON to stdout:
{
  "verdict": "UNSAFE",
  "severity_score": 3.75,
  "total_steps": 5,
  "total_violations": 1,
  "total_missing_precautions": 3,
  "total_high_risk_flags": 1,
  "violations": [...],
  "missing_precautions": [...],
  "high_risk_flags": [...],
  "step_analyses": [...],
  "hazard_categories": [...]
}
"""

import argparse
import io
import json
import logging
import sys
from pathlib import Path

# Force UTF-8 stdout so Unicode characters don't crash on Windows (cp1252)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Ensure the parent package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,  # Logs to stderr so stdout is pure JSON
)
logger = logging.getLogger("match_steps")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match DIY procedure steps against safety rules database"
    )
    parser.add_argument(
        "--steps-file",
        required=True,
        help="Path to JSON file containing extracted DIY steps",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=True,
        help="Run full compliance analysis (default)",
    )
    args = parser.parse_args()

    # Load steps from file
    steps_path = Path(args.steps_file)
    if not steps_path.exists():
        print(json.dumps({"error": f"Steps file not found: {steps_path}"}))
        sys.exit(1)

    try:
        steps_data = json.loads(steps_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(json.dumps({"error": f"Failed to parse steps JSON: {e}"}))
        sys.exit(1)

    if not isinstance(steps_data, list):
        print(json.dumps({"error": "Steps JSON must be an array of step objects"}))
        sys.exit(1)

    if not steps_data:
        print(json.dumps({"error": "No steps provided"}))
        sys.exit(1)

    logger.info("Loaded %d steps from %s", len(steps_data), steps_path)

    # Initialize NLP and matching components
    try:
        from src.matcher import StepNormalizer, RuleMatcher
        from src.compliance import generate_compliance_report

        logger.info("Initializing NLP models...")
        normalizer = StepNormalizer()
        matcher = RuleMatcher()
        logger.info("NLP models loaded successfully")

    except Exception as e:
        print(json.dumps({"error": f"Failed to initialize matching engine: {e}"}))
        sys.exit(1)

    # Process each step
    step_analyses = []
    for step_data in steps_data:
        step_num = step_data.get("step_number", "?")
        logger.info("Analyzing step %s: %s", step_num, step_data.get("action_summary", ""))

        try:
            # 1. Normalize
            normalized = normalizer.normalize(step_data)
            logger.info(
                "  Hazard categories: %s | Action verbs: %s",
                normalized.hazard_categories,
                normalized.action_verbs[:5],
            )

            # 2. Embed + search + classify
            analysis = matcher.analyze_step(normalized)
            logger.info(
                "  Results: %d violations, %d missing precautions, %d high-risk flags",
                len(analysis.violations),
                len(analysis.missing_precautions),
                len(analysis.high_risk_flags),
            )

            step_analyses.append(analysis)

        except Exception as e:
            logger.error("  Error analyzing step %s: %s", step_num, e)
            # Add empty analysis so we don't skip steps
            from src.matcher import StepAnalysis
            step_analyses.append(StepAnalysis(
                step_number=step_data.get("step_number", 0),
                action_summary=step_data.get("action_summary", ""),
            ))

    # Generate compliance report
    report = generate_compliance_report(step_analyses, total_steps=len(steps_data))

    logger.info(
        "Compliance report: verdict=%s, severity=%.2f, "
        "violations=%d, missing=%d, high_risk=%d",
        report.verdict,
        report.severity_score,
        report.total_violations,
        report.total_missing_precautions,
        report.total_high_risk_flags,
    )

    # Output to stdout
    print(json.dumps(report.to_dict(), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
