"""Optional Claude-written explanation of the closure, plus code mapping.

The model only ever sees the computed numbers in `summary_dict` and is told
to quote them, never to compute anything.  If no API key is configured the
app falls back to a template so it works fully offline.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .codes import LIBRARY

MODEL = "claude-haiku-5-5"
API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM = (
    "You are a licensed land surveyor reviewing a traverse closure report for a surveying student. "
    "You are given a JSON summary of a closed loop traverse that software already computed. Explain in "
    "plain English whether the traverse is good enough to use and why. Rules: quote numbers exactly as "
    "given in the JSON and never compute, round differently, or invent values; name the precision and the "
    "required precision; if there is a blunder finding, explain what it points at and the most likely field "
    "mistake (misread degree, wrong backsight, transposed digits, dropped tape length, wrong prism or target "
    "height), and say what to reobserve; if the least squares chi-square test fails, say what that means; "
    "keep it under 200 words, two or three short paragraphs, no headings, no bullet points, no em dashes."
)

CODE_SYSTEM = (
    "You map surveyor field codes to a code library. Reply with only a JSON object whose keys are the unknown "
    "codes and whose values are the best library code, or null if none fits. Library: "
    + json.dumps({k: v[1] for k, v in LIBRARY.items()})
)


def api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or _settings_key()


def _settings_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "TraverseDoctor", "settings.json")


def _settings_key() -> str | None:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            return json.load(f).get("anthropic_api_key") or None
    except (OSError, ValueError):
        return None


def save_api_key(key: str) -> None:
    path = _settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"anthropic_api_key": key.strip()}, f)


def template_narrative(summary: dict) -> str:
    u = summary["units"]
    parts = []
    first = (f"The {summary['stations']}-station loop has a perimeter of {summary['perimeter']:g} {u}. ")
    if summary["angular_misclosure"] is not None:
        first += (f"The angular misclosure is {summary['angular_misclosure']} against an allowable of "
                  f"{summary['allowable_angular_misclosure']}, so each angle was corrected by "
                  f"{summary['angle_correction_each']}. ")
    first += (f"After balancing, the linear misclosure is {summary['linear_misclosure']:g} {u} toward "
              f"{summary['misclosure_direction']}, a precision of {summary['precision']} against the required "
              f"{summary['required_precision']}.")
    parts.append(first)
    ls = summary["least_squares"]
    second = (f"The least squares adjustment has {ls['redundancy']} redundant observations and a reference "
              f"variance of {ls['reference_variance']:g}, which "
              f"{'passes' if ls['chi_square_passes'] else 'fails'} the chi-square test. ")
    if ls["flagged_observations"]:
        flagged = ls["flagged_observations"]
        more = f" and {len(flagged) - 3} more" if len(flagged) > 3 else ""
        second += "Largest standardized residuals: " + ", ".join(flagged[:3]) + more + ". "
    second += (f"Coordinates in this report come from the {summary['coordinates_from'].lower()} adjustment, "
               f"and the area is {summary['area']}.")
    parts.append(second)
    b = summary["blunder_finding"]
    verdict = "meets" if summary["meets_requirements"] else "does not meet"
    if b["kind"] == "none":
        parts.append(f"The traverse {verdict} the requirements and no blunder was found.")
    else:
        parts.append(f"The traverse {verdict} the requirements. {b['headline']} {b['detail']}")
    return "\n\n".join(parts)


def _post(system: str, user: str, key: str, timeout: float, max_tokens: int = 600) -> str | None:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        API_URL, data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        text = "".join(block.get("text", "") for block in data.get("content", []))
        return text.strip() or None
    except (urllib.error.URLError, ValueError, KeyError, OSError):
        return None


def write_narrative(summary: dict, timeout: float = 30.0) -> tuple[str, str]:
    """Return (narrative, source) where source is 'claude' or 'template'."""
    key = api_key()
    if key:
        text = _post(SYSTEM, "Traverse summary:\n" + json.dumps(summary, indent=1), key, timeout)
        if text:
            return text, "claude"
    return template_narrative(summary), "template"


def map_codes_with_claude(codes: list[str], timeout: float = 20.0) -> dict[str, str | None] | None:
    """Ask Claude to map unknown field codes onto the library.  None if unavailable."""
    key = api_key()
    if not key or not codes:
        return None
    text = _post(CODE_SYSTEM, "Unknown codes: " + ", ".join(codes), key, timeout, 300)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    try:
        raw = json.loads(m.group(0)) if m else {}
    except ValueError:
        return None
    return {c: (raw.get(c) if raw.get(c) in LIBRARY else None) for c in codes}
