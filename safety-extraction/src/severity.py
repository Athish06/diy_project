
import logging
import re
from typing import Any

from src.constants import SEVERITY_PATTERNS

logger = logging.getLogger("safety_extraction")


def override_severity(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
   
    for rule in rules:
        suggested = rule.get("suggested_severity", 1)
        validated = suggested

        # Normalise: lowercase, strip punctuation, collapse whitespace
        action = rule.get("actionable_rule", "")
        normalised = re.sub(r"[^\w\s\-]", "", action.lower())
        normalised = re.sub(r"\s+", " ", normalised).strip()

        original = rule.get("original_text", "")
        normalised_original = re.sub(r"[^\w\s\-]", "", original.lower())
        normalised_original = re.sub(r"\s+", " ", normalised_original).strip()

        combined = f"{normalised} {normalised_original}"

        for pattern, min_severity, label in SEVERITY_PATTERNS:
            if pattern.search(combined):
                if label == "toxic_fatal":
                    validated = 5
                    logger.debug(
                        "Severity override (%s): rule='%s' → severity=5",
                        label, action[:60],
                    )
                elif label == "ppe_mention":
                    if validated < min_severity:
                        logger.debug(
                            "Severity override (%s): rule='%s' → severity %d→%d",
                            label, action[:60], validated, min_severity,
                        )
                        validated = min_severity
                else:
                    if validated < min_severity:
                        logger.debug(
                            "Severity override (%s): rule='%s' → severity %d→%d",
                            label, action[:60], validated, min_severity,
                        )
                        validated = max(validated, min_severity)

        rule["validated_severity"] = validated

    return rules
