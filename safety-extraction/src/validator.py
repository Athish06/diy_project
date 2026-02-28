

import logging
import re
from typing import Any

from src.constants import SKIP_LEMMAS, SKIP_POS_TAGS, VAGUE_PHRASES

logger = logging.getLogger("safety_extraction")


class RuleValidator:

    def __init__(self) -> None:
        import spacy

        try:
            self._nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.error(
                "spaCy model 'en_core_web_sm' not found. "
                "Run: python -m spacy download en_core_web_sm"
            )
            raise

    def validate_and_normalize(
        self, rules: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        
        validated: list[dict[str, Any]] = []

        for rule in rules:
            action = rule.get("actionable_rule", "").strip()
            if not action:
                logger.debug("Discarding rule with empty actionable_rule.")
                continue

            # --- Vague rule filter ---
            action_lower = action.lower()
            if any(phrase in action_lower for phrase in VAGUE_PHRASES):
                logger.warning("Discarding vague rule: '%s'", action[:100])
                continue

            # --- Compound rule splitting ---
            split_rules = self._split_compound_rule(rule)

            for sub_rule in split_rules:
                normalised = self._normalize_verb(sub_rule)
                if normalised is not None:
                    validated.append(normalised)

        logger.info(
            "Validation: %d rules in → %d rules out",
            len(rules), len(validated),
        )
        return validated


    def _split_compound_rule(
        self, rule: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Split where 'and' conjoins two **verbs**.
        Do NOT split when 'and' conjoins two **noun objects**.
        """
        action = rule.get("actionable_rule", "")
        doc = self._nlp(action)

        # Find conjunctions connecting verbs
        verb_conj_pairs: list[tuple[Any, Any]] = []
        for token in doc:
            if (
                token.dep_ == "conj"
                and token.head.pos_ == "VERB"
                and token.pos_ == "VERB"
            ):
                verb_conj_pairs.append((token.head, token))

        if not verb_conj_pairs:
            return [rule]

        split_rules: list[dict[str, Any]] = []

        for head_verb, conj_verb in verb_conj_pairs:
            # Find coordinating conjunction between the two verbs
            cc_token = None
            for token in doc:
                if (
                    token.dep_ == "cc"
                    and token.head == conj_verb
                    and head_verb.i < token.i < conj_verb.i
                ):
                    cc_token = token
                    break

            if cc_token is None:
                return [rule]

            clause1_tokens = [t for t in doc if t.i < cc_token.i]
            clause2_tokens = [t for t in doc if t.i > cc_token.i]

            clause1 = "".join(
                t.text_with_ws for t in clause1_tokens
            ).strip().rstrip(",").strip()
            clause2 = "".join(
                t.text_with_ws for t in clause2_tokens
            ).strip()

            if clause2 and clause2[0].islower():
                clause2 = clause2[0].upper() + clause2[1:]

            if clause1 and clause2:
                split_rules.extend([
                    {**rule, "actionable_rule": clause1},
                    {**rule, "actionable_rule": clause2},
                ])
                logger.info(
                    "Split compound rule: '%s' → ['%s', '%s']",
                    action[:80], clause1[:60], clause2[:60],
                )
            else:
                split_rules.append(rule)

        return split_rules if split_rules else [rule]


    def _normalize_verb(self, rule: dict[str, Any]) -> dict[str, Any] | None:
        """
        Ensure ``actionable_rule`` starts with a verb.  Skips leading
        adverbs (Always, Never, …).  Lemmatises the leading verb.
        Returns ``None`` if no leading verb is found.
        """
        action = rule.get("actionable_rule", "").strip()
        if not action:
            return None

        doc = self._nlp(action)
        verb_idx = None

        for token in doc:
            if token.pos_ in SKIP_POS_TAGS or token.lemma_.lower() in SKIP_LEMMAS:
                continue
            if token.pos_ == "VERB":
                verb_idx = token.i
                break
            else:
                logger.warning(
                    "Rule does not start with a verb (first token: '%s' POS=%s): '%s'",
                    token.text, token.pos_, action[:100],
                )
                return None

        if verb_idx is None:
            logger.warning("No verb found in rule: '%s'", action[:100])
            return None

        verb_token = doc[verb_idx]
        lemma = verb_token.lemma_.capitalize()

        leading = "".join(t.text_with_ws for t in doc[:verb_idx])
        rest = "".join(t.text_with_ws for t in doc[verb_idx + 1:])
        normalised_action = f"{leading}{lemma} {rest}".strip()
        normalised_action = re.sub(r"\s+", " ", normalised_action)

        rule["actionable_rule"] = normalised_action
        return rule
