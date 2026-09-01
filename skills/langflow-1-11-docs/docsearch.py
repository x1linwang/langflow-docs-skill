#!/usr/bin/env python3
"""BM25 search over a pinned snapshot of the Langflow documentation.

Zero dependencies. Standard library only. Python 3.9+.

The corpus lives in `corpus/` next to this script, so the skill works from any
directory, in any project, with no repository around it and no network.

Subcommands
-----------
  build    Chunk the .mdx corpus and write a gzipped BM25 index.
  search   Rank chunks against a query.
  get      Print one chunk, or a whole page by path or slug.
  slugs    List every page as "slug<TAB>title<TAB>relpath".
  info     Show index statistics.

A prebuilt index ships in `index/`. It is validated by a content fingerprint
that survives `git clone` and unzip, both of which reset mtimes, so a fresh
install performs no writes at all -- which is what lets this run under agents
that sandbox the home directory read-only. If the corpus really has changed,
the index is rebuilt, falling back to a temp directory when `index/` is not
writable.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

DEFAULT_VERSION = "1.11.0"
SCRIPT_DIR = Path(__file__).resolve().parent
CORPUS_DIR = SCRIPT_DIR / "corpus"
INDEX_DIR = SCRIPT_DIR / "index"
INDEX_NAME = "corpus.idx.json.gz"
SYNONYMS_PATH = INDEX_DIR / "synonyms.json"

# Expansion terms score below literal query terms. High enough to rescue a
# paraphrased query, low enough that it cannot outrank an exact match.
SYNONYM_WEIGHT = 0.35

# A query that trips several keys at once can pull in more expansion terms than
# it has real ones, at which point the expansion is steering rather than
# assisting. Capping breadth keeps recall gains without that drift.
MAX_EXPANSION_TERMS = 12

# Default token budget for `get`, mirroring context7's `tokens` parameter.
# Roughly 4 chars per token on this corpus.
DEFAULT_BUDGET = 6000
CHARS_PER_TOKEN = 4

# BM25 parameters. k1 controls term-frequency saturation, b controls
# length normalisation. These are the standard defaults and behave well on
# short technical chunks.
K1 = 1.2
B = 0.75

# Tokens appearing in a chunk's title or heading trail are repeated this many
# times, so a query that names a page ranks that page above passing mentions.
HEADING_BOOST = 3

# Chunks longer than this are split at paragraph boundaries. Large enough to
# keep a procedure intact, small enough that a hit is a precise citation.
MAX_CHUNK_CHARS = 6000

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
IMPORT_RE = re.compile(r"^import\s+.+?from\s+.+?;?\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
EXPLICIT_ANCHOR_RE = re.compile(r"\s*\{#([A-Za-z0-9_-]+)\}\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
RAW_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./+-]*")
CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")
SEPARATOR_RE = re.compile(r"[_./+-]+")

# import X from '!!raw-loader!@site/docs/API-Reference/curl-examples/a/b.sh';
RAW_LOADER_RE = re.compile(
    r"""^import\s+(\w+)\s+from\s+['"]!!raw-loader!@site/docs/([^'"]+)['"]\s*;?\s*$""",
    re.MULTILINE,
)
# import PartialParams from '@site/docs/_partial-foo.mdx';
PARTIAL_IMPORT_RE = re.compile(
    r"""^import\s+(\w+)\s+from\s+['"]@site/docs/(_partial[^'"]+\.mdx)['"]\s*;?\s*$""",
    re.MULTILINE,
)
# <PartialParams />  or  <PartialParams/>
JSX_SELF_CLOSING_RE = re.compile(r"<(\w+)\s*/>")
# {exampleVariableName}
JSX_EXPR_RE = re.compile(r"\{(\w+)\}")


# --------------------------------------------------------------------------
# tokenisation
# --------------------------------------------------------------------------

def tokenize(text: str) -> list[str]:
    """Split text into BM25 terms.

    Technical docs are full of identifiers that naive tokenisers destroy.
    Each raw token is emitted three ways so all of these match:

      LANGFLOW_AUTO_LOGIN  -> langflow_auto_login, langflow, auto, login
      /api/v1/run          -> api/v1/run, api, v1, run
      DataFrameOperations  -> dataframeoperations, data, frame, operations
    """
    out: list[str] = []
    for match in RAW_TOKEN_RE.finditer(text):
        raw = match.group(0).strip("./-+")
        if not raw:
            continue
        out.append(raw.lower())
        pieces = [p for p in SEPARATOR_RE.split(raw) if p]
        if len(pieces) > 1:
            out.extend(p.lower() for p in pieces if len(p) > 1)
        for piece in pieces:
            camel = CAMEL_RE.findall(piece)
            if len(camel) > 1:
                out.extend(c.lower() for c in camel if len(c) > 1)
    return out


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------

def slugify_heading(text: str) -> str:
    """Approximate Docusaurus heading-anchor generation."""
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    return re.sub(r"\s+", "-", text.strip())


def parse_frontmatter(source: str) -> tuple[dict[str, str], str, int]:
    """Return (fields, body, number of lines consumed by the frontmatter)."""
    match = FRONTMATTER_RE.match(source)
    if not match:
        return {}, source, 0
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    consumed = source[: match.end()].count("\n")
    return fields, source[match.end():], consumed


def split_oversized(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on blank lines, never inside a fenced code block."""
    if len(text) <= limit:
        return [text]
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        current.append(line)
        if not in_fence and not line.strip() and sum(map(len, current)) >= limit:
            blocks.append("".join(current))
            current = []
    if current:
        blocks.append("".join(current))
    return blocks or [text]


FENCE_LANG = {".sh": "bash", ".py": "python", ".js": "javascript",
              ".ts": "typescript", ".json": "json", ".txt": "text"}


def _read_corpus_file(docs_root: Path, relpath: str) -> str | None:
    target = docs_root / relpath
    if target.is_file():
        return target.read_text(encoding="utf-8", errors="replace")
    return None


def expand_includes(body: str, docs_root: Path, depth: int = 0) -> str:
    """Inline the two Docusaurus indirections that hide content from search.

    API-Reference pages hold their curl/Python/JavaScript bodies in separate
    files pulled in by webpack's raw-loader, and component pages keep their
    parameter tables in shared `_partial-*.mdx` files. In both cases the .mdx
    on disk contains only a JSX variable reference, so indexing the .mdx alone
    makes every API example and every parameter table unsearchable.

    Imports name `@site/docs/...` even inside a frozen versioned copy, because
    Docusaurus resolves them against the live tree. The frozen tree carries its
    own copies of those files, so stripping the prefix resolves correctly here.
    """
    raw_map: dict[str, str] = {}
    for match in RAW_LOADER_RE.finditer(body):
        variable, relpath = match.group(1), match.group(2)
        text = _read_corpus_file(docs_root, relpath)
        if text is None:
            continue
        lang = FENCE_LANG.get(Path(relpath).suffix, "")
        raw_map[variable] = f"\n```{lang}\n{text.strip()}\n```\n"

    partial_map: dict[str, str] = {}
    for match in PARTIAL_IMPORT_RE.finditer(body):
        variable, relpath = match.group(1), match.group(2)
        text = _read_corpus_file(docs_root, relpath)
        if text is None:
            continue
        _, inner, _ = parse_frontmatter(text)
        if depth < 2:  # partials import partials; two levels is plenty.
            inner = expand_includes(inner, docs_root, depth + 1)
        partial_map[variable] = IMPORT_RE.sub("", inner).strip()

    body = IMPORT_RE.sub("", body)
    if partial_map:
        body = JSX_SELF_CLOSING_RE.sub(
            lambda m: partial_map.get(m.group(1), m.group(0)), body)
    if raw_map:
        body = JSX_EXPR_RE.sub(
            lambda m: raw_map.get(m.group(1), m.group(0)), body)
    return body


def corpus_pages(docs_root: Path) -> list[Path]:
    """Every addressable page. `*.md*` catches .md too, which .mdx-only globs
    silently dropped."""
    return sorted(f for f in docs_root.rglob("*.md*") if f.is_file())


def chunk_file(path: Path, docs_root: Path) -> list[dict]:
    """Turn one .mdx file into heading-scoped chunks."""
    source = path.read_text(encoding="utf-8", errors="replace")
    fields, body, offset = parse_frontmatter(source)
    body = expand_includes(body, docs_root)

    relpath = path.relative_to(docs_root).as_posix()
    title = fields.get("title") or path.stem.replace("-", " ")
    slug = fields.get("slug") or "/" + path.stem
    is_partial = path.name.startswith("_partial")

    # Collect (line_no, heading_level, heading_text, anchor) boundaries.
    sections: list[dict] = []
    current = {"line": offset + 1, "level": 1, "heading": title, "anchor": "", "lines": []}
    in_fence = False

    for index, line in enumerate(body.splitlines(), start=offset + 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
        heading = None if in_fence else HEADING_RE.match(line)
        if heading:
            if any(l.strip() for l in current["lines"]):
                sections.append(current)
            text = heading.group(2)
            explicit = EXPLICIT_ANCHOR_RE.search(text)
            if explicit:
                anchor = explicit.group(1)
                text = EXPLICIT_ANCHOR_RE.sub("", text)
            else:
                anchor = slugify_heading(text)
            # Strip Docusaurus "Direct link to" duplicates.
            text = re.sub(r"\[.*?\]\(#.*?\)\s*$", "", text).strip()
            current = {
                "line": index,
                "level": len(heading.group(1)),
                "heading": text,
                "anchor": anchor,
                "lines": [],
            }
        else:
            current["lines"].append(line)

    if any(l.strip() for l in current["lines"]):
        sections.append(current)

    chunks: list[dict] = []
    for section in sections:
        text = "\n".join(section["lines"]).strip()
        if not text:
            continue
        parts = split_oversized(text)
        for part_no, part in enumerate(parts):
            heading = section["heading"]
            if len(parts) > 1:
                heading = f"{heading} (part {part_no + 1}/{len(parts)})"
            chunks.append({
                "path": relpath,
                "line": section["line"],
                "title": title,
                "slug": slug,
                "heading": heading,
                "anchor": section["anchor"],
                "partial": is_partial,
                "text": part.strip(),
            })
    return chunks


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

def resolve_docs_root(version: str, override: str | None) -> Path:
    """The corpus ships inside the skill, so there is nothing to search for.

    An earlier version walked up the directory tree hunting for a checkout of
    the Langflow repo, which meant the skill only worked inside that one repo.
    `--docs-root` remains for deliberately pointing at a live checkout; there
    is no environment-variable override, because a stray variable silently
    defeating the version pin is a bad trade for a convenience nobody needed.
    """
    if override:
        root = Path(override).expanduser().resolve()
        if not root.is_dir():
            sys.exit(f"error: docs root not found: {root}")
        return root
    if CORPUS_DIR.is_dir():
        return CORPUS_DIR
    sys.exit(
        f"error: no corpus/ directory beside {SCRIPT_DIR.name}/docsearch.py. "
        "The skill is incomplete -- reinstall it, or pass --docs-root."
    )


def index_path(docs_root: Path) -> Path:
    """Where the index for this corpus lives.

    The bundled corpus gets one fixed, path-independent filename so that the
    index committed to the repo is actually found after `git clone` to an
    arbitrary location. Anything reached through --docs-root is keyed by path
    digest so it can never overwrite the bundled index and serve wrong content.
    """
    if docs_root == CORPUS_DIR:
        return INDEX_DIR / INDEX_NAME
    digest = hashlib.sha1(str(docs_root).encode()).hexdigest()[:10]
    return INDEX_DIR / f"external-{digest}.json.gz"


def fallback_index_path(docs_root: Path) -> Path:
    """Used when the install directory is read-only."""
    return Path(tempfile.gettempdir()) / "langflow-docsearch" / index_path(docs_root).name


def corpus_fingerprint(docs_root: Path) -> dict:
    """Content-addressed, deliberately mtime-free.

    `git clone` and unzip both reset mtimes, so an mtime-based fingerprint
    marks the shipped index stale on every fresh install and forces a rebuild
    -- which then fails wherever the install directory is not writable. Sizes
    and relative paths are stable across install location and clone time.
    """
    entries = []
    total = 0
    for path in sorted(docs_root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        size = path.stat().st_size
        entries.append(f"{path.relative_to(docs_root).as_posix()}:{size}")
        total += size
    return {
        "count": len(entries),
        "bytes": total,
        "sha": hashlib.sha1("\n".join(entries).encode()).hexdigest(),
    }


def load_synonyms() -> dict[str, list[str]]:
    """Query expansion map. Absent or malformed is fine -- search still works."""
    try:
        with open(SYNONYMS_PATH, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {k.lower(): list(v) for k, v in data.items() if isinstance(v, list)}


def load_sidebar(docs_root: Path) -> list[dict]:
    """Flattened sidebar entries, the only real hierarchy source in the corpus."""
    target = docs_root / "_sidebar.json"
    if not target.is_file():
        return []
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []

    flat: list[dict] = []

    def walk(node, trail):
        if isinstance(node, list):
            for item in node:
                walk(item, trail)
        elif isinstance(node, dict):
            kind = node.get("type")
            if kind == "category":
                label = node.get("label", "")
                walk(node.get("items", []), trail + [label])
            elif kind == "doc":
                flat.append({"id": node.get("id", ""), "trail": list(trail),
                             "label": node.get("label", "")})
            elif kind == "link":
                pass
        return

    walk(data.get(next(iter(data), ""), []) if isinstance(data, dict) else data, [])
    return flat


def build(version: str, docs_root: Path, quiet: bool = False) -> dict:
    files = corpus_pages(docs_root)
    if not files:
        sys.exit(f"error: no .md/.mdx files under {docs_root}")

    chunks: list[dict] = []
    for path in files:
        chunks.extend(chunk_file(path, docs_root))

    postings: dict[str, list[list[int]]] = defaultdict(list)
    lengths: list[int] = []

    for chunk_id, chunk in enumerate(chunks):
        terms = tokenize(chunk["text"])
        boosted = tokenize(f"{chunk['title']} {chunk['heading']} {chunk['slug']}")
        terms.extend(boosted * HEADING_BOOST)

        frequencies: dict[str, int] = defaultdict(int)
        for term in terms:
            frequencies[term] += 1
        for term, freq in frequencies.items():
            postings[term].append([chunk_id, freq])
        lengths.append(len(terms))

    index = {
        "version": version,
        # Deliberately not the absolute build path: a shipped index is read on
        # machines that have never seen it, and `get --slug` used to resolve
        # pages against whatever directory happened to build the index.
        "docs_root": None,
        "fingerprint": corpus_fingerprint(docs_root),
        "chunks": [{k: v for k, v in c.items() if k != "text"} for c in chunks],
        "texts": [c["text"] for c in chunks],
        "postings": {t: p for t, p in postings.items()},
        "lengths": lengths,
        "avgdl": (sum(lengths) / len(lengths)) if lengths else 0.0,
    }

    target = index_path(docs_root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(index, handle)
    except OSError:
        target = fallback_index_path(docs_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8") as handle:
            json.dump(index, handle)
        print(f"note: {index_path(docs_root).parent} is read-only; "
              f"cached the index at {target} instead.", file=sys.stderr)

    index["docs_root"] = str(docs_root)
    if not quiet:
        print(
            f"indexed {len(files)} files -> {len(chunks)} chunks, "
            f"{len(postings)} terms\nwrote {target} "
            f"({target.stat().st_size / 1_048_576:.2f} MB)",
            file=sys.stderr,
        )
    return index


def load(version: str, docs_root_override: str | None, rebuild: bool = False) -> dict:
    docs_root = resolve_docs_root(version, docs_root_override)

    if docs_root_override and docs_root.name != f"version-{version}":
        print(
            f"warning: reading {docs_root}, which is not a frozen "
            f"version-{version} snapshot. Results may not reflect {version}.",
            file=sys.stderr,
        )

    if not rebuild:
        for target in (index_path(docs_root), fallback_index_path(docs_root)):
            if not target.exists():
                continue
            try:
                with gzip.open(target, "rt", encoding="utf-8") as handle:
                    index = json.load(handle)
            except (OSError, ValueError):
                continue
            if corpus_fingerprint(docs_root) == index.get("fingerprint"):
                # Always the runtime location, never the build-time one.
                index["docs_root"] = str(docs_root)
                return index

    return build(version, docs_root, quiet=True)


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------

def expand_query(query: str, synonyms: dict[str, list[str]]) -> dict[str, float]:
    """Map a query to weighted BM25 terms.

    Literal terms weigh 1.0. Expansions weigh less, so they can rescue a
    paraphrased query without ever outranking an exact match. Multi-word keys
    are matched against the whole query, single-word keys against each token.

    This widens recall on paraphrase; it is not semantic search. A query that
    shares no vocabulary and no configured alias with the docs still misses.
    """
    weights: dict[str, float] = {}
    for term in tokenize(query):
        weights[term] = 1.0

    # A multi-word key fires when all of its tokens appear anywhere in the
    # query, not as a contiguous phrase. Requiring adjacency made the map
    # almost useless in practice: the key "external package" missed the very
    # natural "external python package", and one intervening word was enough
    # to lose the expansion entirely.
    fired: list[str] = []
    for key, values in synonyms.items():
        key_tokens = set(tokenize(key))
        if key_tokens and key_tokens <= weights.keys():
            fired.extend(values)

    added = 0
    for value in fired:
        if added >= MAX_EXPANSION_TERMS:
            break
        for term in tokenize(value):
            if term in weights:
                continue
            weights[term] = SYNONYM_WEIGHT
            added += 1
    return weights


def search(index: dict, query: str, limit: int, path_filter: str | None,
           include_partials: bool,
           synonyms: dict[str, list[str]] | None = None) -> list[tuple[int, float]]:
    total = len(index["lengths"])
    if not total:
        return []

    avgdl = index["avgdl"] or 1.0
    lengths = index["lengths"]
    postings = index["postings"]
    chunks = index["chunks"]

    scores: dict[int, float] = defaultdict(float)

    for term, weight in expand_query(query, synonyms or {}).items():
        entries = postings.get(term)
        if not entries:
            continue
        df = len(entries)
        idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
        for chunk_id, freq in entries:
            norm = freq * (K1 + 1) / (
                freq + K1 * (1 - B + B * lengths[chunk_id] / avgdl)
            )
            scores[chunk_id] += weight * idf * norm

    ranked = []
    for chunk_id, score in scores.items():
        chunk = chunks[chunk_id]
        if not include_partials and chunk["partial"]:
            continue
        if path_filter and path_filter.lower() not in chunk["path"].lower():
            continue
        ranked.append((chunk_id, score))

    ranked.sort(key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]


def snippet(text: str, query: str, width: int = 320) -> str:
    """Return the densest window of query terms, collapsed to one line."""
    terms = set(tokenize(query))
    lines = [l for l in text.splitlines() if l.strip()]
    best, best_hits = lines[:3], -1
    for start in range(len(lines)):
        window = lines[start:start + 3]
        hits = sum(1 for l in window for t in tokenize(l) if t in terms)
        if hits > best_hits:
            best, best_hits = window, hits
    flat = re.sub(r"\s+", " ", " ".join(best)).strip()
    return flat[:width] + ("..." if len(flat) > width else "")


def related_pages(index: dict, results: list[tuple[int, float]],
                  limit: int = 5) -> list[tuple[str, str]]:
    """Sibling pages of the top hit, from the vendored sidebar.

    A ranked chunk answers "where is this mentioned"; the sidebar answers
    "what else is in this part of the manual", which is usually the thing a
    half-formed question actually wanted.
    """
    if not results:
        return []
    docs_root = Path(index["docs_root"])
    sidebar = load_sidebar(docs_root)
    if not sidebar:
        return []

    top_path = index["chunks"][results[0][0]]["path"]
    top_id = top_path.rsplit(".", 1)[0]
    trail = next((e["trail"] for e in sidebar if e["id"] == top_id), None)
    if trail is None:
        return []

    hit_paths = {index["chunks"][cid]["path"] for cid, _ in results}
    by_id: dict[str, tuple[str, str]] = {}
    for chunk in index["chunks"]:
        by_id.setdefault(chunk["path"].rsplit(".", 1)[0],
                         (chunk["slug"], chunk["title"]))

    out: list[tuple[str, str]] = []
    for entry in sidebar:
        if entry["trail"] != trail or entry["id"] == top_id:
            continue
        found = by_id.get(entry["id"])
        if not found:
            continue
        if any(entry["id"] == hp.rsplit(".", 1)[0] for hp in hit_paths):
            continue
        if found not in out:
            out.append(found)
        if len(out) >= limit:
            break
    return out


def cmd_search(args: argparse.Namespace) -> None:
    index = load(args.version, args.docs_root, rebuild=args.rebuild)
    synonyms = {} if args.no_expand else load_synonyms()
    results = search(index, args.query, args.limit, args.path,
                     args.include_partials, synonyms)

    if not results:
        print(f"no matches for: {args.query}")
        return

    if args.json:
        payload = []
        for chunk_id, score in results:
            chunk = dict(index["chunks"][chunk_id])
            chunk["id"] = chunk_id
            chunk["score"] = round(score, 3)
            chunk["text"] = index["texts"][chunk_id]
            payload.append(chunk)
        print(json.dumps(payload, indent=2))
        return

    base = index["docs_root"]
    for rank, (chunk_id, score) in enumerate(results, start=1):
        chunk = index["chunks"][chunk_id]
        anchor = f"#{chunk['anchor']}" if chunk["anchor"] else ""
        trail = chunk["title"]
        if chunk["heading"] and chunk["heading"] != chunk["title"]:
            trail = f"{trail} > {chunk['heading']}"
        print(f"[{rank}] id={chunk_id}  score={score:.2f}")
        print(f"    {trail}")
        print(f"    url   docs.langflow.org{chunk['slug']}{anchor}")
        print(f"    file  {base}/{chunk['path']}:{chunk['line']}")
        if not args.no_snippet:
            print(f"    {snippet(index['texts'][chunk_id], args.query)}")
        print()

    related = related_pages(index, results)
    if related:
        print("related pages (same sidebar section):")
        for slug, title in related:
            print(f"    {slug}\t{title}")
        print()


def truncate_to_budget(text: str, budget: int) -> str:
    """Trim to roughly `budget` tokens at a line boundary.

    Thirty-odd pages in this corpus exceed 13 KB and the largest is 43 KB, so
    an unbounded `get` can spend 11k tokens on one page. Zero or negative
    disables the cap.
    """
    if budget <= 0:
        return text
    limit = budget * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = cut.rfind("\n")
    if boundary > limit // 2:
        cut = cut[:boundary]
    dropped = len(text) - len(cut)
    return (cut.rstrip() + f"\n\n[truncated: {dropped} more characters "
            f"(~{dropped // CHARS_PER_TOKEN} tokens). Raise --budget or use "
            f"--budget 0 for the whole page.]")


def cmd_get(args: argparse.Namespace) -> None:
    index = load(args.version, args.docs_root)

    if args.id is not None:
        if not 0 <= args.id < len(index["texts"]):
            sys.exit(f"error: id {args.id} out of range (0-{len(index['texts']) - 1})")
        chunk = index["chunks"][args.id]
        print(f"# {chunk['title']} > {chunk['heading']}")
        print(f"# {index['docs_root']}/{chunk['path']}:{chunk['line']}\n")
        print(truncate_to_budget(index["texts"][args.id], args.budget))
        return

    docs_root = Path(index["docs_root"])
    target = None
    if args.slug:
        wanted = args.slug if args.slug.startswith("/") else "/" + args.slug
        for chunk in index["chunks"]:
            if chunk["slug"] == wanted:
                target = docs_root / chunk["path"]
                break
        if target is None:
            sys.exit(f"error: no page with slug {wanted}")
    elif args.path:
        target = docs_root / args.path
        if not target.is_file():
            matches = [c["path"] for c in index["chunks"]
                       if args.path.lower() in c["path"].lower()]
            if not matches:
                sys.exit(f"error: no page matching {args.path}")
            target = docs_root / sorted(set(matches))[0]
    else:
        sys.exit("error: pass --id, --slug, or --path")

    source = target.read_text(encoding="utf-8", errors="replace")
    fields, body, _ = parse_frontmatter(source)
    if not args.raw:
        # Same expansion the indexer applies, so what you read is what was
        # searched: API examples and parameter tables present, not JSX stubs.
        body = expand_includes(body, docs_root)
    title = fields.get("title", target.stem)
    slug = fields.get("slug", "")
    header = f"# {title}\n# docs.langflow.org{slug}\n# {target.relative_to(docs_root)}\n"
    print(header)
    print(truncate_to_budget(body.strip(), args.budget))


def cmd_slugs(args: argparse.Namespace) -> None:
    index = load(args.version, args.docs_root)
    seen = {}
    for chunk in index["chunks"]:
        if chunk["partial"] and not args.include_partials:
            continue
        seen.setdefault(chunk["slug"], (chunk["title"], chunk["path"]))
    for slug, (title, path) in sorted(seen.items()):
        print(f"{slug}\t{title}\t{path}")


def cmd_info(args: argparse.Namespace) -> None:
    index = load(args.version, args.docs_root)
    pages = {c["path"] for c in index["chunks"]}
    print(f"version    {index['version']}")
    print(f"docs root  {index['docs_root']}")
    root = Path(index["docs_root"])
    primary, fallback = index_path(root), fallback_index_path(root)
    print(f"index      {primary if primary.exists() else fallback}")
    print(f"bundled    {'yes' if root == CORPUS_DIR else 'no (--docs-root)'}")
    print(f"pages      {len(pages)}")
    print(f"chunks     {len(index['chunks'])}")
    print(f"terms      {len(index['postings'])}")
    print(f"avg len    {index['avgdl']:.1f} tokens")
    print(f"synonyms   {len(load_synonyms())} keys")
    manifest = Path(index["docs_root"]) / "MANIFEST.json"
    if manifest.is_file():
        with open(manifest, encoding="utf-8") as handle:
            meta = json.load(handle)
        print(f"upstream   {meta.get('upstream_commit', '?')[:12]} "
              f"({meta.get('upstream_commit_date', '?')})")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="docsearch",
        description="BM25 search over a pinned version of the Langflow docs.",
    )
    parser.add_argument("--version", default=DEFAULT_VERSION,
                        help=f"doc version directory suffix (default {DEFAULT_VERSION})")
    parser.add_argument("--docs-root", default=None,
                        help="override path to versioned_docs/version-X.Y.Z")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="rebuild the index")
    p_build.set_defaults(func=lambda a: build(a.version,
                                              resolve_docs_root(a.version, a.docs_root)))

    p_search = sub.add_parser("search", help="rank chunks against a query")
    p_search.add_argument("query")
    p_search.add_argument("-n", "--limit", type=int, default=8)
    p_search.add_argument("--path", default=None,
                          help="restrict to paths containing this substring")
    p_search.add_argument("--include-partials", action="store_true")
    p_search.add_argument("--no-snippet", action="store_true")
    p_search.add_argument("--json", action="store_true",
                          help="emit full chunk text as JSON")
    p_search.add_argument("--rebuild", action="store_true")
    p_search.add_argument("--no-expand", action="store_true",
                          help="disable synonym expansion (literal terms only)")
    p_search.set_defaults(func=cmd_search)

    p_get = sub.add_parser("get", help="print a chunk or a whole page")
    p_get.add_argument("--id", type=int, default=None)
    p_get.add_argument("--slug", default=None)
    p_get.add_argument("--path", default=None)
    p_get.add_argument("--budget", type=int, default=DEFAULT_BUDGET,
                       help=f"approximate token cap (default {DEFAULT_BUDGET}; "
                            "0 for no cap)")
    p_get.add_argument("--raw", action="store_true",
                       help="print the .mdx verbatim, without inlining includes")
    p_get.set_defaults(func=cmd_get)

    p_slugs = sub.add_parser("slugs", help="list every page")
    p_slugs.add_argument("--include-partials", action="store_true")
    p_slugs.set_defaults(func=cmd_slugs)

    p_info = sub.add_parser("info", help="show index statistics")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
