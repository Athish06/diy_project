"""
Hybrid matching engine for DIY step ↔ safety rule comparison.

1. Normalize step text (spaCy lemmatization, tool/material extraction, hazard keyword detection)
2. Embed normalized step text (all-MiniLM-L6-v2, 384-dim)
3. pgvector cosine similarity → candidate rules (top-K above threshold)
4. Deterministic filters classify each candidate:
   - Violation: step contradicts a rule
   - Missing precaution: rule requires something not mentioned in step
   - High-risk action: step implies hazardous operation
"""

import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np

from src.constants import SEVERITY_PATTERNS

logger = logging.getLogger("safety_extraction.matcher")


HAZARD_KEYWORDS: dict[str, list[str]] = {
    "electrical": [
        "wire", "wiring", "circuit", "breaker", "outlet", "voltage", "amp",
        "fuse", "junction", "conduit", "grounding", "ground", "neutral",
        "hot wire", "live wire", "panel", "switch", "receptacle", "romex",
        "electrical", "power", "current", "shock", "electrocute",
    ],
    "cutting": [
        "cut", "saw", "blade", "circular saw", "table saw", "miter",
        "jigsaw", "bandsaw", "chisel", "knife", "router", "trim",
        "snip", "shear", "slice", "chop",
    ],
    "chemical": [
        "paint", "stain", "solvent", "adhesive", "glue", "epoxy",
        "bleach", "ammonia", "acid", "chemical", "fumes", "vapor",
        "lacquer", "polyurethane", "varnish", "thinner",
    ],
    "height": [
        "ladder", "scaffold", "roof", "attic", "climb", "height",
        "elevated", "fall", "harness", "above ground",
    ],
    "heat_fire": [
        "solder", "weld", "torch", "heat gun", "flame", "burn",
        "hot", "fire", "ignite", "flammable", "combustible",
        "furnace", "boiler", "pilot light",
    ],
    "heavy_mechanical": [
        "lift", "heavy", "load", "jack", "hoist", "crane",
        "support", "brace", "structural", "beam", "joist",
        "foundation", "weight", "compress",
    ],
    "sharp": [
        "sharp", "edge", "point", "needle", "nail", "screw",
        "splinter", "burr", "abrasive", "grind",
    ],
    "pressure": [
        "pressure", "compressor", "pneumatic", "hydraulic",
        "psi", "air tool", "nail gun", "staple gun",
    ],
    "respiratory": [
        "dust", "particle", "asbestos", "mold", "insulation",
        "fiberglass", "sawdust", "silica", "mask", "respirator",
        "ventilation", "ventilate", "fume",
    ],
}

# PPE keywords for detecting missing PPE precautions
PPE_KEYWORDS: dict[str, list[str]] = {
    "eye_protection": ["goggles", "safety glasses", "eye protection", "face shield"],
    "hand_protection": ["gloves", "hand protection", "work gloves"],
    "hearing_protection": ["ear protection", "hearing protection", "ear plugs", "ear muffs"],
    "respiratory_protection": ["respirator", "mask", "dust mask", "n95", "half-face"],
    "head_protection": ["hard hat", "helmet", "head protection"],
    "body_protection": ["apron", "coveralls", "long sleeves", "steel toe", "safety boots"],
}

# Precaution verbs/phrases that indicate safety actions
PRECAUTION_PHRASES: list[str] = [
    "disconnect power", "turn off power", "shut off", "de-energize",
    "lock out", "tag out", "lockout", "tagout", "loto",
    "ventilate", "open windows", "ensure ventilation",
    "wear", "put on", "use protection",
    "secure", "clamp", "brace", "support",
    "check", "inspect", "verify", "test",
    "clear area", "remove debris", "clean up",
    "unplug", "remove battery", "isolate",
    "ground", "bond",
]

# Contradiction patterns: (step_pattern, rule_pattern, explanation)
CONTRADICTION_PATTERNS: list[tuple[re.Pattern, re.Pattern, str]] = [
    (
        re.compile(r"connect.*(?:wire|cable|conductor).*(?:breaker|panel|box|live)", re.I),
        re.compile(r"disconnect.*power|de-?energize|turn off.*power|shut off", re.I),
        "Step involves connecting to live electrical without disconnecting power first",
    ),
    (
        re.compile(r"(?:mix|combine).*(?:bleach|chlorine).*(?:ammonia|acid)", re.I),
        re.compile(r"never.*(?:mix|combine)|do not.*(?:mix|combine)", re.I),
        "Step involves mixing incompatible chemicals",
    ),
    (
        re.compile(r"(?:cut|saw).*(?:toward|towards).*(?:body|self|you)", re.I),
        re.compile(r"(?:cut|saw).*away.*(?:body|self|you)", re.I),
        "Step involves cutting toward body instead of away",
    ),
    (
        re.compile(r"remove.*(?:guard|safety|shield).*(?:saw|blade|tool)", re.I),
        re.compile(r"(?:keep|leave|maintain).*(?:guard|safety|shield)", re.I),
        "Step involves removing a safety guard",
    ),
]



@dataclass
class NormalizedStep:
    """A DIY step after NLP normalization."""
    step_number: int
    transcript_excerpt: str
    step_text: str
    action_summary: str

    # Derived fields (populated during normalization)
    lemmatized_text: str = ""
    action_verbs: list[str] = field(default_factory=list)
    hazard_categories: list[str] = field(default_factory=list)
    hazard_keywords_found: list[str] = field(default_factory=list)
    ppe_mentioned: list[str] = field(default_factory=list)
    precautions_mentioned: list[str] = field(default_factory=list)

    def full_text(self) -> str:
        """Combine all text fields for embedding."""
        parts = [self.action_summary, self.step_text]
        if self.transcript_excerpt:
            parts.append(self.transcript_excerpt)
        return " ".join(parts)


@dataclass
class RuleMatch:
    """A single matched safety rule with classification."""
    rule_id: str
    rule_text: str
    severity: int
    category: str
    similarity: float
    match_type: str  # "violation" | "missing_precaution" | "high_risk"
    explanation: str
    source_document: str = ""
    materials: list[str] = field(default_factory=list)


@dataclass
class StepAnalysis:
    """Complete analysis of one DIY step."""
    step_number: int
    action_summary: str
    violations: list[RuleMatch] = field(default_factory=list)
    missing_precautions: list[RuleMatch] = field(default_factory=list)
    high_risk_flags: list[RuleMatch] = field(default_factory=list)
    hazard_categories: list[str] = field(default_factory=list)
    max_severity: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action_summary": self.action_summary,
            "violations": [asdict(v) for v in self.violations],
            "missing_precautions": [asdict(m) for m in self.missing_precautions],
            "high_risk_flags": [asdict(h) for h in self.high_risk_flags],
            "hazard_categories": self.hazard_categories,
            "max_severity": self.max_severity,
        }



class StepNormalizer:
    """Normalize DIY step text using spaCy NLP."""

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

    def normalize(self, step: dict[str, Any]) -> NormalizedStep:
        """Normalize a raw DIY step dict into NormalizedStep."""
        ns = NormalizedStep(
            step_number=step.get("step_number", 0),
            transcript_excerpt=step.get("transcript_excerpt", ""),
            step_text=step.get("step_text", ""),
            action_summary=step.get("action_summary", ""),
        )

        full_text = ns.full_text()
        full_lower = full_text.lower()

        # Lemmatize
        doc = self._nlp(full_text)
        ns.lemmatized_text = " ".join(
            token.lemma_.lower() for token in doc
            if not token.is_punct and not token.is_space
        )

        # Extract action verbs
        ns.action_verbs = list({
            token.lemma_.lower() for token in doc
            if token.pos_ == "VERB"
        })

        # Detect hazard categories
        for category, keywords in HAZARD_KEYWORDS.items():
            for kw in keywords:
                if kw in full_lower or kw in ns.lemmatized_text:
                    if category not in ns.hazard_categories:
                        ns.hazard_categories.append(category)
                    if kw not in ns.hazard_keywords_found:
                        ns.hazard_keywords_found.append(kw)

        # Detect PPE mentions
        for ppe_type, keywords in PPE_KEYWORDS.items():
            for kw in keywords:
                if kw in full_lower:
                    ns.ppe_mentioned.append(ppe_type)
                    break

        # Detect precaution mentions
        for phrase in PRECAUTION_PHRASES:
            if phrase in full_lower:
                ns.precautions_mentioned.append(phrase)

        return ns



class RuleMatcher:
    """
    Match normalized DIY steps against the safety rules database.

    Flow:
    1. Embed step text → 384-dim vector
    2. pgvector cosine search → top-K candidate rules
    3. Deterministic classification of each candidate
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        similarity_threshold: float = 0.30,
        top_k: int = 15,
    ) -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", model_name)
        self._embedder = SentenceTransformer(model_name)
        self._threshold = similarity_threshold
        self._top_k = top_k

    def embed_text(self, text: str) -> np.ndarray:
        """Encode text into 384-dim embedding."""
        return self._embedder.encode(text, show_progress_bar=False)

    def find_candidate_rules(
        self,
        embedding: np.ndarray,
        hazard_categories: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Query pgvector for rules similar to the step embedding.

        Uses the IVFFlat index with cosine distance operator (<=>).
        Optionally filters by hazard-relevant categories.
        """
        from src.db import get_connection

        conn = get_connection(register_vec=False)
        try:
            # Convert numpy array to pgvector string format
            vec_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"

            # Build query with optional category filter
            base_query = """
                SELECT
                    rule_id, actionable_rule, original_text, materials,
                    validated_severity, categories, source_document,
                    page_number, section_heading,
                    1 - (embedding <=> %s::vector) AS similarity
                FROM safety_rules
                WHERE embedding IS NOT NULL
            """
            params: list[Any] = [vec_str]

            if hazard_categories:
                # Filter to rules whose categories overlap with the step's hazard categories
                base_query += " AND categories && %s::text[]"
                params.append(hazard_categories)

            base_query += """
                ORDER BY embedding <=> %s::vector
                LIMIT %s
            """
            params.extend([vec_str, self._top_k])

            from psycopg2.extras import RealDictCursor
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(base_query, params)
                rows = cur.fetchall()

            candidates = []
            for row in rows:
                r = dict(row)
                sim = float(r.get("similarity", 0))
                if sim >= self._threshold:
                    r["similarity"] = sim
                    if r.get("rule_id"):
                        r["rule_id"] = str(r["rule_id"])
                    candidates.append(r)

            logger.info(
                "pgvector search: %d candidates above threshold %.2f (from %d total)",
                len(candidates), self._threshold, len(rows),
            )
            return candidates

        finally:
            conn.close()

    def classify_matches(
        self,
        step: NormalizedStep,
        candidates: list[dict[str, Any]],
    ) -> StepAnalysis:
        """
        Apply deterministic filters to classify each candidate rule.

        Three classification types:
        1. Violation — step contradicts a rule
        2. Missing precaution — rule requires something not mentioned
        3. High-risk action — step implies hazardous operation
        """
        analysis = StepAnalysis(
            step_number=step.step_number,
            action_summary=step.action_summary,
            hazard_categories=step.hazard_categories,
        )

        step_text_lower = step.full_text().lower()
        step_lemma = step.lemmatized_text

        for candidate in candidates:
            rule_text = candidate.get("actionable_rule", "")
            rule_lower = rule_text.lower()
            severity = candidate.get("validated_severity") or candidate.get("suggested_severity") or 3
            similarity = candidate.get("similarity", 0)
            categories = candidate.get("categories", [])

            match = RuleMatch(
                rule_id=candidate.get("rule_id", ""),
                rule_text=rule_text,
                severity=severity,
                category=", ".join(categories) if categories else "general_safety",
                similarity=similarity,
                match_type="",
                explanation="",
                source_document=candidate.get("source_document", ""),
                materials=candidate.get("materials", []) or [],
            )

            classified = False

            # --- 1. Check for violations (contradictions) ---
            for step_pat, rule_pat, explanation in CONTRADICTION_PATTERNS:
                if step_pat.search(step_text_lower) and rule_pat.search(rule_lower):
                    match.match_type = "violation"
                    match.explanation = explanation
                    analysis.violations.append(match)
                    classified = True
                    break

            if classified:
                continue

            # --- 2. Check for missing precautions ---
            missing_explanation = self._check_missing_precaution(
                step, rule_text, rule_lower, categories, candidate.get("materials", [])
            )
            if missing_explanation:
                match.match_type = "missing_precaution"
                match.explanation = missing_explanation
                analysis.missing_precautions.append(match)
                classified = True
                continue

            # --- 3. Check for high-risk actions ---
            if severity >= 4 and similarity >= 0.40:
                # Step has hazard overlap with a high-severity rule
                overlapping_hazards = [
                    h for h in step.hazard_categories
                    if any(h in cat.lower() for cat in categories)
                ]
                if overlapping_hazards or similarity >= 0.55:
                    match.match_type = "high_risk"
                    match.explanation = (
                        f"High-severity rule (level {severity}) matches this step "
                        f"(similarity {similarity:.2f}). "
                        f"Hazard overlap: {', '.join(overlapping_hazards) if overlapping_hazards else 'semantic match'}"
                    )
                    analysis.high_risk_flags.append(match)
                    continue

        # Compute max severity across all matches
        all_matches = analysis.violations + analysis.missing_precautions + analysis.high_risk_flags
        if all_matches:
            analysis.max_severity = max(m.severity for m in all_matches)

        return analysis

    def _check_missing_precaution(
        self,
        step: NormalizedStep,
        rule_text: str,
        rule_lower: str,
        categories: list[str],
        rule_materials: list[str] | None,
    ) -> str | None:
        """
        Check if a rule requires a precaution that the step doesn't mention.
        Returns explanation string if missing, None if precaution is present.
        """
        step_lower = step.full_text().lower()

        # -- PPE checks --
        # If rule mentions PPE and step doesn't mention corresponding PPE
        for ppe_type, keywords in PPE_KEYWORDS.items():
            rule_mentions_ppe = any(kw in rule_lower for kw in keywords)
            if rule_mentions_ppe and ppe_type not in step.ppe_mentioned:
                # Check if the rule's PPE is relevant to this step's hazards
                relevant = False
                if "PPE_required" in categories:
                    relevant = True
                elif ppe_type == "eye_protection" and any(
                    h in step.hazard_categories
                    for h in ["cutting", "chemical", "sharp", "pressure"]
                ):
                    relevant = True
                elif ppe_type == "respiratory_protection" and any(
                    h in step.hazard_categories
                    for h in ["chemical", "respiratory"]
                ):
                    relevant = True
                elif ppe_type == "hearing_protection" and any(
                    h in step.hazard_categories
                    for h in ["cutting", "pressure", "heavy_mechanical"]
                ):
                    relevant = True
                elif ppe_type == "hand_protection" and any(
                    h in step.hazard_categories
                    for h in ["chemical", "sharp", "heat_fire", "electrical"]
                ):
                    relevant = True

                if relevant:
                    ppe_name = ppe_type.replace("_", " ")
                    return (
                        f"Rule requires {ppe_name} but step doesn't mention it. "
                        f"Relevant for: {', '.join(step.hazard_categories)}"
                    )

        # -- Disconnect/de-energize checks --
        if any(h in step.hazard_categories for h in ["electrical"]):
            disconnect_in_rule = any(
                phrase in rule_lower
                for phrase in [
                    "disconnect", "de-energize", "turn off", "shut off",
                    "power off", "lockout", "lock out",
                ]
            )
            disconnect_in_step = any(
                phrase in step_lower
                for phrase in [
                    "disconnect", "de-energize", "turn off", "shut off",
                    "power off", "lockout", "lock out", "unplug",
                ]
            )
            if disconnect_in_rule and not disconnect_in_step:
                return (
                    "Rule requires disconnecting/de-energizing power, "
                    "but step doesn't mention power isolation"
                )

        # -- Ventilation checks --
        if any(h in step.hazard_categories for h in ["chemical", "respiratory"]):
            ventilation_in_rule = any(
                phrase in rule_lower
                for phrase in ["ventilat", "open window", "fresh air", "exhaust"]
            )
            ventilation_in_step = any(
                phrase in step_lower
                for phrase in ["ventilat", "open window", "fresh air", "exhaust", "outdoor"]
            )
            if ventilation_in_rule and not ventilation_in_step:
                return (
                    "Rule requires adequate ventilation, "
                    "but step doesn't mention ventilation or air flow"
                )

        # -- Securing/clamping checks --
        if any(h in step.hazard_categories for h in ["cutting", "sharp"]):
            secure_in_rule = any(
                phrase in rule_lower
                for phrase in ["clamp", "secure", "hold firmly", "vise", "vice"]
            )
            secure_in_step = any(
                phrase in step_lower
                for phrase in ["clamp", "secure", "hold", "vise", "vice", "fixture"]
            )
            if secure_in_rule and not secure_in_step:
                return (
                    "Rule requires securing workpiece (clamp/vise), "
                    "but step doesn't mention securing the material"
                )

        return None

    def analyze_step(self, step: NormalizedStep) -> StepAnalysis:
        """
        Full analysis pipeline for one normalized step.

        1. Embed → 2. pgvector search → 3. Classify matches
        """
        # First try with category-filtered search for precision
        embedding = self.embed_text(step.lemmatized_text or step.full_text())

        candidates = []
        if step.hazard_categories:
            candidates = self.find_candidate_rules(
                embedding, hazard_categories=step.hazard_categories
            )

        # If no category-filtered results, fall back to unfiltered search
        if len(candidates) < 3:
            all_candidates = self.find_candidate_rules(embedding, hazard_categories=None)
            # Merge, avoiding duplicates
            seen_ids = {c["rule_id"] for c in candidates}
            for c in all_candidates:
                if c["rule_id"] not in seen_ids:
                    candidates.append(c)
                    seen_ids.add(c["rule_id"])

        return self.classify_matches(step, candidates)
