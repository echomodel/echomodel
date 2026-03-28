"""SDK for managing cross-tool AI agent skills."""

import shutil
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from aicfg.sdk.config import (
    get_claude_skills_dir,
    get_gemini_skills_dir,
    get_marketplace_cache_dir,
)

SUPPORTED_PLATFORMS = {"claude", "gemini"}
FETCH_TIMEOUT = 5
CACHE_TTL_SECONDS = 300  # 5 minutes


# --- Marketplace management ---
# Marketplaces are git repos cached under ~/.cache/ai-common/skills/marketplaces/<slug>/
# Each cache dir contains a .marketplace file (line 1: alias, line 2: url).

MARKETPLACE_META_FILE = ".marketplace"


def _marketplace_cache_path(alias: str) -> Path:
    slug = alias.replace("/", "~")
    return get_marketplace_cache_dir() / slug


def _read_marketplace_meta(cache_path: Path) -> Optional[tuple[str, str]]:
    """Read alias and url from .marketplace file. Returns (alias, url) or None."""
    meta_file = cache_path / MARKETPLACE_META_FILE
    if not meta_file.exists():
        return None
    lines = meta_file.read_text().strip().splitlines()
    if len(lines) < 2:
        return None
    return lines[0], lines[1]


def _write_marketplace_meta(cache_path: Path, alias: str, url: str):
    meta_file = cache_path / MARKETPLACE_META_FILE
    meta_file.write_text(f"{alias}\n{url}\n")


def _list_registered_marketplaces() -> list[dict]:
    """Discover all registered marketplaces from cache directory."""
    cache_root = get_marketplace_cache_dir()
    if not cache_root.is_dir():
        return []
    results = []
    for entry in sorted(cache_root.iterdir()):
        if not entry.is_dir():
            continue
        meta = _read_marketplace_meta(entry)
        if meta:
            results.append({"alias": meta[0], "url": meta[1], "path": entry})
    return results


def _fetch_marketplace(alias: str, url: str) -> tuple[Path, bool, str]:
    """Fetch/update a marketplace. Clones to /tmp, strips .git, swaps into cache.
    Skips fetch if cache is less than CACHE_TTL_SECONDS old.
    Returns (cache_path, from_cache, message)."""
    import tempfile
    import time

    cache_path = _marketplace_cache_path(alias)

    meta_file = cache_path / MARKETPLACE_META_FILE
    if meta_file.exists():
        age = time.time() - meta_file.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            return cache_path, True, f"cache fresh ({int(age)}s old)"

    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="aicfg-marketplace-"))
        clone_path = tmp_dir / "repo"
        subprocess.run(
            ["git", "clone", "-q", "--depth=1", url, str(clone_path)],
            timeout=FETCH_TIMEOUT, capture_output=True, check=True,
        )
        shutil.rmtree(clone_path / ".git")
        _write_marketplace_meta(clone_path, alias, url)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists():
            shutil.rmtree(cache_path)
        shutil.copytree(clone_path, cache_path)

        return cache_path, False, "updated"
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        if cache_path.exists():
            return cache_path, True, "using cached version (fetch timed out or failed)"
        raise ValueError(f"Fetch failed for {alias} ({url}) and no cache available")
    finally:
        if tmp_dir and tmp_dir.exists():
            shutil.rmtree(tmp_dir)


def marketplace_register(alias: str, url: str) -> dict:
    """Register a marketplace by cloning it."""
    cache_path = _marketplace_cache_path(alias)
    if cache_path.exists() and _read_marketplace_meta(cache_path):
        raise ValueError(f"Marketplace '{alias}' already registered")
    _fetch_marketplace(alias, url)
    return {"alias": alias, "url": url}


def marketplace_remove(alias: str) -> dict:
    """Remove a registered marketplace."""
    cache_path = _marketplace_cache_path(alias)
    if not cache_path.exists() or not _read_marketplace_meta(cache_path):
        raise ValueError(f"Marketplace '{alias}' not found")
    shutil.rmtree(cache_path)
    return {"alias": alias, "removed": True}


def marketplace_list() -> list[dict]:
    """List registered marketplaces."""
    return [{"alias": mp["alias"], "url": mp["url"]} for mp in _list_registered_marketplaces()]


# --- SKILL.md parsing ---

def parse_skill_md(path: Path) -> tuple[dict, str]:
    """Parse a SKILL.md file into frontmatter dict and body string."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return frontmatter, body


def validate_skill_meta(meta: dict) -> list[str]:
    """Validate skill frontmatter. Returns list of errors (empty = valid)."""
    errors = []
    if not meta.get("name"):
        errors.append("Missing required field: name")
    if not meta.get("description"):
        errors.append("Missing required field: description")
    return errors


# --- Platform helpers ---

def resolve_effective_targets(meta: dict) -> set[str]:
    """Determine which platforms a skill targets.
    TODO: Move only/exclude to .marketplace files instead of SKILL.md frontmatter."""
    if "only" in meta:
        return set(meta["only"])
    if "exclude" in meta:
        return SUPPORTED_PLATFORMS - set(meta["exclude"])
    return SUPPORTED_PLATFORMS.copy()


def detect_configured_platforms() -> set[str]:
    """Detect which platforms are configured on this machine."""
    platforms = set()
    if get_claude_skills_dir().parent.exists():
        platforms.add("claude")
    if get_gemini_skills_dir().parent.exists():
        platforms.add("gemini")
    return platforms


def _get_platform_install_dir(platform: str) -> Path:
    if platform == "claude":
        return get_claude_skills_dir()
    elif platform == "gemini":
        return get_gemini_skills_dir()
    raise ValueError(f"Unknown platform: {platform}")


def get_installed_status(name: str) -> dict[str, bool]:
    """Check if a skill is installed on each platform."""
    return {
        "claude": (get_claude_skills_dir() / name / "SKILL.md").exists(),
        "gemini": (get_gemini_skills_dir() / name / "SKILL.md").exists(),
    }


# --- Marketplace skill scanning ---

def _scan_skills_dir(skills_dir: Path, source_name: str, max_depth: int = 3) -> list[dict]:
    """Scan a directory recursively for skills. Returns list of skill metadata dicts."""
    results = []
    if not skills_dir.is_dir():
        return results

    def _scan(directory: Path, depth: int):
        if depth > max_depth:
            return
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                meta, _ = parse_skill_md(skill_md)
                errors = validate_skill_meta(meta)
                if errors:
                    continue
                name = meta["name"]
                results.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "effective_targets": sorted(resolve_effective_targets(meta)),
                    "installed": get_installed_status(name),
                    "source": source_name,
                    "source_path": str(entry),
                })
            else:
                _scan(entry, depth + 1)

    _scan(skills_dir, 0)
    return results


def _get_all_marketplace_skills() -> list[dict]:
    """Scan all registered marketplaces for skills (using cache only, no fetch)."""
    all_skills = []
    for mp in _list_registered_marketplaces():
        all_skills.extend(_scan_skills_dir(mp["path"], mp["alias"]))
    return all_skills


def _discover_installed_skills() -> dict[str, dict[str, bool]]:
    """Discover all skills installed on this machine, keyed by name."""
    installed = {}
    for platform, skills_dir in [("claude", get_claude_skills_dir()), ("gemini", get_gemini_skills_dir())]:
        if not skills_dir.is_dir():
            continue
        for skill_dir in skills_dir.iterdir():
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            name = skill_dir.name
            if name not in installed:
                installed[name] = {"claude": False, "gemini": False}
            installed[name][platform] = True
    return installed


# --- Public API ---

def list_skills(
    target: Optional[str] = None,
    installed: Optional[bool] = None,
) -> list[dict]:
    """List skills from all sources (marketplaces + locally installed)."""
    seen_names = set()
    results = []

    for skill in _get_all_marketplace_skills():
        name = skill["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        if target and target not in skill["effective_targets"]:
            continue
        if installed is True and not any(skill["installed"].values()):
            continue
        if installed is False and any(skill["installed"].values()):
            continue

        results.append(skill)

    all_installed = _discover_installed_skills()
    for name, status in sorted(all_installed.items()):
        if name in seen_names:
            continue

        desc = ""
        for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
            skill_md = platform_dir / name / "SKILL.md"
            if skill_md.exists():
                meta, _ = parse_skill_md(skill_md)
                desc = meta.get("description", "")
                break

        effective_targets = sorted(SUPPORTED_PLATFORMS)

        if target and target not in effective_targets:
            continue
        if installed is True and not any(status.values()):
            continue
        if installed is False and any(status.values()):
            continue

        results.append({
            "name": name,
            "description": desc,
            "effective_targets": effective_targets,
            "installed": status,
            "source": "-",
        })

    return results


def get_skill(name: str) -> Optional[dict]:
    """Get full details of a skill by name. Searches marketplaces first."""
    for skill in _get_all_marketplace_skills():
        if skill["name"] == name:
            source_path = Path(skill["source_path"])
            meta, body = parse_skill_md(source_path / "SKILL.md")
            skill["meta"] = meta
            skill["body"] = body
            return skill

    for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
        skill_md = platform_dir / name / "SKILL.md"
        if skill_md.exists():
            meta, body = parse_skill_md(skill_md)
            return {
                "name": meta.get("name", name),
                "description": meta.get("description", ""),
                "effective_targets": sorted(SUPPORTED_PLATFORMS),
                "installed": get_installed_status(name),
                "source": "-",
                "meta": meta,
                "body": body,
            }

    return None


def _find_skill_source(name: str, marketplace_filter: Optional[str] = None) -> tuple[Optional[Path], Optional[str], str]:
    """Find a skill's source directory across marketplaces.
    Returns (source_dir, marketplace_alias, url_or_empty).
    Raises ValueError on collision.
    """
    matches = []
    for mp in _list_registered_marketplaces():
        if marketplace_filter and not mp["alias"].startswith(marketplace_filter):
            continue
        for skill in _scan_skills_dir(mp["path"], mp["alias"]):
            if skill["name"] == name:
                matches.append((Path(skill["source_path"]), mp["alias"], mp["url"]))

    if len(matches) > 1:
        sources = [f"  {alias}/{name}" for _, alias, _ in matches]
        raise ValueError(
            f"'{name}' found in multiple marketplaces:\n"
            + "\n".join(sources)
            + f"\nSpecify: aicfg skills install <marketplace>/{name}"
        )
    if matches:
        return matches[0]
    return None, None, ""


def install_skill(name: str, target: Optional[str] = None) -> dict:
    """Install a skill to configured platforms. Returns result dict.
    Copies the SKILL.md as-is — no transformation."""
    marketplace_filter = None
    if "/" in name:
        parts = name.split("/", 1)
        marketplace_filter = parts[0]
        name = parts[1]

    fetch_messages = []
    for mp in _list_registered_marketplaces():
        if marketplace_filter and not mp["alias"].startswith(marketplace_filter):
            continue
        try:
            _, from_cache, msg = _fetch_marketplace(mp["alias"], mp["url"])
            fetch_messages.append(f"{mp['alias']}: {msg}")
        except ValueError as e:
            fetch_messages.append(str(e))

    source_dir, source_alias, source_url = _find_skill_source(name, marketplace_filter)
    if source_dir is None:
        raise FileNotFoundError(f"Skill not found: {name}")

    skill_md = source_dir / "SKILL.md"
    meta, _ = parse_skill_md(skill_md)
    errors = validate_skill_meta(meta)
    if errors:
        raise ValueError(f"Invalid skill '{name}': {'; '.join(errors)}")

    effective = resolve_effective_targets(meta)

    if target:
        if target not in effective:
            raise ValueError(
                f"'{name}' does not support {target} "
                f"(effective targets: {', '.join(sorted(effective))})"
            )
        install_targets = {target}
    else:
        install_targets = effective & detect_configured_platforms()

    if not install_targets:
        raise ValueError(f"No configured platforms found for '{name}'")

    installed = []
    for t in sorted(install_targets):
        dest_dir = _get_platform_install_dir(t) / name
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Copy SKILL.md as-is — standard agentskills.io format, no transformation
        shutil.copy2(skill_md, dest_dir / "SKILL.md")
        installed.append(str(dest_dir))

    from_cache = any("cache" in m for m in fetch_messages) if fetch_messages else False

    return {
        "name": name,
        "installed": installed,
        "source": source_alias or "-",
        "url": source_url if source_url else "-",
        "from_cache": from_cache,
        "message": "; ".join(fetch_messages) if fetch_messages else None,
    }


def uninstall_skill(name: str, target: Optional[str] = None) -> list[str]:
    """Uninstall a skill from platforms. Returns list of removed paths."""
    platforms = {target} if target else SUPPORTED_PLATFORMS
    removed = []
    for t in sorted(platforms):
        dest_dir = _get_platform_install_dir(t) / name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
            removed.append(str(dest_dir))
    return removed
