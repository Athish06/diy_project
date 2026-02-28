"""
Final LLM-based safety assessment.

Takes extracted DIY steps + matched safety rules from pgvector
and produces a comprehensive safety report via Groq LLM:
  - Overall verdict (SAFE / UNSAFE / PROFESSIONAL_REQUIRED)
  - Per-step safety analysis with required / already-mentioned / missing precautions
  - Parent monitoring recommendation
  - Critical concerns and recommendations
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("diy.safety_analyzer")

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SAFETY_CATEGORIES_LIST = [
    "electrical", "chemical", "woodworking", "power_tools", "heat_fire",
    "mechanical", "PPE_required", "child_safety", "toxic_exposure",
    "ventilation", "structural", "general_safety",
]

SAFETY_ANALYSIS_PROMPT = """You are an expert DIY Safety Analyst and Compliance Officer.

You are given:
1. Extracted DIY steps from a video tutorial (with transcript excerpts)
2. Matched safety rules from a professional compliance database (matched via cosine similarity on semantic embeddings)
3. The video's safety-relevant categories

Your task is to produce a THOROUGH, DETAILED safety assessment.

FOR EACH STEP:
- Identify what safety precautions MUST be followed (based on matched rules AND general safety knowledge for the category)
- Identify what safety measures the creator ALREADY mentions or demonstrates in the video
- Identify what safety measures are MISSING and need to be added
- Assign a risk level (1-5 scale):
  1 = Minimal risk, basic caution
  2 = Low risk, some care needed
  3 = Moderate risk, specific precautions required
  4 = High risk, serious injury possible without precautions
  5 = Critical risk, professional supervision recommended

OVERALL ASSESSMENT:
- SAFE: No significant safety gaps, creator follows good practices
- UNSAFE: Important safety precautions are missing or violated
- PROFESSIONAL_REQUIRED: Activity involves hazards that need trained professional oversight

PARENT MONITORING:
Assess whether parent/adult monitoring is needed based on:
- Tools and materials used (sharp objects, chemicals, heat sources, power tools)
- Skill level required
- Potential for serious injury
- Whether the activity is suitable for children/teens without supervision
- This applies to ALL videos regardless of stated audience

CRITICAL: Your response must be ONLY valid JSON. No markdown, no code fences, no explanation text.

OUTPUT FORMAT:
{
  "verdict": "SAFE" | "UNSAFE" | "PROFESSIONAL_REQUIRED",
  "overall_risk_score": <1.0-5.0>,
  "parent_monitoring_required": true | false,
  "parent_monitoring_reason": "<concise reason why monitoring is/isn't needed>",
  "summary": "<2-3 sentence overall safety summary>",
  "critical_concerns": ["<most important concern 1>", "<concern 2>"],
  "step_safety_analysis": [
    {
      "step_number": 1,
      "action_summary": "<what the step does>",
      "risk_level": <1-5>,
      "required_precautions": ["<precaution that MUST be followed>"],
      "already_mentioned_precautions": ["<precautions the creator already mentions/shows>"],
      "missing_precautions": ["<precautions NOT mentioned but needed>"],
      "matched_rules": [
        {
          "rule_text": "<the safety rule>",
          "severity": <1-5>,
          "category": "<category>",
          "relevance": "<why this rule applies to this step>"
        }
      ]
    }
  ],
  "safety_measures_in_video": ["<all safety measures mentioned across entire video>"],
  "recommended_additional_measures": ["<measures not in video but strongly recommended>"]
}

/no_think"""


def _build_user_message(
    steps: list[dict[str, Any]],
    rules_per_step: dict[int, list[dict[str, Any]]],
    safety_categories: list[str],
    video_title: str = "",
) -> str:
    """Build the user prompt with steps and matched rules."""
    parts = []

    if video_title:
        parts.append(f"VIDEO TITLE: {video_title}\n")

    parts.append(f"SAFETY CATEGORIES: {', '.join(safety_categories)}\n")

    parts.append("=" * 60)
    parts.append("EXTRACTED DIY STEPS:")
    parts.append("=" * 60)

    for step in steps:
        step_num = step.get("step_number", "?")
        parts.append(f"\n--- Step {step_num} ---")
        parts.append(f"Action: {step.get('action_summary', 'N/A')}")
        parts.append(f"Instruction: {step.get('step_text', 'N/A')}")
        excerpt = step.get("transcript_excerpt", "")
        if excerpt:
            parts.append(f"Transcript: \"{excerpt}\"")

        # Add matched rules for this step
        matched = rules_per_step.get(step_num, [])
        if matched:
            parts.append(f"\nMATCHED SAFETY RULES ({len(matched)} rules):")
            for i, rule in enumerate(matched, 1):
                severity = rule.get("validated_severity") or rule.get("suggested_severity", 3)
                cats = rule.get("categories", [])
                sim = rule.get("similarity", 0)
                parts.append(
                    f"  {i}. [{severity}/5] [{', '.join(cats)}] "
                    f"(similarity: {sim:.0%}) {rule.get('actionable_rule', '')}"
                )
        else:
            parts.append("\nMATCHED SAFETY RULES: None found")

    return "\n".join(parts)


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences and noise from JSON response."""
    trimmed = text.strip()

    if trimmed.startswith("```"):
        newline_pos = trimmed.find("\n")
        if newline_pos >= 0:
            after_fence = trimmed[newline_pos + 1:]
        else:
            after_fence = trimmed.lstrip("`")
        stripped = after_fence.rstrip("`").strip()
    else:
        stripped = trimmed

    obj_start = stripped.find("{")
    obj_end = stripped.rfind("}")
    if obj_start >= 0 and obj_end >= 0 and obj_end > obj_start:
        return stripped[obj_start: obj_end + 1]

    return stripped


async def analyze_safety(
    steps: list[dict[str, Any]],
    rules_per_step: dict[int, list[dict[str, Any]]],
    safety_categories: list[str],
    video_title: str = "",
    api_key: str | None = None,
    model: str = "qwen/qwen3-32b",
) -> dict[str, Any]:
    """
    Call Groq LLM with steps + matched rules to produce a safety report.

    Returns a parsed JSON dict with the safety assessment.
    """
    key = api_key or os.getenv("GROQ_API_KEY", "")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")

    user_message = _build_user_message(steps, rules_per_step, safety_categories, video_title)

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SAFETY_ANALYSIS_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
        "stream": False,
        "seed": 42,
    }

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GROQ_API_URL,
            json=request_body,
            headers=headers,
            timeout=120.0,
        )

        if resp.status_code != 200:
            body = resp.text[:500]
            if resp.status_code == 401:
                raise Exception("Invalid Groq API key.")
            elif resp.status_code == 429:
                raise Exception("Groq rate limit exceeded. Wait a moment and try again.")
            elif resp.status_code == 503:
                raise Exception("Groq service temporarily unavailable.")
            else:
                raise Exception(f"Groq API error (HTTP {resp.status_code}): {body}")

        data = resp.json()
        raw_content = data["choices"][0]["message"]["content"] or ""

    if not raw_content.strip():
        raise Exception("Groq returned empty safety analysis response.")

    cleaned = _clean_json_response(raw_content)
    report = json.loads(cleaned)

    if not isinstance(report, dict):
        raise Exception(f"Expected JSON object, got: {type(report).__name__}")

    # Ensure all expected fields exist with defaults
    report.setdefault("verdict", "UNSAFE")
    report.setdefault("overall_risk_score", 3.0)
    report.setdefault("parent_monitoring_required", True)
    report.setdefault("parent_monitoring_reason", "")
    report.setdefault("summary", "")
    report.setdefault("critical_concerns", [])
    report.setdefault("step_safety_analysis", [])
    report.setdefault("safety_measures_in_video", [])
    report.setdefault("recommended_additional_measures", [])

    logger.info(
        "Safety analysis complete: verdict=%s, risk=%.1f, steps=%d",
        report["verdict"],
        report["overall_risk_score"],
        len(report["step_safety_analysis"]),
    )

    return report
