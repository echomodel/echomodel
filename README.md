# aicfg - AI Assistant Configuration Manager

A Python CLI for managing configuration across AI coding assistants (Gemini CLI, Claude Code). Centralizes slash commands, MCP servers, context files, and settings.

## Quick Start

After cloning this repository:

```bash
# 1. Install globally via pipx (recommended for daily use)
pipx install -e . --force

# 2. Verify installation
aicfg --help
```

### Register with Gemini CLI

Register aicfg as an MCP server so Gemini CLI can use its tools:

```bash
# Register aicfg's MCP server in your user settings
aicfg mcp add --self

# Verify registration and health
aicfg mcp show aicfg
```

You should see `✓ HEALTHY` with server version info.

### Safe Commands to Explore

```bash
# List your slash commands
aicfg cmds list

# Show MCP servers (project + user scopes)
aicfg mcp list

# Check context file status
aicfg context status

# Show current settings
aicfg settings list
```

## Running Tests

The simplest way:

```bash
make test
```

### What `make test` Does (Manual Steps)

For transparency, here's what happens under the hood:

```bash
# 1. Create virtual environment (if needed)
python3 -m venv .venv

# 2. Install package in editable mode with dev dependencies
.venv/bin/pip install -e .[dev]

# 3. Run pytest
.venv/bin/pytest tests
```

Tests run with network I/O blocked by default (except `tests/integration/`).

## Command Groups

| Group | Purpose |
|-------|---------|
| `aicfg skills` | Cross-platform skill management (marketplace, install, list) |
| `aicfg claude` | Claude Code utilities (find-session) |
| `aicfg cmds` | Manage Gemini slash commands (TOML files) |
| `aicfg mcp` | Register/list/remove MCP servers |
| `aicfg context` | Manage context files (CLAUDE.md, GEMINI.md) |
| `aicfg paths` | Manage `context.includeDirectories` |
| `aicfg settings` | Manage aliased Gemini settings |
| `aicfg allowed-tools` | Manage `tools.allowed` list |

### Skills

Install and manage AI agent skills across Claude Code and Gemini CLI from git-hosted marketplaces.

```bash
# Register a skills marketplace
aicfg skills marketplace register my/skills <git-url>

# List all available skills (across all marketplaces + locally installed)
aicfg skills list

# Install a skill to all configured platforms
aicfg skills install nm

# Install to one platform only
aicfg skills install nm --target claude

# Uninstall
aicfg skills uninstall nm

# Show full details
aicfg skills show nm
```

Skills use the [agentskills.io](https://agentskills.io/) open standard. Marketplace repos are also compatible with `gemini skills install` natively.

### Claude Utilities

```bash
# Search recent Claude Code sessions for keywords
aicfg claude find-session "deploy" --most-recent=20
```

### Slash Commands

```bash
# List commands with status (Private, Available, Published, Dirty)
aicfg cmds list

# Create a new command locally
aicfg cmds add my-fix "Explain this bug: {{context}}"

# Promote to this repository for sharing
aicfg cmds publish my-fix

# Install a command from this repo
aicfg cmds install commitall
```

### MCP Servers

```bash
# Register aicfg itself
aicfg mcp add --self

# Register by command name (must be on PATH)
aicfg mcp add --command some-mcp-server --name my-server

# Register by repository path (auto-discovers *-mcp command)
aicfg mcp add --path /path/to/repo

# List all servers
aicfg mcp list

# Show details + health check for a server
aicfg mcp show aicfg

# Filter by pattern
aicfg mcp list --filter "*consult*"

# Remove a server
aicfg mcp remove my-server
```

### Context Files

Unify CLAUDE.md and GEMINI.md into a single shared context file:

```bash
# Check current state
aicfg context status

# Unify user-level context files
aicfg context unify --scope user

# Analyze context with Gemini (requires GEMINI_API_KEY)
aicfg context analyze user "Summarize my rules"

# Revise context with Gemini
aicfg context revise user "Add a rule about commit messages"
```

## Architecture

- **SDK-first**: All logic lives in `src/aicfg/sdk/`. CLI and MCP are thin wrappers.
- **Skills**: Managed from git-hosted marketplace repos. Copied as-is (standard agentskills.io format, no transformation).
- **Scope convention**: `user` = `~/.gemini/settings.json`, `project` = `./.gemini/settings.json`
- **No secrets**: This repo contains no local state, auth tokens, or absolute paths.

## Development

```bash
# Run tests
make test

# Install globally (editable mode via pipx)
make install

# Clean build artifacts
make clean
```

## Prerequisites

- Python 3.10+
- pipx (for global installation)
- Gemini CLI (for MCP integration)

## Related

- [agentic-consult](https://github.com/krisrowe/agentic-consult) - Customer workflow automation with MCP server
- [gworkspace-access](https://github.com/krisrowe/gworkspace-access) - Google Workspace CLI/SDK
