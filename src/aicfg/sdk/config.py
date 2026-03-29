import os
import subprocess
from pathlib import Path

# --- Central Path Functions with Environment Variable Overrides ---

def get_user_scoped_gemini_dir() -> Path:
    """
    Returns the user's Gemini config directory.
    Priority: AICFG_USER_DIR env var > ~/.gemini
    """
    path_str = os.environ.get("AICFG_USER_DIR")
    if path_str:
        return Path(path_str)
    return Path.home() / ".gemini"

def get_aicfg_tool_repo_dir() -> Path:
    """
    Returns the root directory of the aicfg tool repository.
    Priority: AICFG_REPO_DIR env var > discovered git root.
    """
    path_str = os.environ.get("AICFG_REPO_DIR")
    if path_str:
        return Path(path_str)
    
    # Discover relative to this file (src/aicfg/sdk/config.py → repo root)
    this_file = Path(__file__).resolve()
    repo_root = this_file.parent.parent.parent.parent
    
    # Validation
    if not (repo_root / ".git").exists() and not os.environ.get("AICFG_SKIP_GIT_CHECK_FOR_TESTS"):
        raise FileNotFoundError(
            f"Could not locate .git directory in discovered repo root: {repo_root}.\n"
            "Ensure 'aicfg' is installed in editable mode from a git repository."
        )
    return repo_root

# --- Derived Paths ---

def get_user_cmds_dir() -> Path:
    """User-scoped commands directory (~/.gemini/commands)."""
    return get_user_scoped_gemini_dir() / "commands"

def get_registry_cmds_dir() -> Path:
    """Registry commands directory (in gemini-common-config)."""
    return get_aicfg_tool_repo_dir() / ".gemini" / "commands"

def get_project_cmds_dir() -> Path:
    """Project-scoped commands directory (./.gemini/commands)."""
    # Allow override for testing
    path_str = os.environ.get("AICFG_PROJECT_DIR")
    if path_str:
        return Path(path_str) / ".gemini" / "commands"

    try:
        root = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL).decode().strip()
        return Path(root) / ".gemini" / "commands"
    except subprocess.CalledProcessError:
        return Path.cwd() / ".gemini" / "commands"

def get_claude_skills_dir() -> Path:
    """Claude Code user skills directory (~/.claude/skills)."""
    path_str = os.environ.get("AICFG_CLAUDE_SKILLS_DIR")
    if path_str:
        return Path(path_str)
    return Path.home() / ".claude" / "skills"

def get_gemini_skills_dir() -> Path:
    """Gemini CLI user skills directory (~/.gemini/skills)."""
    path_str = os.environ.get("AICFG_GEMINI_SKILLS_DIR")
    if path_str:
        return Path(path_str)
    return Path.home() / ".gemini" / "skills"

def get_install_manifest_path() -> Path:
    """Install manifest for skill provenance (~/.config/ai-common/skills/install-manifest.json)."""
    path_str = os.environ.get("AICFG_INSTALL_MANIFEST_PATH")
    if path_str:
        return Path(path_str)
    return Path.home() / ".config" / "ai-common" / "skills" / "install-manifest.json"

def get_marketplace_cache_dir() -> Path:
    """Cache directory for marketplace clones (~/.cache/ai-common/skills/marketplaces)."""
    path_str = os.environ.get("AICFG_MARKETPLACE_CACHE_DIR")
    if path_str:
        return Path(path_str)
    return Path.home() / ".cache" / "ai-common" / "skills" / "marketplaces"

def ensure_dirs():
    """Ensure user command directory exists."""
    get_user_cmds_dir().mkdir(parents=True, exist_ok=True)