# Contributing

## Design Principles

### Skills Inventory: The Central Value

The most important thing aicfg does is answer the question: **"Which skills
from my tracked marketplaces are installed on THIS machine, for which agent
platform, and which are missing?"**

`aicfg skills list` is the primary interface for this. It must remain fast,
readable, and useful at a glance. Every design decision about marketplaces,
listing, and installation should be evaluated against whether it preserves
or degrades this experience.

### Marketplace Listing Must Stay Manageable

`aicfg skills list` currently shows every skill from every registered
marketplace. As the number of registered marketplaces grows, this output
could become unusable. Any feature that increases the number of skills
surfaced (pre-registered marketplaces, marketplace discovery, bulk
registration) must also address filtering and scoping so the listing
remains actionable.

Potential approaches (not yet implemented):
- Filter by marketplace: `aicfg skills list --marketplace <name>`
- Filter by installed/not-installed (already exists: `--installed`)
- Collapse marketplaces by default, expand on demand
- Default to showing only first-party/primary marketplace

### Pre-Registered Marketplaces: Documentation Only (For Now)

aicfg documentation (README, examples) may reference specific marketplace
repos and use them in examples for marketplace registration and skill
installation. This is documentation, not product coupling — aicfg ships
with no pre-registered marketplaces.

**Future vision:** A marketplace of marketplaces — a discovery mechanism
(possibly GitHub topics, a registry, or curated lists) that lets users
find and bulk-register marketplace sources. This would require:
- Ability to remove or disable marketplaces easily
- Scoped listing so bulk-registered marketplaces don't flood output
- Clear distinction between first-party and third-party sources
- User control over what appears in their default `skills list` view

Until the manageable listing constraint is solved, pre-registration
remains out of scope.

### Skill Portability and the 3+ Alternatives Rule

Skills in general-purpose marketplaces should not hard-depend on tools
that the average consumer is unlikely to have installed. The
[develop-skill](https://github.com/krisrowe/skills/blob/main/coding/develop-skill/SKILL.md)
in the skills marketplace defines a 3+ alternatives pattern: zero-install
baseline, author's own tool, established product. aicfg does not enforce
this — it is a convention for skill authors, not a technical constraint.

### No Transformation

aicfg copies SKILL.md files as-is from marketplace repos. No compilation,
no field stripping, no invented frontmatter. Claude-specific fields pass
through; Gemini ignores them. This is a hard constraint — aicfg is a
delivery mechanism, not a build system.

### Skills and MCP Servers Are Orthogonal

Skills are the knowledge/instruction layer. MCP servers provide tools.
Skills reference MCP tools by name in their prose; the MCP server is
installed and registered separately. aicfg manages both but does not
couple them. A skill that needs an MCP tool says so in its instructions;
it does not declare a package dependency that aicfg resolves.

### Structured Outputs with Operational Transparency

Tool responses must communicate outcomes through conventional, structured
fields at the right level of abstraction for the domain — `success`,
`result`, `ref`, `message`, etc. Callers should never need to parse
underlying script output to determine what happened or make decisions.

At the same time, operations that perform multi-step side effects (such
as `publish_skill` executing clone → add → commit → push) include a
supplemental `git_ops` log: an ordered list of each command executed,
with its arguments, exit code, and combined output. This gives callers
verifiable evidence that each step completed as reported, rather than
requiring them to trust a summary alone.

These two concerns are deliberately separated:

- **Structured fields** are the interface contract. Couple your code to
  these. They are stable and designed for programmatic use.
- **Operational logs** (`git_ops` and similar) are for human review and
  debugging. Do not couple application logic to their structure, order,
  or contents — the underlying commands are an implementation detail
  that may change across versions.

This pattern applies to any tool that orchestrates external operations.
When adding new tools or extending existing ones, ensure the primary
response schema is self-sufficient, and add operational transparency
only as a supplemental, explicitly unstable field.

## Architecture

### SDK-First Design

All business logic lives in `src/aicfg/sdk/`. CLI and MCP server are thin
wrappers that call SDK functions, format output, and handle I/O.

- `sdk/skills.py` — marketplace management, skill install/uninstall/list
- `sdk/sessions.py` — Claude session search
- `sdk/commands.py` — Gemini slash command registry
- `sdk/mcp_setup.py` — MCP server registration
- `sdk/settings.py` — Gemini settings management
- `sdk/context.py` — context file unification
- `sdk/config.py` — path resolution, platform directories

### Path Isolation

All filesystem paths are overridable via environment variables for test
isolation:
- `AICFG_CLAUDE_SKILLS_DIR` — overrides `~/.claude/skills`
- `AICFG_GEMINI_SKILLS_DIR` — overrides `~/.gemini/skills`
- `AICFG_MARKETPLACE_CACHE_DIR` — overrides `~/.cache/ai-common/skills/marketplaces`
- `AICFG_INSTALL_MANIFEST_PATH` — overrides `~/.config/ai-common/skills/install-manifest.json`

### Marketplace Cache

Marketplaces are git repos cloned to `~/.cache/ai-common/skills/marketplaces/`.
Cache has a 5-minute TTL based on `.marketplace` file mtime. Cloned without
`.git` — atomic swap from temp directory to cache path.

### Install Manifest

`install_skill` records provenance in `~/.config/ai-common/skills/install-manifest.json`,
keyed by skill name:

```json
{
  "my-skill": {
    "ref": "bca5cbf",
    "source": "krisrowe/skills",
    "url": "https://github.com/krisrowe/skills.git",
    "path": "coding/my-skill",
    "document": { "version": "1.0", "hash": "a1b2c3d4", "length": 2840 },
    "installed_at": "2026-03-28T14:30:00Z"
  }
}
```

The manifest is the authoritative source of provenance for installed skills.
`list_skills()` and `get_skill()` use the manifest `source` field for installed
skills rather than inferring source from marketplace name matching.

### Install Result Codes

`install_skill` returns a `result` field with one of:

- **`newly_installed`** — No prior manifest entry. `previous` omitted from response.
- **`content_updated`** — Source SKILL.md hash differs from manifest hash.
  Hash-based, not version-based — a skill can be `content_updated` even if
  the version number is unchanged or absent.
- **`document_unchanged`** — Source SKILL.md hash matches manifest hash.
  The skill directory is still copied to targets regardless.
- **`failed`** — Installation did not succeed. Returns `{success: false, result: "failed", message}`.

**Naming asymmetry is intentional:** `content_updated` is broad (any change
detected via hash) while `document_unchanged` is specific (SKILL.md hash
matches). An update can be triggered by content changes, but the "unchanged"
determination is based on the primary document hash.

### Dirty Detection

On reinstall, the live on-disk SKILL.md is hashed and compared against the
manifest hash. If they differ, the installed copy was locally modified since
the last install. This is reported as `previous.dirty: true`. When dirty,
`previous.document` reflects the disk state (hash/length from the modified
file), while provenance fields (`ref`, `source`, `installed_at`) come from
the manifest since provenance cannot be derived from disk.

### Marketplace Repo Structure Alignment

Marketplace repos use the same directory structure that `gemini skills install`
expects. This is intentional — a single marketplace repo must work with both
aicfg and the native Gemini CLI without any transformation.

Constraints:

- Skills are directories containing SKILL.md, organized in collections
  (subdirectories like `coding/`, `prompting/`).
- The `path` field in the install manifest and publish_skill maps directly
  to `gemini skills install <url> --path <path>`. Changing the structure
  would break native Gemini CLI compatibility.
- Gemini scans one level deep for skills at root, or within a collection
  specified by `--path`. It does NOT recurse beyond that. aicfg scans
  up to 3 levels deep for flexibility, but marketplace repos should keep
  skills at standard depths for cross-tool compatibility.
- Claude Code has no native skill CLI. aicfg copies SKILL.md directly to
  `~/.claude/skills/<name>/SKILL.md`. The marketplace structure is
  irrelevant to Claude — only the SKILL.md content matters.
- aicfg copies SKILL.md as-is. No compilation, no field stripping, no
  invented frontmatter. Claude-specific fields pass through; Gemini
  ignores unknown fields. This is a hard constraint.

### Publish and Cache Invalidation

`publish_skill` invalidates the marketplace cache for the target marketplace
after a successful push. This ensures subsequent `list_skills`/`get_skill`
calls reflect the published changes without waiting for the 5-minute TTL.
The cache is NOT refreshed (no re-clone) — it is only invalidated so the
next access triggers a fetch.

## Testing

```bash
make test      # sociable unit tests, network blocked, isolated via env vars
```

Tests exercise full transaction flows: register → list → install → verify →
uninstall. All paths isolated via environment variable overrides.
