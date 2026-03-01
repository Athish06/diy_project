

import json
import logging
import re
from typing import Any

from src.constants import ALLOWED_CATEGORIES
from src.exceptions import ExtractionError
from src.prompt import EXTRACTION_PROMPT

logger = logging.getLogger("safety_extraction")


class GroqExtractor:
    """Wraps the Groq SDK for structured safety rule extraction."""

    def __init__(
        self,
        api_key: str,
        model_name: str = "qwen/qwen3-32b",
        max_retries: int = 3,
    ) -> None:
        from groq import Groq

        self._client = Groq(api_key=api_key)
        self._model_name = model_name
        self._max_retries = max_retries

        logger.info("Groq extractor initialised — model=%s", model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    def extract_rules(
        self,
        text: str,
        document_name: str,
        page_number: int,
        section_heading: str,
    ) -> list[dict[str, Any]]:
        
        if not text.strip():
            return []

        prompt = EXTRACTION_PROMPT.format(
            document_name=document_name,
            section_heading=section_heading,
            page_number=page_number,
            text=text,
        )

        last_error: Exception | None = None
        raw: str = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._model_name,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a safety compliance extraction engine. "
                                "Return ONLY a valid JSON array. No commentary."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )

                raw = response.choices[0].message.content or ""
                rules = _parse_json_response(raw)
                rules = _enforce_categories(rules)

                # Attach source metadata
                for rule in rules:
                    rule["source_document"] = document_name
                    rule["page_number"] = page_number
                    rule["section_heading"] = section_heading

                logger.info(
                    "Page %d: extracted %d rules (attempt %d)",
                    page_number, len(rules), attempt,
                )
                return rules

            except json.JSONDecodeError as exc:
                last_error = exc
                logger.warning(
                    "Page %d attempt %d: JSON parse failed — %s | raw[:500]=%s",
                    page_number, attempt, exc,
                    raw[:500] if raw else "<empty>",
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Page %d attempt %d: Extraction error — %s",
                    page_number, attempt, exc,
                )

        raise ExtractionError(
            f"Failed to extract rules from page {page_number} of "
            f"'{document_name}' after {self._max_retries} attempts. "
            f"Last error: {last_error}"
        )




def _parse_json_response(raw: str) -> list[dict[str, Any]]:
   
    if not raw or not raw.strip():
        return []

    text = raw.strip()

    # Strip <think>...</think> blocks (qwen3 reasoning wrapper)
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()

    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Extract first JSON array via bracket matching
    if not text.startswith("["):
        start = text.find("[")
        if start == -1:
            raise json.JSONDecodeError("No JSON array found in response", text, 0)
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        text = text[start:end]

    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise json.JSONDecodeError("Response is not a JSON array", text, 0)

    # Filter out non-dict items (model sometimes returns strings)
    parsed = [item for item in parsed if isinstance(item, dict)]

    return parsed


def _enforce_categories(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace hallucinated categories with ``general_safety``."""
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        categories = rule.get("category", rule.get("categories", []))
        if isinstance(categories, str):
            categories = [categories]

        cleaned: list[str] = []
        for cat in categories:
            if cat in ALLOWED_CATEGORIES:
                cleaned.append(cat)
            else:
                logger.warning(
                    "Hallucinated category '%s' replaced with 'general_safety' "
                    "in rule: %s", cat, rule.get("actionable_rule", "")[:80],
                )
                cleaned.append("general_safety")

        # Deduplicate while preserving order
        rule["categories"] = list(dict.fromkeys(cleaned))
        rule.pop("category", None)

    return rules
