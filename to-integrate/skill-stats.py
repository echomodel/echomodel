#!/usr/bin/env python3
"""Parse agent session files and report skill invocation stats as JSON.

Prototype script — ~0.25s for ~300 sessions on Claude Code.

Integration notes:
  - When incorporating into the product, this should be an SDK operation
    first, then exposed as both a CLI subcommand (`em stats`) and an MCP tool.
  - Must require an agent platform parameter (e.g. "claude", "gemini") to
    decide where to collect stats from. Only one platform per execution.
    Each platform stores sessions differently:
      - Claude Code: ~/.claude/projects/*/*.jsonl, <command-name> tags
      - Gemini CLI: TBD — session format and storage path not yet researched
  - The detection method is platform-specific. Claude Code uses <command-name>
    XML tags injected when a skill fires. Other platforms may use different
    markers. Each platform needs its own parser.
  - See echomodel/echomodel#20 for the full design discussion.
"""

import json
import os
import re
import sys
import time


def collect_claude(base=None):
    """Collect skill invocation stats from Claude Code session files.

    Parses <command-name> tags from JSONL session files. These tags are
    injected by Claude Code when a skill fires — reliable signal, no
    false positives from text mentions.
    """
    if base is None:
        base = os.path.expanduser("~/.claude/projects")
    results = {}
    session_count = 0

    for root, dirs, files in os.walk(base):
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            session_count += 1
            path = os.path.join(root, f)
            with open(path) as fh:
                for line in fh:
                    if "<command-name>" in line:
                        for m in re.finditer(
                            r"<command-name>(/[^<]+)</command-name>", line
                        ):
                            cmd = m.group(1)
                            results[cmd] = results.get(cmd, 0) + 1

    return session_count, results


def main():
    t0 = time.time()
    session_count, results = collect_claude()
    elapsed = time.time() - t0

    output = {
        "platform": "claude",
        "sessions_scanned": session_count,
        "elapsed_seconds": round(elapsed, 3),
        "total_invocations": sum(results.values()),
        "skills": [
            {"name": name, "count": count}
            for name, count in sorted(results.items(), key=lambda x: -x[1])
        ],
    }
    json.dump(output, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
