"""Temporary feed layouts for tests; never write into the repository's data/."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[3]
SAMPLE = Path(__file__).parent / "fixtures" / "ch05-12-sample.srt"
GUID = "647da4c6-dfa6-456b-af4a-dcda8aa82095"
# The fixture is a truncated real feed SRT: the first 40 Ch05-12 cues, verbatim.
SAMPLE_SHA256 = "61b73fa9c77afb7c1d600e743f4bd714bb8c46d8369ca3f2921a79c70d8447cf"


class FeedTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.feed = self.root / "data" / "episodes" / GUID / "feed"
        self.feed.mkdir(parents=True)
        self.srt = self.feed / "transcript.srt"
        self.raw = SAMPLE.read_bytes()
        self.srt.write_bytes(self.raw)
        self.provenance = {
            "schema": "feed-transcript/v1",
            "guid": GUID,
            "title": "Ch05-12",
            "pubDate": "test fixture",
            "duration": "test fixture",
            "transcript_url": "https://example.invalid/transcript.srt",
            "fetched_at": "test fixture",
            "http_status": 200,
            "bytes": len(self.raw),
            "sha256": hashlib.sha256(self.raw).hexdigest(),
            "cue_count": 40,
            "first_cue_start": "00:00:00,360",
            "last_cue_end": "00:04:54,280",
            "generation_method": "unstated by feed",
            "source_label": "test fixture truncated from a real feed SRT",
            "review_status": "unreviewed",
            "youtube_alignment": "none claimed",
            "time_base": "podcast audio time",
        }
        self.save_provenance()

    def save_provenance(self):
        (self.feed / "provenance.json").write_text(
            json.dumps(self.provenance), encoding="utf-8",
        )
