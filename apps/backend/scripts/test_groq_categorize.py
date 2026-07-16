#!/usr/bin/env python
"""
Quick smoke-test for Groq-based categorization.
Runs batch_categorize against fake Event-like objects so no DB needed.

Usage:
  GROQ_API_KEY=gsk_... python scripts/test_groq_categorize.py
"""

import os
import sys
import pathlib
import types
import json

# ── Make sure we can import events.ai_categories ──────────────────────────────
BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
django.setup()

from events.ai_categories import batch_categorize, CANONICAL_CATEGORIES

# ── Fake event objects (no DB hit) ────────────────────────────────────────────
def fake_event(pk, name, category="", description=""):
    e = types.SimpleNamespace()
    e.pk = pk
    e.name = name
    e.category = category
    e.description = description
    return e

EVENTS = [
    fake_event(1,  "CDO Fun Run 5K",         category="5K, 10K Run"),
    fake_event(2,  "Cebu 21K Half Marathon",  category="Running"),
    fake_event(3,  "Iron Man Triathlon 2026", category="Triathlon"),
    fake_event(4,  "Ben&Ben Live in Manila",  category="Concert"),
    fake_event(5,  "Sinulog Festival 2026",   category="Festival, Culture"),
    fake_event(6,  "AWS Summit Manila",       category="Tech Conference"),
    fake_event(7,  "Barista Workshop CDO",    category="Workshop"),
    fake_event(8,  "Streetfood Fair Davao",   category="Food"),
    fake_event(9,  "Community Charity Run",   category="Charity"),
    fake_event(10, "Mystery Event XYZ",       category="",
               description=""),                          # should fall back to Other
    fake_event(11, "Ayala Mall Grand Opening",category=""),  # ambiguous
    fake_event(12, "Mount Apo Trail Assault", category="Outdoor"),
]

# ── Run ────────────────────────────────────────────────────────────────────────
print(f"\nGroq model : {os.environ.get('GROQ_CATEGORIZE_MODEL', 'llama-3.1-8b-instant')}")
print(f"Events     : {len(EVENTS)}")
print("─" * 60)

try:
    results = batch_categorize(EVENTS)
except RuntimeError as e:
    print(f"\nERROR: {e}")
    sys.exit(1)

other_count = 0
for ev in EVENTS:
    labels = results.get(ev.pk, ["(missing)"])
    is_other = labels == ["Other"]
    if is_other:
        other_count += 1
    tag = "⚠ " if is_other else "  "
    print(f"{tag}[{ev.pk:2d}] {ev.name:<35} → {', '.join(labels)}")

print("─" * 60)
print(f"Other: {other_count}/{len(EVENTS)}  |  Canonical categories hit: {len(CANONICAL_CATEGORIES)}")
