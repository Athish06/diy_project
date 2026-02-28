"""
Groq API streaming client for DIY step extraction.

Port of src-tauri/src/groq.rs — same system prompt, same streaming SSE logic.
Returns extracted steps as JSON, yields SSE events.
"""

import json
from typing import AsyncGenerator

import httpx

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

STEP_EXTRACTION_PROMPT = r"""You are an expert DIY Procedure and Safety Information Extractor.
Your task is to analyze the provided DIY tutorial information (video title, description, and transcript)
and extract structured, ordered procedural steps, materials, tools, safety precautions, and categories.
This output will be used for safety rule matching, so accuracy, ordering, and completeness are critical.

CRITICAL: Your response must be ONLY valid JSON. No markdown, no code fences, no explanation text before or after. Just the raw JSON object.

DIY DETECTION (MUST CHECK FIRST):
Determine if this video is actually a DIY tutorial/how-to/craft/building/repair project.
- If YES: set "is_diy" to true and extract all fields below.
- If NO (e.g. vlogs, reviews, unboxings, morning routines, gaming, commentary):
  set "is_diy" to false and return EMPTY arrays for all fields.
A video is DIY if the creator demonstrates making, building, repairing, crafting, or modifying something with their hands.

CRITICAL GROUNDING RULES (MUST FOLLOW)

- ALL extracted steps, tools, materials, and safety precautions MUST be explicitly supported by the provided transcript.
- If a step, tool, material, or safety precaution is NOT present in the transcript, it MUST NOT appear in the output.
- If the transcript content does NOT clearly describe a DIY procedure, set is_diy to false and return empty arrays.
- Do NOT invent steps, tools, or materials. Do NOT add safety advice that is not mentioned.

SAFETY CATEGORY CLASSIFICATION (MANDATORY):
Based on the DIY procedure's tools, materials, and actions, classify it into one or more of these
EXACT predefined safety categories. Use ONLY these exact category names:
  electrical, chemical, woodworking, power_tools, heat_fire, mechanical,
  PPE_required, child_safety, toxic_exposure, ventilation, structural, general_safety

Assign ALL categories that clearly apply. If none specifically apply, use "general_safety".
Examples:
- Working with isopropyl alcohol → chemical
- Using a circular saw → power_tools, woodworking
- Soldering wires → electrical, heat_fire
- Craft project with glue and glitter → general_safety, child_safety (if involving children)

CORE EXTRACTION RULES

1. Procedural Reconstruction
   You may reconstruct procedural steps by combining adjacent or sequential transcript phrases that clearly describe the same action.
   You must NOT invent new actions, tools, or materials.
   You may add minimal connective verbs only if the action is clearly implied by the transcript sequence.

2. What Counts as a Step
   A step is a single coherent action performed by the creator.
   Do NOT include greetings, intro phrases, outro phrases, commentary, or filler speech as steps.
   Steps must start only when the creator performs an actionable task.
   Do not include recommendations, opinions, or explanations in steps — only procedural actions.

3. Step Ordering (MANDATORY)
   Steps must be strictly ordered in the sequence they occur in the transcript.
   Do not repeat the same action as separate steps unless it clearly occurs again later.

4. Step Fields

   transcript_excerpt: Copy the exact words from the transcript that describe this step. Include the full sentence(s) the creator used, preserving their natural speech. This field is for verification — copy verbatim from transcript only.

   step_text: Write a clean 1-2 sentence instruction for the action. Remove filler words ("um", "like", "so"), greetings, commentary. Keep the creator's key verbs, measurements, temperatures, and technical terms. Do NOT copy raw transcript text directly — rewrite it into a clear instruction.

   action_summary: A very short (3-8 word) imperative phrase summarizing the action. Examples: "Prepare lye solution", "Mix oils and lye", "Pour into mold"

5. Materials and Tools (TOP-LEVEL)
   Extract only explicitly mentioned or clearly shown materials and tools.
   Do not infer brands, sizes, or quantities unless explicitly stated.
   Deduplicate items.

6. Safety Precautions (TOP-LEVEL)
   Safety precautions must be explicitly stated in transcript. Do NOT infer general safety guidelines from context.

7. Categories (diy_categories)
   Multiple categories are allowed. Assign all applicable free-text categories based on materials, tools, and actions.

8. Hallucination Prevention (MANDATORY)
   Before producing final output, verify:
   - Every step is supported by transcript wording
   - No filler or outro sentences are included
   - Steps contain clear actions
   - Ordering is logical and continuous
   If any discrepancy is found, return empty arrays rather than guessing.

OUTPUT FORMAT (STRICT JSON):
{
  "is_diy": true,
  "title": "<video title>",
  "diy_categories": ["<free-text category1>", "<category2>"],
  "safety_categories": ["<from predefined list ONLY: electrical, chemical, woodworking, power_tools, heat_fire, mechanical, PPE_required, child_safety, toxic_exposure, ventilation, structural, general_safety>"],
  "materials": ["<material1>", "<material2>"],
  "tools": ["<tool1>", "<tool2>"],
  "steps": [
    {
      "step_number": 1,
      "transcript_excerpt": "<exact words from transcript>",
      "step_text": "<clean 1-2 sentence instruction>",
      "action_summary": "<3-8 word imperative phrase>"
    }
  ],
  "safety_precautions": ["<precaution1>", "<precaution2>"],
  "target_audience": "adults / teens / children / family (only if mentioned)",
  "supervision_mentioned": false,
  "skill_level": "beginner / intermediate / advanced (only if mentioned)"
}

/no_think"""


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences and leading/trailing noise from JSON response."""
    trimmed = text.strip()

    # Strip ```json ... ``` or ``` ... ```
    if trimmed.startswith("```"):
        newline_pos = trimmed.find("\n")
        if newline_pos >= 0:
            after_fence = trimmed[newline_pos + 1 :]
        else:
            after_fence = trimmed.lstrip("`")
        stripped = after_fence.rstrip("`").strip()
    else:
        stripped = trimmed

    # Find JSON object boundaries first, then array
    obj_start = stripped.find("{")
    obj_end = stripped.rfind("}")
    if obj_start >= 0 and obj_end >= 0 and obj_end > obj_start:
        return stripped[obj_start : obj_end + 1]

    arr_start = stripped.find("[")
    arr_end = stripped.rfind("]")
    if arr_start >= 0 and arr_end >= 0 and arr_end > arr_start:
        return stripped[arr_start : arr_end + 1]

    return stripped


async def extract_steps_stream(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    transcript: str,
) -> AsyncGenerator[dict, None]:
    """
    Stream DIY step extraction from a transcript via Groq API.

    Yields SSE-style event dicts:
      {"type": "steps_delta", "text": "..."}
      {"type": "steps_complete", "steps_json": "..."}

    Raises on error.
    """
    user_message = (
        "Analyze this YouTube video transcript and extract all DIY procedure steps:\n\n"
        + transcript
    )

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": STEP_EXTRACTION_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.0,
        "max_tokens": 8192,
        "stream": True,
        "seed": 42,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with client.stream("POST", GROQ_API_URL, json=request_body, headers=headers, timeout=120.0) as response:
        status = response.status_code
        if status != 200:
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
                if len(body) > 500:
                    break
            if status == 401:
                raise Exception("Invalid Groq API key. Check your key in Settings.")
            elif status == 429:
                raise Exception("Groq rate limit exceeded. Wait a moment and try again.")
            elif status == 503:
                raise Exception("Groq service temporarily unavailable. Try again shortly.")
            else:
                raise Exception(f"Groq API error (HTTP {status}): {body[:500]}")

        full_text = ""
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line == "data: [DONE]":
                break
            if line.startswith("data: "):
                json_str = line[6:]
                try:
                    parsed = json.loads(json_str)
                    content = (
                        parsed.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                    if content:
                        full_text += content
                        yield {"type": "steps_delta", "text": content}
                except (json.JSONDecodeError, IndexError, KeyError):
                    pass

    if not full_text:
        raise Exception("Groq returned empty response. Try again.")

    cleaned = _clean_json_response(full_text)
    parsed = json.loads(cleaned)
    if not isinstance(parsed, (dict, list)):
        raise Exception(f"Expected JSON object or array, got: {cleaned[:100]}")

    extraction_json = json.dumps(parsed)
    yield {"type": "steps_complete", "steps_json": extraction_json}
