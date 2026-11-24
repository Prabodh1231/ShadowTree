"""Phase 1 experiment (feedback note 2): do single-field Needle tools return None less
often than the combined {title, summary, keywords} schema?

  backend\\.venv\\Scripts\\python.exe spikes\\needle_single_field.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import apply_env  # noqa: E402

apply_env()
import cactus  # noqa: E402
from app.ai_cactus import NEEDLE_SCHEMA  # noqa: E402

TEXTS = {
    "invoice": "Invoice INV-2041 from Northwind Supplies. Billed to billing@example.com, phone +1 555-0142. "
               "Items: 3 ergonomic chairs at $180 each, 1 standing desk at $420. Total due $960 by 15 December 2026.",
    "meeting": "Q3 roadmap sync. Attendees: Sam, Priya. Sam owns the API migration and the search redesign ships "
               "in October. Risks: hiring delays and unclear scope.",
    "journal": "Dear diary, today I walked by the lake with my dog and felt calm for the first time this week. "
               "I want to start painting again.",
    "pdf": "Rental agreement. The tenant pays 900 dollars rent monthly to the landlord.",
    "memo": "Please pay the electricity invoice of $64 before Friday.",
    "junk": "zzzz qqqq 1234",
}


def tool(name, prop, desc, kind="string"):
    typ = {"type": "array", "items": {"type": "string"}} if kind == "array" else {"type": "string"}
    return {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {prop: {**typ, "description": desc}}, "required": [prop]}}


def call(agent, text):
    r = agent.complete(text[:1500], max_new_tokens=160)
    calls = r.get("function_calls") or r.get("suppressed_calls") or []
    return calls[0]["arguments"] if calls else None


def main():
    combined = cactus.Cactus(tools=[NEEDLE_SCHEMA], auto_date=False, stateless=True)
    t_agent = cactus.Cactus(tools=[tool("get_title", "title", "Short title of the document")], auto_date=False, stateless=True)
    k_agent = cactus.Cactus(tools=[tool("get_keywords", "keywords", "Key topics of the document", "array")], auto_date=False, stateless=True)
    none_c = none_t = none_k = 0
    for name, text in TEXTS.items():
        c, t, k = call(combined, text), call(t_agent, text), call(k_agent, text)
        none_c += c is None
        none_t += t is None
        none_k += k is None
        print(f"{name:8} combined={c}\n{'':8} title_only={t}\n{'':8} keywords_only={k}")
    n = len(TEXTS)
    print(f"\nNone counts of {n}: combined={none_c}, title-only={none_t}, keywords-only={none_k}")
    for a in (combined, t_agent, k_agent):
        a.close()


if __name__ == "__main__":
    main()
