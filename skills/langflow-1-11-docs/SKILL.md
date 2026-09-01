---
name: langflow-1-11-docs
description: Search the bundled Langflow 1.11.x documentation and cite exact pages. Use this whenever a question touches how Langflow works - components, flows, agents, tool mode, the Langflow API, environment variables, authentication, deployment, MCP, bundles, memory, or troubleshooting - and whenever writing, debugging, or reviewing a Langflow flow, a custom Python component, or an API call. Also use it to confirm whether a feature exists in 1.11.x before relying on it, because Langflow's component names, input types, and environment variables shift between minor versions and recalled details are frequently wrong in ways that look right. Prefer it over recalled knowledge, and over Context7, which currently serves Langflow 1.10 docs. The corpus ships inside the skill, so this works offline and in any project.
license: MIT
compatibility: Needs python3 (3.9 or newer) on PATH and the ability to run it. No third-party packages, no network.
allowed-tools: Bash, Read, Grep
---

# Langflow 1.11.x documentation

Answer Langflow questions from this corpus rather than from memory. Langflow's
API surface, component names, and environment variables move fast between minor
versions, and recalled details are wrong often enough — while looking
plausible — that guessing costs more time than searching.

The corpus is the frozen `version-1.11.0` snapshot, which covers the whole
1.11.x line: Langflow cuts doc versions per minor, not per patch, so 1.11.0
through 1.11.x all share it. It lives in `corpus/` inside this skill, with
provenance in `corpus/MANIFEST.json`. Nothing here needs a network or a
Langflow checkout.

## Commands

`docsearch.py` sits next to this file. It finds its own corpus, so the working
directory does not matter. Substitute the real path to this skill directory for
`$SKILL` below.

```bash
# Rank chunks against a query. Start here.
python3 "$SKILL/docsearch.py" search "trigger a flow with a webhook" -n 8

# Narrow to a doc area when a query is broad.
python3 "$SKILL/docsearch.py" search "authentication" --path Deployment
python3 "$SKILL/docsearch.py" search "api key" --path API-Reference

# Read a result. `id` comes from the search output.
python3 "$SKILL/docsearch.py" get --id 1044

# Read a whole page, by slug or path fragment. Capped at ~6000 tokens.
python3 "$SKILL/docsearch.py" get --slug /webhook
python3 "$SKILL/docsearch.py" get --slug /bundles-datastax --budget 12000
python3 "$SKILL/docsearch.py" get --path Components/loop.mdx

# Every page as "slug<TAB>title<TAB>path". Good for learning the vocabulary.
python3 "$SKILL/docsearch.py" slugs

# Full chunk text as JSON, for programmatic use.
python3 "$SKILL/docsearch.py" search "session id" -n 3 --json

# Corpus and index provenance.
python3 "$SKILL/docsearch.py" info
```

Useful flags: `--budget 0` on `get` removes the token cap; `--raw` shows the
`.mdx` verbatim without inlining includes; `--no-expand` on `search` disables
synonym expansion when you want literal terms only.

## Where things are

Jumping straight to a page beats searching when the topic is already clear.

| Topic | Slug |
|---|---|
| Custom Python components, `Component` class, inputs/outputs | `/components-custom-components` |
| Making any component a tool; agent as a tool; toolsets | `/agents-tools` |
| Agent component behaviour | `/agents` |
| Component concepts, inspection panel, ports | `/concepts-components` |
| Installing extra Python packages for components | `/install-custom-dependencies` |
| Input/output data types, `Message`, `Data`, `DataFrame` | `/data-types` |
| Environment variables (all `LANGFLOW_*`) | `/environment-variables` |
| API keys, `x-api-key`, auto-login, SSRF settings | `/api-keys-and-authentication` |
| Global variables and secrets | `/configuration-global-variables` |
| Calling a flow over HTTP, `/api/v1/run`, streaming | `/api-flows-run` |
| Langflow API, getting started, examples | `/api-reference-api-examples` |
| Triggering flows, publishing, embedding a chat widget | `/concepts-publish` |
| Webhooks | `/webhook`, `/component-webhook` |
| Session IDs and how components share state | `/session-id` |
| Memory, message history, memory bases | `/memory`, `/message-history`, `/memory-bases` |
| Building and managing flows | `/concepts-flows` |
| Importing/exporting flow JSON | `/concepts-flows-import` |
| Langflow as an MCP server / client | `/mcp-server`, `/mcp-client` |
| Bundles overview, then `/bundles-<vendor>` | `/components-bundle-components` |
| Vector data and knowledge bases | `/knowledge`, `/knowledge-base` |
| Structured/JSON output | `/structured-output` |
| Loops and batching | `/loop`, `/batch-run` |
| Conditional routing | `/if-else`, `/smart-router` |
| Docker deployment | `/deployment-docker` |
| Kubernetes production | `/deployment-kubernetes-prod` |
| Multiple workers / scaling | `/deployment-multi-worker` |
| External PostgreSQL | `/configuration-custom-database` |
| CLI flags | `/configuration-cli` |
| Troubleshooting | `/troubleshoot` |
| Logs and traces | `/logging`, `/traces` |
| Release notes, what changed | `/release-notes` |

## Working method

1. **Search before answering**, even when you feel certain. One search is
   cheap; a confidently wrong version-specific claim is not.
2. **Read the chunk, do not answer from the snippet.** Snippets exist to help
   you choose which `get` to run. Answering from a snippet is how half-correct
   answers happen.
3. **Read the whole page for procedures.** If the question is "how do I do X",
   the surrounding steps matter. Use `get --slug`.
4. **Cite what you used** — the `docs.langflow.org/<slug>#<anchor>` URL from the
   search output. Those URLs are version-default, so they resolve to 1.11.x.
5. **Say so when the corpus is silent.** If two or three reformulations find
   nothing, report that the 1.11.x docs do not cover it. That is a useful
   answer. Filling the gap from memory is not.

## What the docs are authoritative for, and what they are not

The docs are the truth for **concepts, procedures, environment variables, and
API shapes**.

They are *not* the truth for **the exact field names, input types, and edge
handles of a specific component in your running Langflow**. Those come from the
instance itself — `GET /api/v1/all` returns the live component registry, and it
is the only reliable source when you are writing flow JSON by hand or matching
a component's parameter names. Docs can lag the code; the registry cannot.

So: docs for "how does tool mode work", the running instance for "what is this
component's field actually called".

## For anything that is not Langflow

This corpus is Langflow only. For third-party packages a component imports —
`pandas`, `scipy`, `yfinance`, `httpx`, anything on PyPI — use Context7 or the
package's own docs. Do not search here for them and do not guess; Langflow's
docs say nothing about them.

Context7 is also worth reaching for on Langflow questions *newer* than this
snapshot, with the caveat that it currently indexes Langflow 1.10, so it will
disagree with 1.11.x on authentication, environment variables, and the CLI —
exactly the pages where a version mix-up produces confident wrong answers.

## Deeper references

Written by hand, for things the official docs cover thinly or not at all. Read
one when the task calls for it; they are not needed for ordinary doc lookups.

- `references/custom-components.md` — how Langflow actually loads a custom
  component, why only top-level imports run, how tool names and descriptions
  are derived, which input types support tool mode. Read this **before writing
  or debugging a custom component**; most custom-component failures are one of
  these rules.
- `references/flow-json.md` — the flow JSON schema, node and edge shapes,
  encoded edge handles, and how to build nodes from the live component
  registry. Read this before hand-editing or generating a flow file.
- `references/api-and-auth.md` — which credential works on which route, and how
  auto-login changes things. Read this when an API call returns 401 or 403.
- `references/external-packages.md` — getting third-party packages into a
  Langflow image so components can import them.

## How retrieval behaves, so you can query it well

BM25 over heading-level chunks, with title and heading terms boosted, plus a
synonym map that expands common phrasings into the nouns the docs use.

**Strong on exact vocabulary.** Identifiers survive tokenisation whole and also
match their parts, so `LANGFLOW_AUTO_LOGIN`, `langflow auto login`, and
`auto login` all reach the right section.

**Weaker on paraphrase**, because it is lexical, not semantic. The synonym map
covers many common phrasings, but a query sharing no vocabulary and no
configured alias with the docs will still miss. Two habits fix most of it:

- **Guess the doc's noun.** Langflow says "Tool Mode", "Toolset", "Structured
  Output", "Session ID", "global variables", "bundles". Query the noun, not the
  symptom.
- **Try two or three variants** before concluding something is undocumented:
  the feature name, the user-facing symptom, and the likely component name.
  `slugs` is a fast way to find the real vocabulary.

`grep` over `corpus/` is a reasonable fallback for a distinctive string with no
obvious keyword.

## Notes

- Zero dependencies, standard library only, Python 3.9+.
- 246 pages become ~1620 chunks. A prebuilt index ships in `index/`, validated
  by a content fingerprint that survives cloning, so a fresh install performs
  no writes and the first search is instant. If the corpus genuinely changes,
  the index rebuilds in about a second, falling back to a temp directory when
  the install location is read-only.
- API reference pages keep their curl/Python/JavaScript bodies in separate
  files, and component pages keep parameter tables in shared partials. Both are
  inlined at index time, so examples and parameter tables are searchable and
  appear in `get` output. `--raw` shows the unexpanded source.
- `_partial-*.mdx` fragments are indexed but excluded from results by default,
  since they are not addressable pages. `--include-partials` includes them.
