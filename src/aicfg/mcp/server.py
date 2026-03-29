import json
import logging
from typing import Any, Optional
from mcp.server.fastmcp import FastMCP
from aicfg.sdk import commands as cmds_sdk
from aicfg.sdk import settings as settings_sdk
from aicfg.sdk import mcp_setup as mcp_sdk
from aicfg.sdk import skills as skills_sdk

logger = logging.getLogger(__name__)
mcp = FastMCP("aicfg")

@mcp.tool()
async def add_slash_command(
    name: str,
    prompt: str,
    description: Optional[str] = None,
    namespace: Optional[str] = None
) -> dict[str, Any]:
    """
    Add a new slash command to the local configuration.
    
    Args:
        name: Command name (e.g. 'fix-bug')
        prompt: The prompt text for the command
        description: Short description
        namespace: Optional namespace (subdirectory) for the command
    """
    try:
        path = cmds_sdk.add_command(name, prompt, description, namespace=namespace)
        return {"success": True, "path": str(path), "status": "PRIVATE"}
    except Exception as e:
        logger.error(f"Error adding command: {e}")
        return {"error": str(e)}

@mcp.tool()
async def publish_slash_command(name: str) -> dict[str, Any]:
    """
    Publish a local slash command to the common configuration registry.
    
    Args:
        name: The name of the command to publish (e.g., 'fix-bug').
    """
    try:
        registry_path = cmds_sdk.publish_command(name)
        return {
            "success": True, 
            "registry_path": str(registry_path), 
            "status": "PUBLISHED",
            "message": f"Command '{name}' published to registry. Remember to commit changes in gemini-common-config."
        }
    except Exception as e:
        logger.error(f"Error publishing command: {e}")
        return {"error": str(e)}

@mcp.tool()
async def get_slash_command(name: str) -> dict[str, Any]:
    """
    Retrieve the full definition of a slash command.
    
    Args:
        name: The name of the command to retrieve.
    """
    try:
        command = cmds_sdk.get_command(name)
        if command:
            return {"name": name, "definition": command}
        return {"error": f"Command '{name}' not found."}
    except Exception as e:
        logger.error(f"Error getting command: {e}")
        return {"error": str(e)}

@mcp.tool()
async def list_mcp_servers(
    scope: Optional[str] = None,
    filter_pattern: Optional[str] = None
) -> dict[str, Any]:
    """
    List all registered MCP servers with optional filtering.

    Args:
        scope: Optional scope filter ('user' or 'project'). Default shows all scopes.
        filter_pattern: Optional wildcard pattern to match against any output
                        column (scope, name, command/url). Case-insensitive.

    Returns:
        Dict with:
          - servers: List of {name, scope, config} entries
          - filters: Dict of active filters (scope, pattern) or None if no filters
    """
    try:
        return mcp_sdk.list_mcp_servers(scope=scope, filter_pattern=filter_pattern)
    except Exception as e:
        logger.error(f"Error listing MCP servers: {e}")
        return {"error": str(e)}

@mcp.tool()
async def list_slash_commands(filter_pattern: Optional[str] = None) -> dict[str, Any]:
    """
    List all available slash commands and their status.
    
    Args:
        filter_pattern: Optional shell-style wildcard pattern to filter by name (e.g. "commit*").

    Note: When presenting these to the user, it is recommended to use the following 'Icon [space] Scope Name' format for clarity:
    - 👤 User
    - ☁️ Registry
    - 🏠 Project
    """
    try:
        results = cmds_sdk.list_commands(filter_pattern=filter_pattern)
        return {"commands": results}
    except Exception as e:
        return {"error": str(e)}

# NOTE: add_context_path intentionally not exposed as MCP tool.
# See DESIGN.md "Context Include Paths (CLI-only)" for rationale.

@mcp.tool()
async def check_mcp_server_startup(command: str, args: Optional[list[str]] = None) -> dict[str, Any]:
    """
    Smoke test an MCP server command to see if it starts up correctly (STDIO).
    
    This is the best way to verify if an MCP server command is working or not if you've 
    already confirmed that it's registered with the agent (e.g. via 'gemini mcp list') 
    and you are seeing it listed with an unhealthy status (e.g. Disconnected).
    
    If you reference an MCP tool that the agent cannot find, first check the list of 
    registered MCP servers. If one reports unhealth, invoke this tool to diagnose the
    startup issue.
    
    Args:
        command: The command to execute (e.g., 'uv', 'python', 'my-mcp-server').
        args: Optional list of arguments for the command.
    """
    try:
        full_cmd = [command] + (args or [])
        return mcp_sdk.check_mcp_startup(full_cmd)
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
async def skills_marketplaces_list() -> dict[str, Any]:
    """List registered skill marketplaces.

    Marketplaces are git repos containing skill directories (each with a
    SKILL.md file). Each entry returns an alias and the git URL for the
    repo.

    To discover which skills a marketplace provides, use list_skills() —
    each skill result includes a ``source`` field (marketplace alias) and
    ``source_path`` (the skill's directory within the repo).

    To publish a new or updated skill, clone the repo at the returned
    ``url``, add or update the skill folder at the path shown by
    ``source_path`` from list_skills()/get_skill(), commit, and push.

    Returns:
        marketplaces: List of {alias, url} entries.
    """
    try:
        results = skills_sdk.marketplace_list()
        return {"marketplaces": results}
    except Exception as e:
        logger.error(f"Error listing marketplaces: {e}")
        return {"error": str(e)}

@mcp.tool()
async def list_skills(
    installed: Optional[str] = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """List skills from all registered marketplaces and locally installed.

    For installed skills, the source field comes from the install manifest
    (where the skill was actually installed from), not from marketplace
    name matching.

    Each skill result includes:
      - name: Skill name.
      - description: Short description from SKILL.md frontmatter.
      - effective_targets: Platforms this skill supports (['claude', 'gemini']).
      - installed: {platform: bool} showing install status per platform.
      - source: For installed skills, the marketplace alias from the
                install manifest. For available skills, the marketplace
                where the skill was found. '-' if unknown.
      - source_path: Path to the skill directory within the marketplace
                     repo. Use with skills_marketplaces_list() url to
                     locate the skill in its source repo for updates.
      - status (str, installed skills only): One of:
          'current'   — matches manifest and marketplace source.
          'modified'  — locally edited since install.
          'outdated'  — marketplace has newer content.
          'conflict'  — both modified locally and outdated.
          'untracked' — installed but no manifest entry.

    Args:
        installed: Filter by install status. None (default) shows all.
                   'any' = installed on at least one platform.
                   'none' = not installed anywhere.
                   'claude' = installed on claude.
                   'gemini' = installed on gemini.
        refresh: Force refresh of marketplace cache (5-minute TTL)
                 before reading. Avoid refreshing on every call.
    """
    try:
        results = skills_sdk.list_skills(installed=installed, refresh=refresh)
        return {"skills": results}
    except Exception as e:
        logger.error(f"Error listing skills: {e}")
        return {"error": str(e)}

@mcp.tool()
async def get_skill(name: str, refresh: bool = False) -> dict[str, Any]:
    """Get full details of a skill including metadata and instructions.

    For installed skills, includes on-disk document info, manifest
    provenance, and per-marketplace details with status comparison.

    Marketplace data comes from local cache (5-minute TTL). Use
    refresh=True to force a cache update. Avoid refreshing on every call.

    Args:
        name: The skill name (e.g. 'find-session')
        refresh: Force refresh of marketplace cache before reading.
    """
    try:
        result = skills_sdk.get_skill(name, refresh=refresh)
        if result:
            return result
        return {"error": f"Skill '{name}' not found."}
    except Exception as e:
        logger.error(f"Error getting skill: {e}")
        return {"error": str(e)}

@mcp.tool()
async def install_skill(name: str, platform: Optional[str] = None) -> dict[str, Any]:
    """Install a skill to configured platforms.

    Copies SKILL.md as-is from the marketplace source and records
    provenance in the install manifest.

    Result codes:
      - newly_installed: First install, no prior manifest entry.
      - content_updated: Source SKILL.md hash differs from manifest hash
        (hash-based, not version-based).
      - document_unchanged: Source SKILL.md hash matches manifest hash.
        Skill directory is still copied to targets regardless.
      - failed: Installation did not succeed.

    Response includes:
      - success (bool)
      - result (str): One of the result codes above.
      - installed (dict): Provenance — ref, source, url, path,
        document {version, hash, length}.
      - previous (dict, omitted for newly_installed/failed): Prior
        provenance — ref, source, url, path, installed_at, dirty (bool),
        document {version, hash, length}. When dirty is true, document
        reflects live disk state; provenance fields come from manifest.
      - targets (list[str]): Platform directories where skill was copied.
      - message (str): Human-readable summary.

    Args:
        name: Skill name (e.g. 'find-session'), optionally prefixed
              with marketplace alias (e.g. 'krisrowe/skills/find-session').
        platform: Platform to install to ('claude' or 'gemini'). Default: all supported.
    """
    return skills_sdk.install_skill(name, platform=platform)

@mcp.tool()
async def uninstall_skill(name: str, platform: Optional[str] = None) -> dict[str, Any]:
    """Uninstall a skill from platforms.

    Args:
        name: The skill name (e.g. 'find-session')
        platform: Optional platform to uninstall from ('claude' or 'gemini'). Default: all.
    """
    try:
        removed = skills_sdk.uninstall_skill(name, platform=platform)
        return {"success": True, "removed": removed}
    except Exception as e:
        logger.error(f"Error uninstalling skill: {e}")
        return {"error": str(e)}

@mcp.tool()
async def publish_skill(
    name: str,
    platform: Optional[str] = None,
    marketplace: Optional[str] = None,
    path: Optional[str] = None,
    source_path: Optional[str] = None,
    message: Optional[str] = None,
) -> dict[str, Any]:
    """Publish a local skill to a marketplace git repo.

    Clones the marketplace repo, copies the skill directory in, commits,
    and pushes. Updates the local install manifest and invalidates the
    marketplace cache.

    The ``path`` parameter determines where the skill lands in the repo.
    This aligns with ``gemini skills install <url> --path <path>`` so
    the same repo works with both aicfg and native Gemini CLI. Claude
    Code has no native skill CLI; aicfg copies SKILL.md to
    ~/.claude/skills/<name>/SKILL.md directly.

    Result codes:
      - published: Committed and pushed successfully.
      - no_changes: Skill matches what's already in the repo.
      - failed: Publish did not succeed.

    The response includes a ``git_ops`` list recording each git command
    executed in order, with exit codes and combined output. This provides
    transparency into the publish process. ``git_ops`` is for review and
    debugging — do not couple application logic to its structure or
    contents. Use the structured fields (success, result, ref, message)
    for control flow.

    Args:
        name: Skill name (must exist locally or at source_path).
        platform: Which platform's installed copy to use ('claude' or
                  'gemini'). Auto-detected if omitted. Cannot be used
                  with source_path.
        marketplace: Target marketplace alias. Defaults to manifest
                     source. Required for skills with no manifest entry.
        path: Destination path within the repo (e.g. 'coding/my-skill').
              Maps to --path arg of 'gemini skills install'. Defaults
              to manifest path or skill name.
        source_path: Absolute path to a local skill directory. For skills
                     not installed to any platform. Cannot be used with
                     platform.
        message: Git commit message. Default: 'Publish skill: <name>'.
    """
    return skills_sdk.publish_skill(
        name, platform=platform, marketplace=marketplace,
        path=path, source_path=source_path, message=message,
    )

@mcp.resource("aicfg://commands")
async def commands_resource() -> str:
    """List of all slash commands as a JSON resource."""
    results = cmds_sdk.list_commands()
    return json.dumps(results, indent=2)

def run_server():
    mcp.run()

if __name__ == "__main__":
    run_server()