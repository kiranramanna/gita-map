import hashlib
import json
import os
import subprocess
import sys

from scripts.feed import clean_srt
from scripts.feed.tests.helpers import FeedTestCase, GUID, REPO


class CleanerTests(FeedTestCase):
    def test_output_schema_timing_order_and_verbatim_words(self):
        destination = clean_srt.clean(self.srt)
        document = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(set(document), {"schema", "guid", "source_sha256", "cues"})
        self.assertEqual(document["schema"], "feed-cleaned/v1")
        self.assertEqual(document["guid"], GUID)
        self.assertEqual(document["source_sha256"], hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(len(document["cues"]), 40)
        self.assertEqual(document["cues"][0], {
            "i": 1, "start": 0.36, "end": 3.8,
            "text": "Namaste everyone. Welcome to Advaita Vedata",
        })
        self.assertEqual(document["cues"][-1]["end"], 294.28)
        original_blocks = self.raw.decode("utf-8").strip().split("\n\n")
        for index, (cue, block) in enumerate(zip(document["cues"], original_blocks), 1):
            self.assertEqual(set(cue), {"i", "start", "end", "text"})
            self.assertEqual(cue["i"], index)
            self.assertEqual(cue["text"], " ".join(" ".join(block.splitlines()[2:]).split()))
        self.assertEqual(self.srt.read_bytes(), self.raw)

    def test_whitespace_only_even_with_unicode_spaces(self):
        # Unicode spaces are whitespace, not permission to correct transcript wording.
        raw = self.raw.replace(
            b"Namaste everyone. \nWelcome to Advaita Vedata ",
            " \tNamaste\u00a0everyone.  \n Welcome to Advaita Vedata \t".encode("utf-8"),
            1,
        )
        self.srt.write_bytes(raw)
        document = clean_srt.cleaned_document(self.srt)
        self.assertEqual(document["cues"][0]["text"],
                         "Namaste everyone. Welcome to Advaita Vedata")
        self.assertEqual(self.srt.read_bytes(), raw)

    def test_caption_markup_is_preserved(self):
        raw = self.raw.replace(b"Namaste everyone.", b"<i>Namaste everyone.</i>", 1)
        self.srt.write_bytes(raw)
        self.assertEqual(clean_srt.cleaned_document(self.srt)["cues"][0]["text"],
                         "<i>Namaste everyone.</i> Welcome to Advaita Vedata")

    def test_repeated_writes_are_identical(self):
        destination = clean_srt.clean(self.srt)
        first = destination.read_bytes()
        clean_srt.clean(self.srt)
        self.assertEqual(destination.read_bytes(), first)
        self.assertTrue(first.endswith(b"\n"))

    def test_check_matches_without_changing_either_file(self):
        destination = clean_srt.clean(self.srt)
        raw_stat, clean_stat = self.srt.stat(), destination.stat()
        self.assertEqual(clean_srt.clean(self.srt, check=True), destination)
        self.assertEqual(self.srt.stat().st_mtime_ns, raw_stat.st_mtime_ns)
        self.assertEqual(destination.stat().st_mtime_ns, clean_stat.st_mtime_ns)

    def test_check_ignores_json_formatting_and_key_order(self):
        destination = clean_srt.clean(self.srt)
        document = json.loads(destination.read_text(encoding="utf-8"))
        destination.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        clean_srt.clean(self.srt, check=True)

    def test_check_missing_output_writes_nothing(self):
        with self.assertRaises(FileNotFoundError):
            clean_srt.clean(self.srt, check=True)
        self.assertFalse((self.feed / "cleaned.json").exists())
        self.assertEqual(self.srt.read_bytes(), self.raw)

    def test_check_detects_all_document_and_cue_mutations(self):
        destination = clean_srt.clean(self.srt)
        original = destination.read_bytes()
        mutations = (
            lambda doc: doc.update(schema="wrong"),
            lambda doc: doc.update(guid="wrong"),
            lambda doc: doc.update(source_sha256="0" * 64),
            lambda doc: doc["cues"][0].update(text=""),
            lambda doc: doc["cues"][0].update(i=True),
            lambda doc: doc["cues"][0].update(start=0),
            lambda doc: doc["cues"][0].update(end=4),
            lambda doc: doc["cues"].reverse(),
            lambda doc: doc["cues"].pop(),
            lambda doc: doc.update(extra="unexpected"),
        )
        for mutate in mutations:
            document = json.loads(original)
            mutate(document)
            changed = json.dumps(document).encode("utf-8")
            destination.write_bytes(changed)
            with self.subTest(document=document), self.assertRaises(ValueError):
                clean_srt.clean(self.srt, check=True)
            self.assertEqual(destination.read_bytes(), changed)
            self.assertEqual(self.srt.read_bytes(), self.raw)

    def test_check_detects_raw_whitespace_change_from_digest(self):
        destination = clean_srt.clean(self.srt)
        original = destination.read_bytes()
        self.srt.write_bytes(self.raw + b"\n")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            clean_srt.clean(self.srt, check=True)
        self.assertEqual(destination.read_bytes(), original)

    def test_invalid_srt_does_not_clobber_existing_cleaned_file(self):
        destination = clean_srt.clean(self.srt)
        original = destination.read_bytes()
        self.srt.write_bytes(b"not SRT")
        with self.assertRaises(ValueError):
            clean_srt.clean(self.srt)
        self.assertEqual(destination.read_bytes(), original)

    def run_cleaner(self, *args):
        return subprocess.run(
            [sys.executable, str(REPO / "scripts/feed/clean_srt.py"), str(self.srt), *args],
            cwd=self.root, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            capture_output=True, text=True, check=False,
        )

    def test_cli_write_and_check_from_another_directory(self):
        for args in ((), ("--check",)):
            with self.subTest(args=args):
                result = self.run_cleaner(*args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("feed-cleaned: OK", result.stdout)
        self.assertEqual(self.srt.read_bytes(), self.raw)

    def test_cli_missing_cleaned_file(self):
        result = self.run_cleaner("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("feed-cleaned: FAIL", result.stderr)
        self.assertFalse((self.feed / "cleaned.json").exists())

    def test_cli_invalid_cleaned_json(self):
        for raw in (b"{", b"\xff", b"null", b"[]"):
            with self.subTest(raw=raw):
                (self.feed / "cleaned.json").write_bytes(raw)
                result = self.run_cleaner("--check")
                self.assertEqual(result.returncode, 1)
                self.assertIn("feed-cleaned: FAIL", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_cli_changed_source_fails_check(self):
        clean_srt.clean(self.srt)
        self.srt.write_bytes(self.raw.replace(b"00:00:00,360", b"00:00:00,361", 1))
        result = self.run_cleaner("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no longer matches", result.stderr)
