

import re


ALLOWED_CATEGORIES: set[str] = {
    "electrical",
    "chemical",
    "woodworking",
    "power_tools",
    "heat_fire",
    "mechanical",
    "PPE_required",
    "child_safety",
    "toxic_exposure",
    "ventilation",
    "structural",
    "general_safety",
}


VAGUE_PHRASES: list[str] = [
    "be careful",
    "ensure safety",
    "use caution",
    "exercise care",
    "take precaution",
    "take care",
    "be aware",
    "use common sense",
]

# 
# Deterministic severity override patterns


SEVERITY_PATTERNS: list[tuple[re.Pattern, int, str]] = [
    # Toxic / fatal — force severity 5
    (
        re.compile(
            r"(toxic[\s\-]?gas|chlorine[\s\-]?gas|bleach[\s\-]?and[\s\-]?ammonia"
            r"|hydrogen[\s\-]?sulfide|carbon[\s\-]?monoxide|cyanide[\s\-]?gas"
            r"|phosgene|nerve[\s\-]?agent)",
            re.IGNORECASE,
        ),
        5,
        "toxic_fatal",
    ),
    # High voltage / live electrical — severity >= 4
    (
        re.compile(
            r"(high[\s\-]?voltage|live[\s\-]?wire|live[\s\-]?current"
            r"|exposed[\s\-]?live[\s\-]?conductor|energized[\s\-]?circuit"
            r"|arc[\s\-]?flash|electrical[\s\-]?shock)",
            re.IGNORECASE,
        ),
        4,
        "electrical_hazard",
    ),
    # PPE mentions — severity >= 3
    (
        re.compile(
            r"(goggles|gloves|helmet|hard[\s\-]?hat|respirator|face[\s\-]?shield"
            r"|ear[\s\-]?protect|hearing[\s\-]?protect|ppe|protective[\s\-]?equipment"
            r"|safety[\s\-]?glasses|steel[\s\-]?toe)",
            re.IGNORECASE,
        ),
        3,
        "ppe_mention",
    ),
]


# Heading detection regexes


NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+\.?\d*\.?\d*)\s+[A-Z]")
ALLCAPS_RE = re.compile(r"^[A-Z][A-Z\s\d\-:./()]{2,}$")


# Adverbs / particles to skip when validating verb-first rules


SKIP_POS_TAGS: set[str] = {"ADV", "PART"}

SKIP_LEMMAS: set[str] = {
    "always", "never", "immediately", "regularly",
    "periodically", "routinely", "continuously", "not",
    "do", "only", "also", "first", "then",
}
