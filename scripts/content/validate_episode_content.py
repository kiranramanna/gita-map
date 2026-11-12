#!/usr/bin/env python3
"""Validate authored episode content (episode-content/v1) against its feed transcript.

Usage:
  python3 scripts/content/validate_episode_content.py [--root REPO] [--guid GUID]
                                                     [--expect N] [--derive]

Checks data/episodes/<guid>/content.json against data/episodes/<guid>/feed/cleaned.json
and data/episodes/<guid>/feed/provenance.json, enforcing scripts/content/SPEC.md.
Episodes without content.json are skipped (unless named with --guid, which then FAILs).
--expect N requires exactly N episodes with content.json (ignored with --guid).
--derive prints each segment's start/end seconds, derived from its first and last cue.
Prints one OK/FAIL line per episode; exits 1 on any failure; the final line on success
is "episode-content: OK n=<count>". Standard library only; never modifies files.
"""

import argparse
import json
from pathlib import Path
import re
import sys


SCHEMA = "episode-content/v1"
DEFAULT_ROOT = Path(__file__).resolve().parents[2]

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
CONCEPT_ID_RE = re.compile(r"^c-[a-z0-9]+(?:-[a-z0-9]+)*$")
SHLOKA_RE = re.compile(r"^BG ([1-9][0-9]*)\.([1-9][0-9]*)(?:-([1-9][0-9]*))?$")
BLOCK_KINDS = ("paraphrase", "quote", "inferred", "unresolved")
SHLOKA_BASES = ("stated-in-transcript", "uploader-claim-only")
MERMAID_HEADER_RE = re.compile(r"^flowchart\s+(TD|TB|BT|LR|RL)\s*$")
MERMAID_SKIP_RE = re.compile(
    r"^(subgraph|end|classDef|class|style|linkStyle|click|direction|%%)\b")
MERMAID_ARROW_RE = re.compile(r"<?[-=.]{2,}>?|[-=.]{2,}[ox](?=\s|$)|~~~")
MERMAID_ID_RE = re.compile(r"[A-Za-z0-9_]+")

QUOTE_MAX_WORDS = 25
PROSE_MAX_WORDS = 80
SUMMARY_MAX_WORDS = 120
HEADING_MAX_WORDS = 10
COPY_RUN_WORDS = 8
DIAGRAM_MIN_NODES = 5
DIAGRAM_MAX_NODES = 12


def normalise_ws(text):
    """Collapse all whitespace runs to one space (case and punctuation preserved)."""
    return " ".join(text.split())


def word_count(text):
    return len(text.split())


def copy_tokens(text):
    """Tokens for the copied-run check: lowercase, punctuation stripped."""
    return re.findall(r"[^\W_]+", text.lower())


class Transcript:
    """Cue texts from cleaned.json, addressed by 1-based cue index."""

    def __init__(self, cues):
        self.cues = cues
        self.count = len(cues)
        tokens = copy_tokens(" ".join(c["text"] for c in cues))
        self.ngrams = {tuple(tokens[k:k + COPY_RUN_WORDS])
                       for k in range(len(tokens) - COPY_RUN_WORDS + 1)}

    def joined(self, cue_range):
        i, j = cue_range
        return normalise_ws(" ".join(c["text"] for c in self.cues[i - 1:j]))

    def copied_run(self, text):
        """Return the first run of COPY_RUN_WORDS words copied from the cues, or None."""
        tokens = copy_tokens(text)
        for k in range(len(tokens) - COPY_RUN_WORDS + 1):
            gram = tuple(tokens[k:k + COPY_RUN_WORDS])
            if gram in self.ngrams:
                return " ".join(gram)
        return None


class Checker:
    def __init__(self, transcript):
        self.t = transcript
        self.errors = []

    def err(self, path, message):
        self.errors.append(f"{path}: {message}")

    def keys(self, obj, path, required, optional=()):
        if not isinstance(obj, dict):
            self.err(path, "must be an object")
            return False
        missing = [k for k in required if k not in obj]
        extra = sorted(set(obj) - set(required) - set(optional))
        if missing:
            self.err(path, "missing keys " + ", ".join(missing))
        if extra:
            self.err(path, "unknown keys " + ", ".join(extra))
        return not missing

    def text(self, value, path, allow_null=False):
        if allow_null and value is None:
            return False
        if not isinstance(value, str) or not value.strip():
            self.err(path, "must be a non-empty string" + (" or null" if allow_null else ""))
            return False
        return True

    def cue_range(self, value, path, within=None, within_label="segment"):
        """Validate [i, j] with 1 <= i <= j <= cue_count; optionally inside `within`."""
        if (not isinstance(value, list) or len(value) != 2
                or any(type(x) is not int for x in value)):
            self.err(path, "cue_range must be [i, j] with integer cue indices")
            return False
        i, j = value
        if not 1 <= i <= j <= self.t.count:
            self.err(path, f"cue_range {value} out of bounds (need 1 <= i <= j <= "
                           f"{self.t.count})")
            return False
        if within is not None and not within[0] <= i <= j <= within[1]:
            self.err(path, f"cue_range {value} outside {within_label} cue_range {within}")
            return False
        return True

    def words(self, text, path, limit, label):
        n = word_count(text)
        if n > limit:
            self.err(path, f"{label} has {n} words (max {limit})")

    def not_copied(self, text, path):
        run = self.t.copied_run(text)
        if run is not None:
            self.err(path, f"copies {COPY_RUN_WORDS}+ consecutive words from the cues: "
                           f"{run!r}")


def check_shloka_ref(ref):
    """Return an error string for a malformed 'BG <ch>.<verse>[-<verse>]', else None."""
    if not isinstance(ref, str):
        return "shloka ref must be a string"
    match = SHLOKA_RE.match(ref)
    if match is None:
        return f"shloka ref {ref!r} must look like 'BG 5.18' or 'BG 5.18-19'"
    chapter = int(match.group(1))
    if not 1 <= chapter <= 18:
        return f"shloka ref {ref!r} chapter must be 1..18"
    if match.group(3) is not None and int(match.group(3)) <= int(match.group(2)):
        return f"shloka ref {ref!r} range end must exceed its start"
    return None


def parse_mermaid(source):
    """Return (header, node_ids, quoted_labels, open_depth) for a Mermaid flowchart.

    Text inside [], (), {} (any nesting) is a label; |...| is an edge label.
    Node ids are the identifiers left on statement lines after removing labels,
    arrows and ':::class' suffixes; subgraph/end/classDef/class/style/linkStyle/
    click/direction/%% lines are not nodes. 'A -- text --> B' edge text is not
    supported (use 'A -->|text| B'). A label wrapped as ["..."] may use that outer
    pair of double quotes; any other ASCII ' or " in label text is reported.
    Brackets inside a "..." label do not nest. Node ids are [A-Za-z0-9_]+, so a
    hyphenated id such as step-1 is not supported.
    """
    outer, labels, depth, current, in_quote = [], [], 0, [], False
    for ch in source:
        if depth > 0 and ch == '"':
            in_quote = not in_quote
            current.append(ch)
        elif in_quote:
            current.append(ch)  # brackets inside a "..." label are plain text
        elif ch in "[({":
            if depth == 0:
                current = []
            else:
                current.append(ch)
            depth += 1
        elif ch in "])}" and depth > 0:
            depth -= 1
            if depth == 0:
                labels.append("".join(current))
                outer.append(" ")
            else:
                current.append(ch)
        elif depth > 0:
            current.append(ch)
        else:
            outer.append(ch)
    outer = "".join(outer)
    labels.extend(re.findall(r"\|([^|]*)\|", outer))
    outer = re.sub(r"\|[^|]*\|", " ", outer)
    statements = [s.strip() for s in re.split(r"[\n;]", outer)]
    statements = [s for s in statements if s]
    header = statements[0] if statements else ""
    nodes = []
    for statement in statements[1:]:
        if MERMAID_SKIP_RE.match(statement):
            continue
        statement = re.sub(r":::[A-Za-z0-9_-]+", " ", statement)
        statement = MERMAID_ARROW_RE.sub(" ", statement).replace("&", " ")
        for node in MERMAID_ID_RE.findall(statement):
            if node not in nodes:
                nodes.append(node)
    quoted = []
    for label in labels:
        inner = label.strip()
        if len(inner) >= 2 and inner[0] == inner[-1] == '"':
            inner = inner[1:-1]  # Mermaid's ["..."] wrapper is a delimiter, not label text
        if '"' in inner or "'" in inner:
            quoted.append(label)
    return header, nodes, quoted, depth


def validate_content(content, transcript, provenance, guid):
    """Return a list of error strings for one parsed content.json."""
    c = Checker(transcript)
    top = ("schema", "guid", "title", "source", "uploader_claim", "summary",
           "segments", "concepts", "diagram", "gaps")
    if not c.keys(content, "content", top):
        return c.errors
    if content["schema"] != SCHEMA:
        c.err("schema", f"must be {SCHEMA!r}")
    if content["guid"] != guid:
        c.err("guid", f"{content['guid']!r} does not match episode directory {guid!r}")
    if content["title"] != provenance.get("title"):
        c.err("title", "does not match provenance title")

    source = content["source"]
    if c.keys(source, "source", ("transcript", "sha256", "review_status", "time_base")):
        if source["sha256"] != provenance.get("sha256"):
            c.err("source.sha256", "does not equal provenance sha256")
        for key, want in (("transcript", "feed"), ("review_status", "unreviewed"),
                          ("time_base", "podcast audio time")):
            if source[key] != want:
                c.err(f"source.{key}", f"must be {want!r}")

    claim = content["uploader_claim"]
    if c.keys(claim, "uploader_claim", ("text", "verified")):
        if claim["text"] != provenance.get("description"):
            c.err("uploader_claim.text", "must equal the feed description verbatim")
        if claim["verified"] is not False:
            c.err("uploader_claim.verified", "must be false")

    summary = content["summary"]
    if c.keys(summary, "summary", ("text", "cue_ranges")):
        if c.text(summary["text"], "summary.text"):
            c.words(summary["text"], "summary.text", SUMMARY_MAX_WORDS, "summary")
            c.not_copied(summary["text"], "summary.text")
        ranges = summary["cue_ranges"]
        if not isinstance(ranges, list) or not ranges:
            c.err("summary.cue_ranges", "must be a non-empty list")
        else:
            for k, rng in enumerate(ranges):
                c.cue_range(rng, f"summary.cue_ranges[{k}]")

    seen_ids = {}

    def claim_id(value, path, pattern=ID_RE, what="id"):
        if not isinstance(value, str) or not pattern.match(value):
            c.err(path, f"{what} {value!r} must match {pattern.pattern}")
        elif value in seen_ids:
            c.err(path, f"duplicate id {value!r} (also {seen_ids[value]})")
        else:
            seen_ids[value] = path

    segments = content["segments"]
    if not isinstance(segments, list) or not segments:
        c.err("segments", "must be a non-empty list")
        segments = []
    previous = None
    for s, seg in enumerate(segments):
        sp = f"segments[{s}]"
        if not c.keys(seg, sp, ("id", "heading", "cue_range", "shloka_refs", "blocks")):
            continue
        claim_id(seg["id"], f"{sp}.id")
        if c.text(seg["heading"], f"{sp}.heading"):
            c.words(seg["heading"], f"{sp}.heading", HEADING_MAX_WORDS, "heading")
        seg_range = seg["cue_range"] if c.cue_range(seg["cue_range"], f"{sp}.cue_range") \
            else None
        if seg_range is not None:
            if previous is not None and seg_range[0] <= previous[1]:
                c.err(f"{sp}.cue_range", f"{seg_range} overlaps or precedes previous "
                                         f"segment {previous} (segments must be ascending "
                                         f"and non-overlapping)")
            previous = seg_range

        refs = seg["shloka_refs"]
        if not isinstance(refs, list):
            c.err(f"{sp}.shloka_refs", "must be a list")
            refs = []
        for r, ref in enumerate(refs):
            rp = f"{sp}.shloka_refs[{r}]"
            if not c.keys(ref, rp, ("ref", "basis"), ("cue_range",)):
                continue
            problem = check_shloka_ref(ref["ref"])
            if problem:
                c.err(f"{rp}.ref", problem)
            if ref["basis"] not in SHLOKA_BASES:
                c.err(f"{rp}.basis", f"must be one of {', '.join(SHLOKA_BASES)}")
            if "cue_range" in ref:
                # SPEC confines only blocks to their segment; a verse may be named
                # just before the segment that discusses it, so only bounds apply.
                c.cue_range(ref["cue_range"], f"{rp}.cue_range")
            elif ref["basis"] == "stated-in-transcript":
                c.err(rp, "stated-in-transcript ref requires cue_range")

        blocks = seg["blocks"]
        if not isinstance(blocks, list) or not blocks:
            c.err(f"{sp}.blocks", "must be a non-empty list")
            blocks = []
        for b, block in enumerate(blocks):
            bp = f"{sp}.blocks[{b}]"
            if not c.keys(block, bp, ("kind", "text", "cue_range")):
                continue
            kind = block["kind"]
            if kind not in BLOCK_KINDS:
                c.err(f"{bp}.kind", f"must be one of {', '.join(BLOCK_KINDS)}")
            ok_range = c.cue_range(block["cue_range"], f"{bp}.cue_range", seg_range)
            if not c.text(block["text"], f"{bp}.text"):
                continue
            text = block["text"]
            if kind == "quote":
                c.words(text, f"{bp}.text", QUOTE_MAX_WORDS, "quote")
                if ok_range and normalise_ws(text) not in transcript.joined(
                        block["cue_range"]):
                    c.err(f"{bp}.text", "quote is not a verbatim substring of cues "
                                        f"{block['cue_range']}")
            elif kind in BLOCK_KINDS:
                c.words(text, f"{bp}.text", PROSE_MAX_WORDS, kind)
                c.not_copied(text, f"{bp}.text")

    concepts = content["concepts"]
    if not isinstance(concepts, list):
        c.err("concepts", "must be a list")
        concepts = []
    for k, concept in enumerate(concepts):
        cp = f"concepts[{k}]"
        if not c.keys(concept, cp, ("id", "label", "gloss", "cue_range")):
            continue
        claim_id(concept["id"], f"{cp}.id", CONCEPT_ID_RE, "concept id")
        ok_range = c.cue_range(concept["cue_range"], f"{cp}.cue_range")
        if c.text(concept["label"], f"{cp}.label") and ok_range:
            label = normalise_ws(concept["label"]).lower()
            if label not in transcript.joined(concept["cue_range"]).lower():
                c.err(f"{cp}.label", f"{concept['label']!r} does not appear in cues "
                                     f"{concept['cue_range']}")
        if c.text(concept["gloss"], f"{cp}.gloss", allow_null=True):
            c.not_copied(concept["gloss"], f"{cp}.gloss")

    diagram = content["diagram"]
    if c.keys(diagram, "diagram", ("mermaid",)) and c.text(diagram["mermaid"],
                                                            "diagram.mermaid"):
        header, nodes, quoted, depth = parse_mermaid(diagram["mermaid"])
        if not MERMAID_HEADER_RE.match(header):
            c.err("diagram.mermaid", f"must start with 'flowchart TD' (or TB/BT/LR/RL), "
                                     f"got {header[:30]!r}")
        if depth:
            c.err("diagram.mermaid", "unbalanced label brackets")
        if not DIAGRAM_MIN_NODES <= len(nodes) <= DIAGRAM_MAX_NODES:
            c.err("diagram.mermaid", f"has {len(nodes)} nodes (need "
                                     f"{DIAGRAM_MIN_NODES}-{DIAGRAM_MAX_NODES})")
        if quoted:
            c.err("diagram.mermaid", f"label contains an ASCII quote: {quoted[0]!r}")

    gaps = content["gaps"]
    if not isinstance(gaps, list):
        c.err("gaps", "must be a list")
        gaps = []
    for k, gap in enumerate(gaps):
        gp = f"gaps[{k}]"
        if c.keys(gap, gp, ("cue_range", "note")):
            c.cue_range(gap["cue_range"], f"{gp}.cue_range")
            c.text(gap["note"], f"{gp}.note")
    return c.errors


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_transcript(feed_dir, guid):
    """Load and cross-check provenance.json and cleaned.json; return (provenance, Transcript)."""
    provenance = load_json(feed_dir / "provenance.json")
    if not isinstance(provenance, dict):
        raise ValueError("provenance.json must be a JSON object")
    if provenance.get("guid") != guid:
        raise ValueError("provenance guid does not match episode directory")
    cleaned = load_json(feed_dir / "cleaned.json")
    if not isinstance(cleaned, dict) or cleaned.get("schema") != "feed-cleaned/v1":
        raise ValueError("cleaned.json schema must be feed-cleaned/v1")
    if cleaned.get("guid") != guid:
        raise ValueError("cleaned.json guid does not match episode directory")
    if cleaned.get("source_sha256") != provenance.get("sha256"):
        raise ValueError("cleaned.json source_sha256 does not equal provenance sha256")
    cues = cleaned.get("cues")
    if not isinstance(cues, list) or not cues:
        raise ValueError("cleaned.json has no cues")
    for n, cue in enumerate(cues, 1):
        if (not isinstance(cue, dict) or cue.get("i") != n
                or not isinstance(cue.get("text"), str)
                or type(cue.get("start")) not in (int, float)
                or type(cue.get("end")) not in (int, float)):
            raise ValueError(f"cleaned.json cue {n} malformed or out of sequence")
    if "cue_count" in provenance and provenance["cue_count"] != len(cues):
        raise ValueError(f"cleaned.json has {len(cues)} cues but provenance cue_count is "
                         f"{provenance['cue_count']}")
    return provenance, Transcript(cues)


def derive_segments(content, transcript):
    """Yield (segment id, i, j, start seconds, end seconds) from cue times."""
    for seg in content["segments"]:
        i, j = seg["cue_range"]
        yield seg["id"], i, j, transcript.cues[i - 1]["start"], transcript.cues[j - 1]["end"]


def validate_episode(episode_dir):
    """Return (errors, content, transcript) for one episode directory."""
    guid = episode_dir.name
    try:
        provenance, transcript = load_transcript(episode_dir / "feed", guid)
        content = load_json(episode_dir / "content.json")
    except (OSError, UnicodeError, ValueError) as exc:
        return [str(exc)], None, None
    return validate_content(content, transcript, provenance, guid), content, transcript


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                        help="repository root (default: this script's repository)")
    parser.add_argument("--guid", help="validate only this episode")
    parser.add_argument("--expect", type=int,
                        help="required number of episodes with content.json")
    parser.add_argument("--derive", action="store_true",
                        help="print derived per-segment start/end seconds")
    args = parser.parse_args(argv)
    if args.expect is not None and args.expect < 0:
        parser.error("--expect must be non-negative")
    episodes = args.root / "data" / "episodes"
    if not episodes.is_dir():
        print(f"episode-content: FAIL missing episodes directory: {episodes}")
        return 1
    failures = 0
    if args.guid is not None:
        target = episodes / args.guid
        if args.guid in ("", ".", "..") or "/" in args.guid or not target.is_dir():
            print(f"{args.guid}: FAIL no episode directory")
            print("episode-content: FAIL n=0 failures=1")
            return 1
        if not (target / "content.json").is_file():
            print(f"{args.guid}: FAIL missing content.json")
            print("episode-content: FAIL n=0 failures=1")
            return 1
        episode_dirs = [target]
    else:
        episode_dirs = sorted(p.parent for p in episodes.glob("*/content.json"))
    for episode_dir in episode_dirs:
        errors, content, transcript = validate_episode(episode_dir)
        if errors:
            failures += 1
            print(f"{episode_dir.name}: FAIL " + "; ".join(errors))
            continue
        if args.derive:
            for sid, i, j, start, end in derive_segments(content, transcript):
                print(f"{episode_dir.name} {sid} cues={i}-{j} start={start:.3f} "
                      f"end={end:.3f}")
        print(f"{episode_dir.name}: OK segments={len(content['segments'])} "
              f"concepts={len(content['concepts'])}")
    if args.expect is not None and args.guid is None and len(episode_dirs) != args.expect:
        failures += 1
        print(f"episode-content: FAIL expected n={args.expect}, found n={len(episode_dirs)}")
    if failures:
        print(f"episode-content: FAIL n={len(episode_dirs)} failures={failures}")
        return 1
    print(f"episode-content: OK n={len(episode_dirs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
