import json
import shutil

from helpers import CLEANED, GUID, SHA256, VALID, ContentTestCase, validator


class ValidContentTests(ContentTestCase):
    def test_fixture_is_verbatim_real_sample(self):
        cleaned = json.loads(CLEANED.read_text(encoding="utf-8"))
        self.assertEqual(cleaned["guid"], GUID)
        self.assertEqual(cleaned["source_sha256"], SHA256)
        self.assertEqual([c["i"] for c in cleaned["cues"]], list(range(1, 41)))
        self.assertEqual(cleaned["cues"][0]["text"], "Namaste everyone. Welcome to Advaita Vedata")

    def test_valid_file(self):
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertIn(f"{GUID}: OK segments=2 concepts=2", out)
        self.assertEqual(out.rstrip().splitlines()[-1], "episode-content: OK n=1")

    def test_no_content_files_is_ok_zero(self):
        code, out = self.run_main(content=False)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.strip(), "episode-content: OK n=0")

    def test_quote_whitespace_normalised(self):
        self.content["segments"][1]["blocks"][0]["text"] = (
            "  a very famous\n verse   often quoted from Bhagavad Gita ")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_range_shloka_ref_and_null_gloss(self):
        self.content["segments"][1]["shloka_refs"][0]["ref"] = "BG 5.18-19"
        code, out = self.run_main()
        self.assertEqual(code, 0, out)


class FlagTests(ContentTestCase):
    def test_derive(self):
        code, out = self.run_main("--derive")
        self.assertEqual(code, 0, out)
        self.assertIn(f"{GUID} s01 cues=1-20 start=0.360 end=84.040", out)
        self.assertIn(f"{GUID} s02 cues=21-40 start=110.720 end=294.280", out)

    def test_expect_match_and_mismatch(self):
        code, out = self.run_main("--expect", "1")
        self.assertEqual(code, 0, out)
        code, out = self.run_main("--expect", "2")
        self.assertEqual(code, 1, out)
        self.assertIn("episode-content: FAIL expected n=2, found n=1", out)

    def test_guid_selects_one(self):
        code, out = self.run_main("--guid", GUID)
        self.assertEqual(code, 0, out)
        self.assertTrue(out.rstrip().endswith("episode-content: OK n=1"))

    def test_guid_without_content_fails(self):
        code, out = self.run_main("--guid", GUID, content=False)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{GUID}: FAIL missing content.json", out)

    def test_unknown_guid_fails(self):
        code, out = self.run_main("--guid", "nope")
        self.assertEqual(code, 1, out)
        self.assertIn("nope: FAIL no episode directory", out)

    def test_one_failure_among_many(self):
        other = self.root / "data" / "episodes" / "other-guid"
        shutil.copytree(self.episode / "feed", other / "feed")
        # other-guid has no content.json yet, so it is skipped.
        code, out = self.run_main()
        self.assertEqual(code, 0, out)
        self.assertNotIn("other-guid", out)
        # With content.json its copied feed (wrong guid) must fail; GUID stays OK.
        self.write(other / "content.json", self.content)
        code, out = self.run_main()
        self.assertEqual(code, 1, out)
        self.assertIn(f"{GUID}: OK", out)
        self.assertIn("other-guid: FAIL provenance guid does not match", out)
        self.assertIn("episode-content: FAIL n=2 failures=1", out)


class QuoteTests(ContentTestCase):
    def test_quote_not_verbatim(self):
        self.content["segments"][0]["blocks"][1]["text"] = "Let me do my invocation."
        self.assertFails("segments[0].blocks[1].text: quote is not a verbatim substring")

    def test_quote_is_case_sensitive(self):
        self.content["segments"][0]["blocks"][1]["text"] = "let me do my invocations."
        self.assertFails("quote is not a verbatim substring")

    def test_quote_asr_text_not_fixed(self):
        # The cue says "the gender Gita"; correcting the ASR text is not verbatim.
        block = self.content["segments"][1]["blocks"][0]
        block["text"], block["cue_range"] = "the Bhagavad Gita, the Samadharshana", [28, 28]
        self.assertFails("quote is not a verbatim substring")

    def test_quote_outside_its_own_range(self):
        # Verbatim in the episode, but not inside the block's cue_range.
        self.content["segments"][1]["blocks"][0]["cue_range"] = [25, 26]
        self.assertFails("quote is not a verbatim substring of cues [25, 26]")

    def test_quote_over_25_words(self):
        block = self.content["segments"][1]["blocks"][0]
        block["cue_range"] = [23, 26]
        block["text"] = ("panda jab samadarshina. Now this verse is a very famous verse often "
                         "quoted from Bhagavad Gita by many people for different purposes. "
                         "The critics always have condemned such a statement")
        out = self.assertFails("segments[1].blocks[0].text: quote has 30 words (max 25)")
        self.assertNotIn("not a verbatim", out)


class ProseTests(ContentTestCase):
    def test_paraphrase_copies_eight_words_across_cue_boundary(self):
        self.content["segments"][1]["blocks"][1]["text"] = (
            "He notes this verse is a very famous verse often quoted, then moves on.")
        self.assertFails("segments[1].blocks[1].text: copies 8+ consecutive words",
                         "this verse is a very famous verse often")

    def test_copy_check_ignores_case_and_punctuation(self):
        self.content["segments"][1]["blocks"][2]["text"] = (
            "Equal Being; equal SEEING of Brahman, is the most disparate.")
        self.assertFails("segments[1].blocks[2].text: copies 8+ consecutive words")

    def test_seven_copied_words_allowed(self):
        self.content["segments"][1]["blocks"][1]["text"] = (
            "He notes this verse is a very famous one and moves on.")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_summary_and_gloss_copy_checked(self):
        self.content["summary"]["text"] = "Equal being, equal seeing of Brahman is the most."
        self.content["concepts"][0]["gloss"] = (
            "the equality in vision or the equal vision as a defining mark")
        self.assertFails("summary.text: copies", "concepts[0].gloss: copies")

    def test_word_limits(self):
        self.content["segments"][1]["blocks"][3]["text"] = " ".join(["word"] * 81)
        self.content["summary"]["text"] = " ".join(f"w{k}" for k in range(121))
        self.content["segments"][0]["heading"] = "one two three four five six seven eight nine ten eleven"
        self.assertFails("unresolved has 81 words (max 80)", "summary has 121 words (max 120)",
                         "heading has 11 words (max 10)")

    def test_bad_block_kind(self):
        self.content["segments"][0]["blocks"][0]["kind"] = "summary"
        self.assertFails("segments[0].blocks[0].kind: must be one of")


class RangeTests(ContentTestCase):
    def test_cue_range_out_of_bounds(self):
        seg = self.content["segments"][1]
        seg["blocks"][1]["cue_range"] = [39, 41]
        self.assertFails("segments[1].blocks[1].cue_range: cue_range [39, 41] out of bounds")

    def test_cue_range_zero_and_reversed(self):
        self.content["gaps"][0]["cue_range"] = [0, 3]
        self.content["concepts"][0]["cue_range"] = [28, 27]
        self.assertFails("gaps[0].cue_range: cue_range [0, 3] out of bounds",
                         "concepts[0].cue_range: cue_range [28, 27] out of bounds")

    def test_cue_range_types(self):
        self.content["summary"]["cue_ranges"] = [[True, 3], [1.0, 2], [1, 2, 3]]
        out = self.assertFails("summary.cue_ranges[0]: cue_range must be [i, j]")
        self.assertIn("summary.cue_ranges[1]", out)
        self.assertIn("summary.cue_ranges[2]", out)

    def test_overlapping_segments(self):
        self.content["segments"][1]["cue_range"] = [20, 40]
        self.assertFails("segments[1].cue_range: [20, 40] overlaps or precedes")

    def test_descending_segments(self):
        self.content["segments"].reverse()
        self.assertFails("segments[1].cue_range: [1, 20] overlaps or precedes")

    def test_block_outside_segment(self):
        self.content["segments"][0]["blocks"][0]["cue_range"] = [18, 22]
        self.assertFails("segments[0].blocks[0].cue_range: cue_range [18, 22] outside "
                         "segment cue_range [1, 20]")


class ShlokaTests(ContentTestCase):
    def test_stated_ref_without_cue_range(self):
        del self.content["segments"][1]["shloka_refs"][1]["cue_range"]
        self.assertFails("segments[1].shloka_refs[1]: stated-in-transcript ref requires "
                         "cue_range")

    def test_ref_cue_range_may_precede_segment(self):
        # SPEC confines blocks, not shloka refs, to their segment.
        self.content["segments"][1]["shloka_refs"][1]["cue_range"] = [10, 30]
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_ref_cue_range_out_of_bounds(self):
        self.content["segments"][1]["shloka_refs"][1]["cue_range"] = [30, 41]
        self.assertFails("segments[1].shloka_refs[1].cue_range: cue_range [30, 41] out of "
                         "bounds")

    def test_bad_ref_formats(self):
        for ref in ("BG 5:18", "Gita 5.18", "BG 19.1", "BG 5.19-18", "BG 5.18-", "bg 5.18",
                    "BG 05.18", 518):
            with self.subTest(ref=ref):
                self.content["segments"][1]["shloka_refs"][0]["ref"] = ref
                self.assertFails("segments[1].shloka_refs[0].ref:")

    def test_bad_basis(self):
        self.content["segments"][1]["shloka_refs"][0]["basis"] = "guessed"
        self.assertFails("segments[1].shloka_refs[0].basis: must be one of")


class ProvenanceTests(ContentTestCase):
    def test_bad_sha(self):
        self.content["source"]["sha256"] = "0" * 64
        self.assertFails("source.sha256: does not equal provenance sha256")

    def test_cleaned_sha_mismatch(self):
        self.provenance["sha256"] = "f" * 64
        self.write(self.episode / "feed" / "provenance.json", self.provenance)
        self.assertFails("cleaned.json source_sha256 does not equal provenance sha256")

    def test_guid_mismatch(self):
        self.content["guid"] = "00a46f46-0c35-4944-a270-cf89bdab81e7"
        self.assertFails("guid: '00a46f46-0c35-4944-a270-cf89bdab81e7' does not match")

    def test_uploader_claim(self):
        self.content["uploader_claim"] = {"text": "Chapter 05 verses 18 and 19",
                                          "verified": 0}
        self.assertFails("uploader_claim.text: must equal the feed description verbatim",
                         "uploader_claim.verified: must be false")

    def test_source_fields(self):
        self.content["source"]["review_status"] = "reviewed"
        self.content["source"]["transcript"] = "youtube"
        self.assertFails("source.review_status: must be 'unreviewed'",
                         "source.transcript: must be 'feed'")

    def test_title_and_schema(self):
        self.content["title"] = "Other"
        self.content["schema"] = "episode-content/v2"
        self.assertFails("title: does not match provenance title", "schema: must be")

    def test_missing_and_unknown_keys(self):
        del self.content["gaps"]
        self.content["timestamps"] = []
        self.assertFails("content: missing keys gaps", "unknown keys timestamps")

    def test_unparseable_content(self):
        (self.episode / "content.json").write_text("{", encoding="utf-8")
        code, out = self.run_main("--guid", GUID, content=False)
        self.assertEqual(code, 1, out)
        self.assertIn(f"{GUID}: FAIL", out)


class IdTests(ContentTestCase):
    def test_bad_segment_id(self):
        self.content["segments"][0]["id"] = "S01"
        self.assertFails("segments[0].id: id 'S01' must match")

    def test_bad_concept_id(self):
        self.content["concepts"][0]["id"] = "samadarshana"
        self.assertFails("concepts[0].id: concept id 'samadarshana' must match")

    def test_non_ascii_concept_id(self):
        self.content["concepts"][0]["id"] = "c-samadarśana"
        self.assertFails("concepts[0].id: concept id")

    def test_duplicate_id(self):
        self.content["segments"][1]["id"] = "s01"
        self.assertFails("segments[1].id: duplicate id 's01'")

    def test_concept_label_must_appear_in_cues(self):
        self.content["concepts"][1]["label"] = "Jivanmukta"
        self.assertFails("concepts[1].label: 'Jivanmukta' does not appear in cues [34, 34]")


class DiagramTests(ContentTestCase):
    def test_too_few_nodes(self):
        self.content["diagram"]["mermaid"] = "flowchart TD\n A[One] --> B[Two]\n B --> C[Three]"
        self.assertFails("diagram.mermaid: has 3 nodes (need 5-12)")

    def test_too_many_nodes(self):
        lines = ["flowchart LR"] + [f"  N{k}[Step {k}] --> N{k + 1}[Step {k + 1}]"
                                    for k in range(12)]
        self.content["diagram"]["mermaid"] = "\n".join(lines)
        self.assertFails("diagram.mermaid: has 13 nodes (need 5-12)")

    def test_ignores_styling_lines_and_counts_ampersand(self):
        self.content["diagram"]["mermaid"] = (
            "flowchart TD\n"
            "  classDef key fill:#eee\n"
            "  subgraph Part1\n"
            "    A[Start]:::key --> B[Next] & C[Other]\n"
            "  end\n"
            "  B --> D[Then]; C --> D\n"
            "  D -.->|so| E[(Close)]\n"
            "  style A fill:#fff\n")
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_header_required(self):
        self.content["diagram"]["mermaid"] = self.content["diagram"]["mermaid"].replace(
            "flowchart TD", "graph TD")
        self.assertFails("diagram.mermaid: must start with 'flowchart TD'")

    def test_quote_wrapper_allowed(self):
        self.content["diagram"]["mermaid"] = self.content["diagram"]["mermaid"].replace(
            "A[Welcome and invocation]", 'A["Welcome: and invocation"]')
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_brackets_inside_quoted_label(self):
        self.content["diagram"]["mermaid"] = (
            VALID["diagram"]["mermaid"]
            .replace("A[Welcome and invocation]", 'A["Recap (ch 3"]')
            .replace("B[Verse recited]", 'B["Step 1) verse [recited]"]'))
        code, out = self.run_main()
        self.assertEqual(code, 0, out)

    def test_ascii_quotes_in_labels(self):
        for label in ('A[The "verse"]', 'A["The "verse""]', "A[Krishna's verse]",
                      "A --> |it's| B"):
            with self.subTest(label=label):
                self.content["diagram"]["mermaid"] = VALID["diagram"]["mermaid"].replace(
                    "A[Welcome and invocation]", label)
                self.assertFails("diagram.mermaid: label contains an ASCII quote")


if __name__ == "__main__":
    import unittest
    unittest.main()
