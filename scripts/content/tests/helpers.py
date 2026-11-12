"""Temporary episode layouts for content-validator tests; never write into data/."""

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

CONTENT_DIR = Path(__file__).resolve().parents[1]
if str(CONTENT_DIR) not in sys.path:
    sys.path.insert(0, str(CONTENT_DIR))

import validate_episode_content as validator  # noqa: E402

GUID = "647da4c6-dfa6-456b-af4a-dcda8aa82095"
# Verbatim first 40 cues of the real Ch05-12 feed cleaned.json (source_sha256 kept).
CLEANED = Path(__file__).parent / "fixtures" / "ch05-12-cleaned-first40.json"
SHA256 = "43edac682888872bf6049dd2233ecf32b73f7d8a821ede677d6fa55384d74a75"

PROVENANCE = {
    "schema": "feed-transcript/v1",
    "guid": GUID,
    "title": "Ch05-12-Shrimad Bhagavad Gita",
    "description": "Shrimad Bhagavad Gita Chapter 05 verses 18&19",
    "sha256": SHA256,
    "cue_count": 40,
    "review_status": "unreviewed",
    "time_base": "podcast audio time",
}

# A hand-made, spec-valid content file over the 40-cue fixture. Test data only.
VALID = {
    "schema": "episode-content/v1",
    "guid": GUID,
    "title": "Ch05-12-Shrimad Bhagavad Gita",
    "source": {"transcript": "feed", "sha256": SHA256, "review_status": "unreviewed",
               "time_base": "podcast audio time"},
    "uploader_claim": {"text": "Shrimad Bhagavad Gita Chapter 05 verses 18&19",
                       "verified": False},
    "summary": {
        "text": "After a welcome and invocation, the teacher takes up a much-cited line "
                "and presents equal seeing as the outward sign of one settled in Brahman.",
        "cue_ranges": [[1, 20], [21, 40]],
    },
    "segments": [
        {
            "id": "s01",
            "heading": "Welcome and invocation",
            "cue_range": [1, 20],
            "shloka_refs": [],
            "blocks": [
                {"kind": "paraphrase",
                 "text": "The host greets listeners, mentions recordings on other platforms "
                         "and a companion book, then hands over to the teacher.",
                 "cue_range": [1, 17]},
                {"kind": "quote", "text": "Let me do my invocations.", "cue_range": [18, 18]},
            ],
        },
        {
            "id": "s02",
            "heading": "Equal vision as the mark of the wise",
            "cue_range": [21, 40],
            "shloka_refs": [
                {"ref": "BG 5.18", "basis": "uploader-claim-only"},
                {"ref": "BG 5.17", "basis": "stated-in-transcript", "cue_range": [29, 30]},
            ],
            "blocks": [
                # Verbatim quote straddling the cue 23/24 boundary.
                {"kind": "quote",
                 "text": "a very famous verse often quoted from Bhagavad Gita",
                 "cue_range": [23, 24]},
                {"kind": "paraphrase",
                 "text": "Critics, the teacher says, misread this well-known line; he treats "
                         "same-sightedness as the visible sign of a person settled in Brahman.",
                 "cue_range": [25, 36]},
                {"kind": "inferred",
                 "text": "This sign appears to complete the portrait begun just before.",
                 "cue_range": [29, 35]},
                {"kind": "unresolved",
                 "text": "The recited Sanskrit at the opening of this stretch is unclear.",
                 "cue_range": [21, 23]},
            ],
        },
    ],
    "concepts": [
        {"id": "c-samadarshana", "label": "Samadharshana", "gloss": "equal vision",
         "cue_range": [28, 28]},
        {"id": "c-jeevan-mukta", "label": "Jeevan Mukta", "gloss": None,
         "cue_range": [34, 34]},
    ],
    "diagram": {"mermaid": "flowchart TD\n"
                           "  A[Welcome and invocation] --> B[Verse recited]\n"
                           "  B --> C(Critics misread it)\n"
                           "  C --> D{Equal vision}\n"
                           "  D --> E[Sign of the settled sage]\n"
                           "  E -->|builds on| F[Link to the earlier verse]\n"},
    "gaps": [{"cue_range": [21, 21], "note": "Two-word fragment over a long pause."}],
}


class ContentTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.episode = self.root / "data" / "episodes" / GUID
        feed = self.episode / "feed"
        feed.mkdir(parents=True)
        (feed / "cleaned.json").write_bytes(CLEANED.read_bytes())
        self.provenance = copy.deepcopy(PROVENANCE)
        self.write(feed / "provenance.json", self.provenance)
        self.content = copy.deepcopy(VALID)

    @staticmethod
    def write(path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def run_main(self, *extra, content=True):
        if content:
            self.write(self.episode / "content.json", self.content)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = validator.main(["--root", str(self.root), *extra])
        return code, out.getvalue()

    def assertFails(self, *reasons):
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{GUID}: FAIL", out)
        for reason in reasons:
            self.assertIn(reason, out)
        self.assertTrue(out.rstrip().splitlines()[-1].startswith("episode-content: FAIL"),
                        out)
        return out
