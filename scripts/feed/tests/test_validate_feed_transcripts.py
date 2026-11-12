import hashlib
import json
import os
import subprocess
import sys
import unittest

from scripts.feed import validate_feed_transcripts as validator
from scripts.feed.tests.helpers import FeedTestCase, GUID, REPO, SAMPLE, SAMPLE_SHA256


class ParseSrtTests(unittest.TestCase):
    def test_real_truncated_fixture(self):
        raw = SAMPLE.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), SAMPLE_SHA256)
        cues = validator.parse_srt(raw)
        self.assertEqual(len(cues), 40)
        self.assertEqual([cue["i"] for cue in cues], list(range(1, 41)))
        self.assertEqual(cues[0]["start"], 0.36)
        self.assertEqual(cues[-1]["end"], 294.28)
        self.assertEqual(cues[0]["text"], "Namaste everyone. \nWelcome to Advaita Vedata ")

    def test_bom_and_windows_line_endings(self):
        raw = b"\xef\xbb\xbf" + SAMPLE.read_bytes().replace(b"\n", b"\r\n")
        self.assertEqual(len(validator.parse_srt(raw)), 40)

    def test_repeated_blank_lines(self):
        raw = SAMPLE.read_bytes().replace(b"\n\n", b"\n \n\n")
        self.assertEqual(len(validator.parse_srt(raw)), 40)

    def test_empty_and_malformed_inputs(self):
        for raw in (b"", b" \n\t", b"1", b"1\n00:00:00,360 --> 00:00:03,800",
                    b"1\nnot timing\nNamaste everyone.", b"\xff"):
            with self.subTest(raw=raw), self.assertRaises((ValueError, UnicodeError)):
                validator.parse_srt(raw)

    def test_empty_cue_text(self):
        raw = (b"1\n00:00:00,360 --> 00:00:03,800\n   \n\n"
               b"2\n00:00:03,800 --> 00:00:07,280\nSatsang house.\n")
        with self.assertRaisesRegex(ValueError, "text"):
            validator.parse_srt(raw)

    def test_indices_must_start_at_one_and_be_sequential(self):
        raw = SAMPLE.read_bytes()
        for bad in (b"0" + raw[1:], raw.replace(b"\n2\n", b"\n3\n", 1),
                    raw.replace(b"\n2\n", b"\n1\n", 1),
                    raw.replace(b"\n2\n", b"\n-2\n", 1)):
            with self.subTest(raw=bad[:120]), self.assertRaises(ValueError):
                validator.parse_srt(bad)

    def test_equal_and_reversed_times_rejected(self):
        raw = SAMPLE.read_bytes()
        for end in (b"00:00:00,360", b"00:00:00,000"):
            bad = raw.replace(b"00:00:03,800", end, 1)
            with self.subTest(end=end), self.assertRaisesRegex(ValueError, "start"):
                validator.parse_srt(bad)

    def test_handmade_non_monotonic_case(self):
        raw = (b"1\n00:00:03,800 --> 00:00:07,280\nSatsang house.\n\n"
               b"2\n00:00:00,360 --> 00:00:03,800\nNamaste everyone.\n")
        with self.assertRaisesRegex(ValueError, "not monotonic"):
            validator.parse_srt(raw)

    def test_equal_starts_and_overlapping_cues_allowed(self):
        raw = SAMPLE.read_bytes().replace(
            b"00:00:03,800 --> 00:00:07,280",
            b"00:00:00,360 --> 00:00:07,280", 1,
        )
        self.assertEqual(len(validator.parse_srt(raw)), 40)

    def test_invalid_timestamps(self):
        for timestamp in ("00:60:00,000", "00:00:60,000", "00:00:01.000",
                          "0:00:01,000", "-1:00:01,000", "00:00:01,00"):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                validator.timestamp_seconds(timestamp)

    def test_hour_conversion(self):
        self.assertEqual(validator.timestamp_seconds("01:27:13,600"), 5233.6)


class ProvenanceTests(FeedTestCase):
    def test_valid_fixture_provenance(self):
        self.assertEqual(validator.validate_episode(self.feed), 40)

    def test_numeric_boundary_seconds(self):
        self.provenance.update(first_cue_start=0.36, last_cue_end=294.28)
        self.save_provenance()
        self.assertEqual(validator.validate_episode(self.feed), 40)

    def test_handmade_bad_sha(self):
        self.provenance["sha256"] = "0" * 64
        self.save_provenance()
        with self.assertRaisesRegex(ValueError, "sha256"):
            validator.validate_episode(self.feed)

    def test_every_required_field_is_checked(self):
        original = self.provenance.copy()
        for field in validator.REQUIRED_FIELDS:
            with self.subTest(field=field):
                self.provenance = original.copy()
                del self.provenance[field]
                self.save_provenance()
                with self.assertRaisesRegex(ValueError, "missing provenance fields"):
                    validator.validate_episode(self.feed)

    def test_mismatched_values(self):
        original = self.provenance.copy()
        cases = (
            ("schema", "wrong"), ("guid", "wrong"), ("review_status", "reviewed"),
            ("bytes", len(self.raw) + 1), ("cue_count", 39), ("cue_count", 40.0),
            ("first_cue_start", 1), ("last_cue_end", "00:04:54,281"),
            ("first_cue_start", "not a timestamp"), ("first_cue_start", False),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                self.provenance = dict(original, **{field: value})
                self.save_provenance()
                with self.assertRaises(ValueError):
                    validator.validate_episode(self.feed)

    def test_invalid_provenance_documents(self):
        for value in ([], None, "not an object"):
            (self.feed / "provenance.json").write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "JSON object"):
                validator.validate_episode(self.feed)

    def test_raw_mutation_invalidates_digest(self):
        self.srt.write_bytes(self.raw + b"\n")
        with self.assertRaisesRegex(ValueError, "sha256"):
            validator.validate_episode(self.feed)


class ValidatorCliTests(FeedTestCase):
    def run_validator(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(REPO / "scripts/feed/validate_feed_transcripts.py"),
             "--root", str(self.root), *args],
            cwd=cwd or REPO, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True, text=True, check=False,
        )

    def test_success_and_expected_count(self):
        result = self.run_validator("--expect", "1", cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"{GUID}: OK cues=40", result.stdout)
        self.assertTrue(result.stdout.endswith("feed-transcripts: OK n=1\n"))

    def test_expected_count_mismatch(self):
        result = self.run_validator("--expect", "48")
        self.assertEqual(result.returncode, 1)
        self.assertIn("expected n=48, found n=1", result.stdout)
        self.assertNotIn("feed-transcripts: OK", result.stdout)

    def test_missing_root(self):
        result = self.run_validator("--root", str(self.root / "missing"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing episodes directory", result.stdout)

    def test_empty_dataset_cannot_satisfy_positive_expectation(self):
        empty = self.root / "empty" / "data" / "episodes"
        empty.mkdir(parents=True)
        result = self.run_validator("--root", str(empty.parents[1]), "--expect", "48")
        self.assertEqual(result.returncode, 1)
        self.assertIn("found n=0", result.stdout)

    def test_invalid_files_are_reported_without_tracebacks(self):
        for filename, content in (("provenance.json", b"{"),
                                  ("provenance.json", b"\xff"),
                                  ("transcript.srt", b"not SRT")):
            with self.subTest(filename=filename, content=content):
                self.srt.write_bytes(self.raw)
                self.save_provenance()
                (self.feed / filename).write_bytes(content)
                result = self.run_validator()
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"{GUID}: FAIL", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_incomplete_episode_does_not_stop_other_episodes(self):
        incomplete = self.feed.parents[1] / "aaa-incomplete" / "feed"
        incomplete.mkdir(parents=True)
        result = self.run_validator("--expect", "2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("aaa-incomplete: FAIL", result.stdout)
        self.assertIn(f"{GUID}: OK cues=40", result.stdout)

    def test_episode_output_order_is_stable(self):
        other = self.feed.parents[1] / "000-first" / "feed"
        other.mkdir(parents=True)
        (other / "transcript.srt").write_bytes(self.raw)
        (other / "provenance.json").write_text(
            json.dumps(dict(self.provenance, guid="000-first")), encoding="utf-8",
        )
        result = self.run_validator("--expect", "2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("000-first: OK cues=40\n"))


if __name__ == "__main__":
    unittest.main()
