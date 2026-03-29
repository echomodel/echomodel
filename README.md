# aicfg

Manage AI agent skills, MCP servers, and configuration across Claude Code and Gemini CLI from a single tool.

## Why

Claude Code and Gemini CLI each have their own skill format, config files, and MCP server registrations. If you use both, you're maintaining everything in two places. aicfg bridges the gap:

- **One command to install a skill to both platforms** — no need to learn each tool's install syntax
- **Git-hosted skill marketplaces** — register a repo, browse skills, install by name
- **Unified MCP server management** — register, health-check, and list servers across scopes
- **Context file unification** — keep CLAUDE.md and .gemini/settings.json in sync from shared source files

Skills use the [agentskills.io](https://agentskills.io/) open standard. Marketplace repos work natively with `gemini skills install` too.

## Quick Start

```bash
# Install
pipx install -e . --force

# Register a skills marketplace
aicfg skills marketplace register my/skills https://github.com/YOUR_USERNAME/skills.git

# See what's available
aicfg skills list

# Install a skill (to both Claude and Gemini)
aicfg skills install develop-unit-tests

# Install to one platform only
aicfg skills install nm --platform claude

# Publish a local skill to a marketplace
aicfg skills publish my-skill --marketplace my/skills
```

## Commands

### Skills

```bash
aicfg skills list                              # all skills across marketplaces + local
aicfg skills list --installed any              # only installed skills
aicfg skills list --installed claude           # installed on claude
aicfg skills list --installed none             # not installed anywhere
aicfg skills list --refresh                    # force marketplace cache refresh
aicfg skills install <name>                    # install to all configured platforms
aicfg skills install <name> --platform claude  # install to one platform
aicfg skills uninstall <name>
aicfg skills show <name>                       # full details + status per marketplace
aicfg skills publish <name>                    # publish to source marketplace
aicfg skills publish <name> --marketplace <alias>
aicfg skills publish <name> --source-path ~/ws/my-skill  # from arbitrary dir
aicfg skills marketplace register <alias> <git-url>
aicfg skills marketplace list
aicfg skills marketplace remove <alias>
```

Marketplace repos work natively with both aicfg and the Gemini CLI:

```bash
# These are equivalent — same repo, same skill:
aicfg skills install develop-skill               # via aicfg
gemini skills install <url> --path coding/develop-skill  # via Gemini CLI
```

Claude Code has no native skill CLI. aicfg copies SKILL.md to `~/.claude/skills/<name>/SKILL.md` directly.

### Claude Utilities

```bash
aicfg claude find-session "deploy"         # search recent sessions for keywords
aicfg claude find-session "error" --most-recent=20
aicfg claude find-session "deploy" "cloud run" --all   # AND match
```

### MCP Servers

```bash
aicfg mcp add --self                       # register aicfg's own MCP server
aicfg mcp add --command some-mcp --name my-server
aicfg mcp add --path /path/to/repo         # auto-discover from pyproject.toml
aicfg mcp list
aicfg mcp show aicfg                       # details + health check
aicfg mcp remove my-server
```

### Gemini Slash Commands

```bash
aicfg cmds list                            # list with sync status
aicfg cmds add my-fix "Fix: {{context}}"   # create locally
aicfg cmds publish my-fix                  # promote to repo registry
aicfg cmds install commitall               # install from registry
```

### Context Files

```bash
aicfg context status                       # check CLAUDE.md / GEMINI.md state
aicfg context unify --scope user           # merge into shared CONTEXT.md
```

### Settings

```bash
aicfg settings list
aicfg paths list                           # context.includeDirectories
aicfg allowed-tools list                   # tools.allowed
```

## Architecture

- **SDK-first** — all logic in `src/aicfg/sdk/`. CLI and MCP server are thin wrappers.
- **Skills** — standard agentskills.io format, copied as-is from git-hosted marketplaces. No transformation.
- **Marketplace cache** — `~/.cache/ai-common/skills/marketplaces/`. Cloned without `.git`, 5-minute TTL.
- **Scope convention** — `user` = `~/.gemini/settings.json`, `project` = `./.gemini/settings.json`

## Development

```bash
make test      # run unit tests (network blocked, isolated via env vars)
make install   # pipx install in editable mode
make clean     # remove build artifacts
```

## Prerequisites

- Python 3.10+
- pipx
- Claude Code and/or Gemini CLI
