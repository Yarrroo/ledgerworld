"""The recorded narration speaks to a finance lead without losing the demo's limits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.walkthrough_plan import build, srt

ROOT = Path(__file__).resolve().parents[2]
BEATS = build((ROOT / "docs/video-script.md").read_text(encoding="utf-8"))
VOICES = {beat["beat"]: beat["subtitle"] for beat in BEATS}


@pytest.mark.parametrize("beat", VOICES)
def test_voice_uses_plain_words_and_a_short_lead(beat):
    voice = VOICES[beat]
    jargon = r"\b(snapshot|branches?|cohorts?|checkpoints?|intents?|provenance|K_p|obs_hash|gateway)\b"
    assert not re.search(jargon, voice, re.IGNORECASE), (beat, voice)
    assert len(re.split(r"[.!?]", voice, maxsplit=1)[0].split()) <= 25
    assert "proves wiring" not in voice
    assert "different buckets" not in voice
    assert "scoped observation" not in voice
    for ambiguous in ("the others", "neither label", "This scripted test", "the actor"):
        assert ambiguous not in voice, (beat, ambiguous)


@pytest.mark.parametrize(("beat", "topics"), [
    ("State", ("payroll", "cash", "set aside")),
    ("World", ("lender", "borrowers", "risk")),
    ("Shock", ("payment", "late", "news")),
    ("Fork", ("plan", "payroll", "safety minimum", "fee")),
    ("Break", ("bill", "safety minimum", "contact")),
    ("Execute", ("moved", "books", "approved")),
    ("Explain", ("cash", "figures", "results")),
])
def test_each_beat_answers_a_finance_question(beat, topics):
    for topic in topics:
        assert topic in VOICES[beat].lower(), (beat, topic)


@pytest.mark.parametrize(("beat", "disclosures"), [
    ("State", ("made-up", "nothing moves", "approve and send")),
    ("World", ("own information", "public news", "scripts", "model")),
    ("Shock", ("scripted test", "not a model's own choices", "not why")),
    ("Fork", ("respond again", "new what-if", "replay", "live model", "simulated or sandbox",
              "does not approve")),
    ("Break", ("first bill", "never lowers")),
    ("Execute", ("earlier approved plan", "not a new payment", "simulated bank connection",
                 "sandbox bank", "mode a", "mode b", "advance inflow (sandbox simulation)",
                 "not a lender disbursement", "repayment", "simulated", "pending", "unknown",
                 "neither means the money has arrived")),
    ("Explain", ("could see", "cannot move money", "source code", "limitations")),
])
def test_honesty_is_spoken_not_only_left_in_the_shot_notes(beat, disclosures):
    for disclosure in disclosures:
        assert disclosure in VOICES[beat].lower(), (beat, disclosure)


def test_recording_consumers_get_the_same_seven_rewritten_lines():
    assert [(b["beat"], b["start"], b["end"]) for b in BEATS] == [
        ("State", 0, 15), ("World", 15, 25), ("Shock", 25, 40), ("Fork", 40, 95),
        ("Break", 95, 120), ("Execute", 120, 235), ("Explain", 235, 275),
    ]
    subtitles = srt(BEATS)
    for beat in BEATS:
        assert f"[{beat['beat']}] {VOICES[beat['beat']]}" in subtitles
