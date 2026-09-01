# langflow-1-11-docs

An agent skill that gives coding agents accurate, citable access to the
**Langflow 1.11.x** documentation — offline, with no setup. Works in Claude
Code, Codex CLI, and opencode from a single install.

Alongside the official docs it bundles a set of hand-written notes drawn from
actually building this stuff: Langflow flows, custom Python components, and
custom tools for the Agent component to call. Those notes cover the things that
cost me the most time and that the official documentation does not state.

> **This is not an official Langflow skill.** It is a personal project, built
> for my team and my students, with no affiliation with or endorsement from the
> Langflow project. It bundles Langflow's documentation, which is MIT licensed,
> but the packaging, the search tool, and the hand-written notes are mine.
>
> The `/plugin marketplace add` below points at a marketplace self-hosted from
> this repository — it is my own catalogue, not Anthropic's official or community
> marketplace.
>
> It is a work in progress and will keep changing. If you try it and something
> is wrong, missing, or misleading, please open an issue — bug reports and
> corrections are genuinely welcome, especially on the hand-written notes, where
> I am describing observed behaviour rather than quoting a spec.

## Why it exists

Langflow's component names, input types, environment variables, and
authentication behaviour move between minor versions. Agents answer these
questions confidently from memory and are wrong often enough to be expensive —
and the wrong answers look right.

General doc-lookup tools do not fully solve it either. Context7, at the time of
writing, serves Langflow **1.10** docs. Those disagree with 1.11.x precisely on
authentication, environment variables, and the CLI, which are exactly the pages
where a version mix-up produces a confident wrong answer.

So this pins one version, ships it inside the skill, and tells the agent to
search before answering.

## Install

**Prerequisite for both methods:** `python3` 3.9 or newer on your `PATH`. The
skill runs a small Python script to search the corpus, so Python is needed at
query time regardless of how you install. Nothing else — no third-party
packages, no network, no Langflow checkout.

Pick **one** of the two methods below, not both. See the note at the end for why.

### Claude Code — install as a plugin (recommended)

```
/plugin marketplace add x1linwang/langflow-docs-skill
/plugin install langflow-docs@langflow-docs-skill
```

Nothing to clone, and no shell script to run. Claude Code tells you at session
start when a new version is available, and `/plugin` handles enable, disable,
and uninstall.

The skill is namespaced as `langflow-docs:langflow-1-11-docs`, but you do not
need to type that — like any skill, it loads on its own when your question
matches its description.

The first time it searches, Claude Code asks permission to run `python3`. Approve
it; the skill cannot search the corpus otherwise. To skip the prompt in a project
you use often, add this to its `.claude/settings.json`:

```json
{ "permissions": { "allow": ["Bash(python3 *)"] } }
```

### Codex CLI, opencode, or manual — install as files

`/plugin` is a Claude Code feature; Codex CLI and opencode do not read
`.claude-plugin/`. Everywhere else, use the script:

```bash
git clone https://github.com/x1linwang/langflow-docs-skill.git
cd langflow-docs-skill
./install.sh
```

It detects which agent CLIs you have and installs into each. Then start a new
session and ask a Langflow question — there is nothing to configure.

```bash
./install.sh --list       # show what would happen, change nothing
./install.sh --project    # install into ./.claude/skills of the current repo
./install.sh --uninstall  # remove it again
```

On Windows, run the installer in Git Bash or WSL.

Updating a script install means pulling and re-running it, and nothing prompts
you to. That notification is the main thing the plugin route adds.

> **Why one method and not both.** A plugin skill is namespaced, so it coexists
> with a plain `~/.claude/skills/` copy rather than replacing it. With both
> installed you get two entries — `langflow-1-11-docs` and
> `langflow-docs:langflow-1-11-docs`. Both work, and the duplicate description
> costs only a couple of hundred tokens, so this is not urgent.
>
> The reason it matters is **version skew**: update the plugin and your older
> script copy stays behind at the previous corpus. The agent may then answer from
> a stale snapshot with nothing to signal that it is stale, which is the exact
> failure this skill exists to prevent. If you already ran `install.sh` and want
> the plugin, run `./install.sh --uninstall` first.

### Where it lands

| Tool | Directory |
|---|---|
| Claude Code | `~/.claude/skills/langflow-1-11-docs` |
| opencode | reads `~/.claude/skills`, or `~/.config/opencode/skills` |
| Codex CLI | `~/.codex/skills/langflow-1-11-docs` |

`SKILL.md` is an open standard, so one copy serves all three. If you would
rather not run the script, copying `skills/langflow-1-11-docs/` into any of
those directories works identically.

## Using it directly

It is just a CLI, so you can drive it yourself:

```bash
cd ~/.claude/skills/langflow-1-11-docs

python3 docsearch.py search "trigger a flow with a webhook" -n 8
python3 docsearch.py get --slug /agents-tools
python3 docsearch.py get --slug /bundles-datastax --budget 12000
python3 docsearch.py slugs        # every page, for finding the right vocabulary
python3 docsearch.py info
```

`search` ranks heading-level chunks and prints citable
`docs.langflow.org/<slug>#<anchor>` URLs; `get` prints a chunk or a whole page
under a token budget. Same two-step shape as a resolve-then-fetch docs service.

## What is in here

```
skills/langflow-1-11-docs/
├── SKILL.md          instructions the agent loads; the only always-loaded file
├── docsearch.py      BM25 search, standard library only
├── corpus/           the Langflow 1.11.0 docs (246 pages), plus MANIFEST.json
├── index/            prebuilt search index + the synonym map
└── references/       hand-written notes (see below)
```

`corpus/` is about 3 MB on disk and never enters the model's context — only
search results do, at roughly 1–8k tokens per query. The full corpus is some
300–400k tokens of text, which is exactly why it is searched rather than loaded.

### The hand-written notes

This is the part that came out of building things rather than reading docs, and
probably the most useful part if you are writing your own components:

- **`references/custom-components.md`** — Langflow loads component files by AST
  surgery rather than importing them, so only flat top-level imports execute;
  the tool name the LLM sees is the output's *method* name, not the display
  name; the tool description is `Output(info=...)`, and leaving it unset gives
  an agent N tools with one identical description; the args schema is built once
  from every `tool_mode=True` input and shared across all actions; a category
  directory needs `__init__.py` or its components silently never appear.
- **`references/flow-json.md`** — node and edge shapes, and the `œ`-encoded edge
  handles that read like file corruption the first time you meet them.
- **`references/api-and-auth.md`** — `x-api-key` for execution routes, session
  JWT for management routes, and why `GET /api/v1/all` is the real source of
  truth for a component's field names.
- **`references/external-packages.md`** — getting third-party packages into a
  Langflow image so components can import them.

Each file marks which claims are quoted from the docs and which are observed
behaviour, so you know what to re-verify after an upgrade. Please tell me if any
of the observed ones stop being true.

## Honest limits

- **Lexical, not semantic.** BM25 with a curated synonym map, not embeddings. It
  is excellent when you name things the way the docs do, and a query sharing no
  vocabulary and no configured alias with the docs can still miss. Real
  embeddings would mean an API key or a model download, which would break
  offline use and give different users different results.
- **Pinned, so stale by design.** It knows the 1.11.0 snapshot and nothing after
  it. `scripts/sync_corpus.sh` re-vendors a newer version when you choose to.
- **Docs lag code.** For a component's actual field names and handles in *your*
  instance, `GET /api/v1/all` is authoritative, not the docs. The skill says so
  rather than pretending otherwise.
- **Langflow only.** For `pandas`, `scipy`, `yfinance` and friends, use Context7
  or the package's own docs. The skill tells the agent this explicitly so it
  does not search here for them.
- **Retrieval, not reasoning.** It finds the right pages; the agent still has to
  read them.
- **Triggering differs slightly per tool.** All three read `SKILL.md`, but each
  decides on its own when to load a skill.

## Contributing

Issues and PRs welcome, particularly:

- a query that should have found a page and did not — please include the exact
  query, it is the most useful kind of bug report for this project
- anything in `references/` that is wrong, or that changed in a newer Langflow
- support for another agent CLI's skills directory

```bash
python3 scripts/regression.py       # 34-case retrieval check, literal vs expanded
python3 scripts/quick_validate.py skills/langflow-1-11-docs
claude plugin validate . --strict   # marketplace manifest
claude plugin validate .claude-plugin/plugin.json --strict
./scripts/sync_corpus.sh 1.12.0     # re-vendor upstream docs, rebuild the index
```

Note that `claude plugin validate .` checks only the *marketplace* manifest when
both files are present, so validate `plugin.json` by path as well.

### Cutting a release

```bash
# 1. bump "version" in .claude-plugin/plugin.json
# 2. commit and push
claude plugin tag                   # optional: langflow-docs--v<version> git tag
```

The version bump is not optional if you want anyone to receive the update.
Because `version` is set in `plugin.json`, Claude Code pins to that string —
push new commits without bumping it and existing users keep the cached copy
indefinitely.

`regression.py` is the guard on the synonym map. Query expansion trades
precision for recall — an early version demoted `/structured-output` for the
query "structured output" — so any edit to `index/synonyms.json` should be
measured rather than eyeballed. Current baseline: 34 cases, top-1 32/34 and
top-3 34/34 with expansion, versus 26/34 and 30/34 literal-only.

## Licence

MIT, see `LICENSE`.

The bundled documentation in `skills/langflow-1-11-docs/corpus/` is
redistributed from [langflow-ai/langflow](https://github.com/langflow-ai/langflow)
under the MIT Licence. See `corpus/NOTICE` for attribution and
`corpus/MANIFEST.json` for the exact upstream commit and vendoring date.
Langflow and its logo are trademarks of their respective owners; this project is
not affiliated with them.
