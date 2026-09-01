#!/usr/bin/env python3
"""Retrieval regression harness.

Each case names a query and the slugs that would count as a correct landing
page. Reports top-1 and top-3 hit rates with and without synonym expansion,
so a change to the synonym map is measured rather than eyeballed.

Usage:  python3 scripts/regression.py [--verbose]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "langflow-1-11-docs"

# (query, acceptable slugs). Precise queries guard against expansion damage;
# paraphrases measure whether expansion earns its keep.
CASES = [
    # --- exact vocabulary: must not regress ---
    ("LANGFLOW_AUTO_LOGIN", ["/api-keys-and-authentication", "/environment-variables"]),
    ("session id", ["/session-id"]),
    ("structured output", ["/structured-output"]),
    ("split text chunk overlap", ["/split-text"]),
    ("agent as a tool", ["/agents-tools"]),
    ("custom component tool mode", ["/agents-tools", "/components-custom-components"]),
    ("webhook trigger", ["/webhook", "/component-webhook"]),
    ("global variables", ["/configuration-global-variables"]),
    ("environment variables", ["/environment-variables"]),
    ("data types", ["/data-types"]),
    ("message history", ["/message-history", "/memory"]),
    ("loop component", ["/loop"]),
    ("if else conditional routing", ["/if-else", "/smart-router"]),
    ("mcp server", ["/mcp-server"]),
    ("knowledge base", ["/knowledge-base", "/knowledge"]),
    ("deploy on kubernetes production", ["/deployment-kubernetes-prod",
                                         "/deployment-prod-best-practices"]),
    ("external postgres database", ["/configuration-custom-database",
                                    "/enterprise-database-guide"]),
    ("langflow cli options", ["/configuration-cli"]),
    ("import and export flows", ["/concepts-flows-import"]),
    ("run flow python example", ["/api-flows-run", "/api-reference-api-examples"]),
    ("api request component parameters", ["/api-request"]),
    ("file system tool base directory", ["/file-system", "/environment-variables"]),

    # --- paraphrase: what expansion is for ---
    ("keep the conversation between turns", ["/session-id", "/message-history",
                                             "/memory", "/memory-bases"]),
    ("my component does not show up in the menu",
     ["/components-custom-components", "/troubleshoot", "/concepts-components"]),
    ("how do I use an external python package in my component",
     ["/install-custom-dependencies", "/components-custom-components",
      "/develop-application"]),
    ("hide an api key from the flow", ["/configuration-global-variables",
                                       "/api-keys-and-authentication"]),
    ("call my flow from a website", ["/api-flows-run", "/concepts-publish",
                                     "/typescript-client"]),
    ("make the model return json I can parse", ["/structured-output", "/data-types"]),
    ("let a person approve before it continues", ["/human-in-the-loop", "/human-input"]),
    ("stop my agent from calling a tool it should not use",
     ["/agents-tools", "/policies", "/guardrails"]),
    ("chatbot that answers from my documents", ["/chat-with-rag", "/knowledge",
                                                "/chat-with-files"]),
    ("run more than one worker", ["/deployment-multi-worker"]),
    ("where do the logs go", ["/logging", "/api-logs"]),
    ("it is really slow to start", ["/lfx-prewarm", "/troubleshoot",
                                    "/deployment-multi-worker"]),
]


def run(query: str, expand: bool, limit: int = 3) -> list[str]:
    cmd = [sys.executable, "docsearch.py", "search", query, "-n", str(limit),
           "--json"]
    if not expand:
        cmd.append("--no-expand")
    out = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True)
    if out.returncode != 0:
        return []
    try:
        return [c["slug"] for c in json.loads(out.stdout)]
    except ValueError:
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    tally = {True: [0, 0], False: [0, 0]}
    rows = []
    for query, wanted in CASES:
        row = {"query": query}
        for expand in (False, True):
            slugs = run(query, expand)
            top1 = bool(slugs) and slugs[0] in wanted
            top3 = any(s in wanted for s in slugs)
            tally[expand][0] += top1
            tally[expand][1] += top3
            row["exp" if expand else "lit"] = (top1, top3, slugs[:1])
        rows.append(row)

    total = len(CASES)
    print(f"{total} cases\n")
    print(f"{'':38} {'top1':>10} {'top3':>10}")
    for label, expand in (("literal only", False), ("with expansion", True)):
        hits = tally[expand]
        print(f"{label:38} {hits[0]:>4}/{total:<5} {hits[1]:>4}/{total:<5}")
    print()

    changed = [r for r in rows if r["lit"][:2] != r["exp"][:2]]
    if changed:
        print("cases expansion changed:")
        for r in changed:
            lit, exp = r["lit"], r["exp"]
            verdict = "better" if exp[1] >= lit[1] and exp[0] >= lit[0] else (
                "WORSE" if (exp[0] < lit[0] or exp[1] < lit[1]) else "mixed")
            print(f"  [{verdict:6}] {r['query']}")
            print(f"            literal  top1={lit[0]} top3={lit[1]} {lit[2]}")
            print(f"            expanded top1={exp[0]} top3={exp[1]} {exp[2]}")

    if args.verbose:
        print("\nall cases:")
        for r in rows:
            print(f"  {r['query'][:60]:62} lit={r['lit'][:2]} exp={r['exp'][:2]}")

    misses = [r["query"] for r in rows if not r["exp"][1]]
    if misses:
        print(f"\nstill missing top-3 ({len(misses)}):")
        for q in misses:
            print(f"  - {q}")


if __name__ == "__main__":
    main()
