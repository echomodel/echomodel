"""SDK for managing cross-tool AI agent skills."""

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from aicfg.sdk.config import (
    get_claude_skills_dir,
    get_gemini_skills_dir,
    get_install_manifest_path,
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


def _read_marketplace_meta(cache_path: Path) -> Optional[tuple[str, str, Optional[str]]]:
    """Read alias, url, and optional ref from .marketplace file.
    Returns (alias, url, ref) or None. ref may be None for old-format caches."""
    meta_file = cache_path / MARKETPLACE_META_FILE
    if not meta_file.exists():
        return None
    lines = meta_file.read_text().strip().splitlines()
    if len(lines) < 2:
        return None
    ref = lines[2] if len(lines) >= 3 else None
    return lines[0], lines[1], ref


def _write_marketplace_meta(cache_path: Path, alias: str, url: str, ref: Optional[str] = None):
    meta_file = cache_path / MARKETPLACE_META_FILE
    content = f"{alias}\n{url}\n"
    if ref:
        content += f"{ref}\n"
    meta_file.write_text(content)


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
            results.append({"alias": meta[0], "url": meta[1], "ref": meta[2], "path": entry})
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
        # Capture HEAD ref before stripping .git
        ref_result = subprocess.run(
            ["git", "-C", str(clone_path), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
        )
        ref = ref_result.stdout.strip() if ref_result.returncode == 0 else None
        shutil.rmtree(clone_path / ".git")
        _write_marketplace_meta(clone_path, alias, url, ref=ref)

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


def _invalidate_marketplace_cache(alias: str):
    """Invalidate cache for a specific marketplace so next access re-fetches."""
    import os
    cache_path = _marketplace_cache_path(alias)
    meta_file = cache_path / MARKETPLACE_META_FILE
    if meta_file.exists():
        # Set mtime to epoch so TTL check triggers a re-fetch
        os.utime(meta_file, (0, 0))


def _refresh_all_marketplaces():
    """Force refresh all registered marketplace caches."""
    for mp in _list_registered_marketplaces():
        try:
            _invalidate_marketplace_cache(mp["alias"])
            _fetch_marketplace(mp["alias"], mp["url"])
        except ValueError:
            pass


def marketplace_list() -> list[dict]:
    """List registered skill marketplaces.

    Marketplaces are git repos containing skill directories (each with a
    SKILL.md file). Use list_skills() or get_skill() to see which skills
    each marketplace provides — those results include ``source`` (the
    marketplace alias) and ``source_path`` (the skill's directory path
    within the repo).

    To publish a new or updated skill to a marketplace, clone the repo at
    ``url``, add or update the skill folder at the path shown by
    ``source_path`` from list_skills()/get_skill(), commit, and push.

    Returns:
        List of dicts, each with:
          - alias: Marketplace identifier (e.g. 'krisrowe/skills').
          - url: Git clone URL for the marketplace repo.
    """
    return [{"alias": mp["alias"], "url": mp["url"]} for mp in _list_registered_marketplaces()]


# --- Install manifest ---

def _read_manifest() -> dict:
    """Read the install manifest. Returns {} if missing or malformed."""
    path = get_install_manifest_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(manifest: dict):
    """Write the install manifest, creating parent dirs as needed."""
    path = get_install_manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")


def _hash_file(path: Path) -> str:
    """SHA-256 hash of a file, truncated to 8 hex chars."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def _document_info(skill_md_path: Path, meta: Optional[dict] = None) -> dict:
    """Build document info dict for a SKILL.md file."""
    if meta is None:
        meta, _ = parse_skill_md(skill_md_path)
    return {
        "version": meta.get("version"),
        "hash": _hash_file(skill_md_path),
        "length": skill_md_path.stat().st_size,
    }


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

def _check_status(name: str, manifest: dict, marketplace_hash: Optional[str] = None) -> Optional[str]:
    """Determine the status of an installed skill.

    Compares three hashes: manifest (what was installed), disk (what's on
    disk now), and optionally marketplace (what's in the source repo cache).

    Returns:
        'current'   — disk matches manifest, manifest matches marketplace
        'modified'  — disk differs from manifest (locally edited)
        'outdated'  — marketplace differs from manifest (newer source available)
        'conflict'  — both modified locally and outdated vs marketplace
        'untracked' — installed but no manifest entry
        None        — not installed
    """
    entry = manifest.get(name)
    if not entry:
        # Check if installed at all
        for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
            if (platform_dir / name / "SKILL.md").exists():
                return "untracked"
        return None

    manifest_hash = entry.get("document", {}).get("hash")
    if not manifest_hash:
        return "untracked"

    # Get disk hash
    disk_hash = None
    for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
        disk_md = platform_dir / name / "SKILL.md"
        if disk_md.exists():
            disk_hash = _hash_file(disk_md)
            break

    if disk_hash is None:
        return None

    disk_modified = disk_hash != manifest_hash
    source_changed = marketplace_hash is not None and marketplace_hash != manifest_hash

    if disk_modified and source_changed:
        return "conflict"
    if disk_modified:
        return "modified"
    if source_changed:
        return "outdated"
    return "current"


def _matches_installed_filter(status: dict[str, bool], installed: Optional[str]) -> bool:
    """Check if a skill's install status matches the filter.

    Args:
        status: {platform: bool} install status.
        installed: None (no filter), 'any', 'none', 'claude', or 'gemini'.
    """
    if installed is None:
        return True
    if installed == "any":
        return any(status.values())
    if installed == "none":
        return not any(status.values())
    # Platform-specific: 'claude' or 'gemini'
    return status.get(installed, False)


def list_skills(
    installed: Optional[str] = None,
    refresh: bool = False,
) -> list[dict]:
    """List skills from all registered marketplaces and locally installed.

    For installed skills, the ``source`` field comes from the install
    manifest (where the skill was actually installed from), not from
    marketplace scanning. Marketplace scanning is used only to discover
    skills that are available but not yet installed.

    Marketplace data comes from local cache (5-minute TTL). Use
    refresh=True to force a cache update before reading. Avoid
    refreshing on every call — the cache is designed to be reused.

    Each result includes:
      - name: Skill name.
      - description: Short description from SKILL.md frontmatter.
      - effective_targets: Platforms this skill supports (e.g. ['claude', 'gemini']).
      - installed: Dict of {platform: bool} showing install status per platform.
      - source: For installed skills, the marketplace alias recorded in
                the install manifest. For not-installed skills, the
                marketplace where the skill was found. '-' if unknown.
      - source_path: For not-installed skills, the path within the
                     marketplace cache. For installed skills, the path
                     from the install manifest. Use with
                     marketplace_list() url to locate in the source repo.
      - status (str, present only for installed skills): One of:
          'current'   — matches manifest and marketplace source.
          'modified'  — locally edited since install (disk != manifest).
          'outdated'  — marketplace has newer content (marketplace != manifest).
          'conflict'  — both modified locally and outdated.
          'untracked' — installed but no manifest entry.

    Args:
        installed: Filter by install status. None shows all skills.
                   'any' = installed on at least one platform.
                   'none' = not installed anywhere.
                   'claude' = installed on claude.
                   'gemini' = installed on gemini.
        refresh: Force refresh of marketplace cache before reading.
    """
    if refresh:
        _refresh_all_marketplaces()
    manifest = _read_manifest()
    seen_names = set()
    results = []

    # Pass 1: marketplace skills (available but not installed get marketplace source;
    # installed skills get their source from the manifest)
    for skill in _get_all_marketplace_skills():
        name = skill["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        if not _matches_installed_filter(skill["installed"], installed):
            continue

        # Override source from manifest for installed skills
        is_installed = any(skill["installed"].values())
        if is_installed:
            # Compute marketplace hash before overriding source_path
            mp_hash = None
            mp_md = Path(skill["source_path"]) / "SKILL.md"
            if mp_md.exists():
                mp_hash = _hash_file(mp_md)
            if name in manifest:
                entry = manifest[name]
                skill["source"] = entry.get("source", skill["source"])
                if "path" in entry:
                    skill["source_path"] = entry["path"]
            status = _check_status(name, manifest, marketplace_hash=mp_hash)
            if status:
                skill["status"] = status

        results.append(skill)

    # Pass 2: installed skills not found in any marketplace
    all_installed = _discover_installed_skills()
    for name, status in sorted(all_installed.items()):
        if name in seen_names:
            continue

        if not _matches_installed_filter(status, installed):
            continue

        desc = ""
        for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
            skill_md = platform_dir / name / "SKILL.md"
            if skill_md.exists():
                meta, _ = parse_skill_md(skill_md)
                desc = meta.get("description", "")
                break

        effective_targets = sorted(SUPPORTED_PLATFORMS)

        # Use manifest for source provenance
        source = "-"
        source_path = None
        if name in manifest:
            entry = manifest[name]
            source = entry.get("source", "-")
            source_path = entry.get("path")

        result = {
            "name": name,
            "description": desc,
            "effective_targets": effective_targets,
            "installed": status,
            "source": source,
        }
        if source_path:
            result["source_path"] = source_path
        status = _check_status(name, manifest)
        if status:
            result["status"] = status
        results.append(result)

    return results


def _get_disk_document(name: str) -> Optional[tuple[Path, dict]]:
    """Find the on-disk SKILL.md for an installed skill and return (path, document_info)."""
    for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
        disk_md = platform_dir / name / "SKILL.md"
        if disk_md.exists():
            return disk_md, _document_info(disk_md)
    return None


def _build_marketplace_details(name: str, manifest_entry: Optional[dict]) -> list[dict]:
    """Build per-marketplace detail entries for a skill."""
    manifest_hash = (manifest_entry or {}).get("document", {}).get("hash")
    disk_result = _get_disk_document(name)
    disk_hash = disk_result[1]["hash"] if disk_result else None

    details = []
    for mp in _list_registered_marketplaces():
        for skill in _scan_skills_dir(mp["path"], mp["alias"]):
            if skill["name"] != name:
                continue
            mp_md = Path(skill["source_path"]) / "SKILL.md"
            if not mp_md.exists():
                continue
            mp_doc = _document_info(mp_md)

            # Compute status against this marketplace's version
            if disk_hash is None:
                mp_status = None
            elif manifest_hash is None:
                mp_status = "untracked"
            else:
                disk_modified = disk_hash != manifest_hash
                source_changed = mp_doc["hash"] != manifest_hash
                if disk_modified and source_changed:
                    mp_status = "conflict"
                elif disk_modified:
                    mp_status = "modified"
                elif source_changed:
                    mp_status = "outdated"
                else:
                    mp_status = "current"

            entry = {
                "alias": mp["alias"],
                "url": mp["url"],
                "ref": mp.get("ref"),
                "path": skill["source_path"],
                "document": mp_doc,
            }
            if mp_status:
                entry["status"] = mp_status
            details.append(entry)
    return details


def get_skill(name: str, refresh: bool = False) -> Optional[dict]:
    """Get full details of a skill by name.

    For installed skills, includes on-disk document info, manifest
    provenance, and per-marketplace details with status.

    Marketplace data comes from local cache (5-minute TTL). Use
    refresh=True to force a cache update before reading. Avoid
    refreshing on every call — the cache is designed to be reused.

    Args:
        name: The skill name.
        refresh: Force refresh of marketplace cache before reading.
    """
    if refresh:
        _refresh_all_marketplaces()

    manifest = _read_manifest()
    manifest_entry = manifest.get(name)
    install_status = get_installed_status(name)
    is_installed = any(install_status.values())

    # Find skill metadata — try marketplace first, then installed copies
    meta = None
    body = None
    description = ""

    for skill in _get_all_marketplace_skills():
        if skill["name"] == name:
            mp_md = Path(skill["source_path"]) / "SKILL.md"
            meta, body = parse_skill_md(mp_md)
            description = meta.get("description", "")
            break

    if meta is None:
        for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
            skill_md = platform_dir / name / "SKILL.md"
            if skill_md.exists():
                meta, body = parse_skill_md(skill_md)
                description = meta.get("description", "")
                break

    if meta is None:
        return None

    # Source from manifest for installed skills
    source = "-"
    source_path = None
    if manifest_entry:
        source = manifest_entry.get("source", "-")
        source_path = manifest_entry.get("path")

    result = {
        "name": meta.get("name", name),
        "description": description,
        "effective_targets": sorted(resolve_effective_targets(meta)),
        "installed": install_status,
        "source": source,
        "meta": meta,
        "body": body,
    }
    if source_path:
        result["source_path"] = source_path

    # Add on-disk document info for installed skills
    if is_installed:
        disk_result = _get_disk_document(name)
        if disk_result:
            result["document"] = disk_result[1]

        # Add manifest provenance
        if manifest_entry:
            result["manifest"] = manifest_entry

        # Compute top-level status against manifest source
        mp_hash = None
        marketplace_details = _build_marketplace_details(name, manifest_entry)
        # Find the manifest source marketplace's hash
        if manifest_entry:
            for mp_detail in marketplace_details:
                if mp_detail["alias"] == manifest_entry.get("source"):
                    mp_hash = mp_detail["document"]["hash"]
                    break
        status = _check_status(name, manifest, marketplace_hash=mp_hash)
        if status:
            result["status"] = status

        if marketplace_details:
            result["marketplaces"] = marketplace_details

    return result


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


def _get_source_ref(marketplace_filter: Optional[str] = None) -> Optional[str]:
    """Get the git ref for the marketplace(s) being used."""
    for mp in _list_registered_marketplaces():
        if marketplace_filter and not mp["alias"].startswith(marketplace_filter):
            continue
        if mp.get("ref"):
            return mp["ref"]
    return None


def _relative_source_path(source_dir: Path) -> str:
    """Compute the skill's path relative to its marketplace cache root."""
    cache_root = get_marketplace_cache_dir()
    try:
        rel = source_dir.relative_to(cache_root)
        # Strip the marketplace slug (first component)
        parts = rel.parts[1:]  # e.g. ('test~mp', 'coding', 'my-skill') -> ('coding', 'my-skill')
        return str(Path(*parts)) if parts else source_dir.name
    except ValueError:
        return source_dir.name


def _build_previous(manifest_entry: dict, name: str) -> dict:
    """Build the previous object for a reinstall, including dirty detection."""
    previous = {
        "ref": manifest_entry.get("ref"),
        "source": manifest_entry.get("source"),
        "url": manifest_entry.get("url"),
        "path": manifest_entry.get("path"),
        "installed_at": manifest_entry.get("installed_at"),
    }
    # Check live disk against manifest hash for dirty detection
    manifest_hash = manifest_entry.get("document", {}).get("hash")
    disk_doc = None
    for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
        disk_md = platform_dir / name / "SKILL.md"
        if disk_md.exists():
            disk_doc = _document_info(disk_md)
            break

    if disk_doc and manifest_hash and disk_doc["hash"] != manifest_hash:
        previous["dirty"] = True
        previous["document"] = disk_doc
    else:
        previous["dirty"] = False
        previous["document"] = manifest_entry.get("document", {})

    return previous


def install_skill(name: str, platform: Optional[str] = None) -> dict:
    """Install a skill to configured platforms.

    Copies the SKILL.md as-is from the marketplace source. Writes an
    install manifest entry with provenance so future installs and
    list_skills() can report the actual source.

    Result codes:
      - newly_installed: First install, no prior manifest entry.
      - content_updated: Source SKILL.md hash differs from manifest hash.
        Determined by hash comparison, not version number.
      - document_unchanged: Source SKILL.md hash matches manifest hash.
        Skill directory is still copied to targets regardless.
      - failed: Installation did not succeed.

    Returns dict with:
      - success (bool)
      - result (str): One of the result codes above.
      - installed (dict): Provenance of what was just installed — ref,
        source, url, path, document {version, hash, length}.
      - previous (dict, omitted for newly_installed/failed): Provenance
        of prior install — ref, source, url, path, installed_at, dirty
        (bool), document {version, hash, length}. When dirty is true,
        document reflects the live disk state; provenance fields (ref,
        source, installed_at) come from the manifest.
      - targets (list[str]): Platform directories where skill was copied.
      - message (str): Human-readable summary.
    """
    try:
        marketplace_filter = None
        if "/" in name:
            parts = name.split("/", 1)
            marketplace_filter = parts[0]
            name = parts[1]

        for mp in _list_registered_marketplaces():
            if marketplace_filter and not mp["alias"].startswith(marketplace_filter):
                continue
            try:
                _fetch_marketplace(mp["alias"], mp["url"])
            except ValueError:
                pass

        source_dir, source_alias, source_url = _find_skill_source(name, marketplace_filter)
        if source_dir is None:
            return {"success": False, "result": "failed", "message": f"Skill not found: {name}"}

        skill_md = source_dir / "SKILL.md"
        meta, _ = parse_skill_md(skill_md)
        errors = validate_skill_meta(meta)
        if errors:
            return {"success": False, "result": "failed",
                    "message": f"Invalid skill '{name}': {'; '.join(errors)}"}

        effective = resolve_effective_targets(meta)

        if platform:
            if platform not in effective:
                return {"success": False, "result": "failed",
                        "message": f"'{name}' does not support {platform} "
                                   f"(effective targets: {', '.join(sorted(effective))})"}
            install_targets = {platform}
        else:
            install_targets = effective & detect_configured_platforms()

        if not install_targets:
            return {"success": False, "result": "failed",
                    "message": f"No configured platforms found for '{name}'"}

        # Read manifest for previous install state
        manifest = _read_manifest()
        manifest_entry = manifest.get(name)

        # Build source document info
        source_doc = _document_info(skill_md, meta)
        source_ref = _get_source_ref(marketplace_filter)
        source_path = _relative_source_path(source_dir)

        # Determine result code
        if manifest_entry is None:
            result_code = "newly_installed"
        elif manifest_entry.get("document", {}).get("hash") != source_doc["hash"]:
            result_code = "content_updated"
        else:
            result_code = "document_unchanged"

        # Build previous before overwriting files
        previous = None
        if manifest_entry is not None:
            previous = _build_previous(manifest_entry, name)

        # Copy files to targets
        targets = []
        for t in sorted(install_targets):
            dest_dir = _get_platform_install_dir(t) / name
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(skill_md, dest_dir / "SKILL.md")
            targets.append(str(dest_dir))

        # Write manifest
        installed_info = {
            "ref": source_ref,
            "source": source_alias or "-",
            "url": source_url or "-",
            "path": source_path,
            "document": source_doc,
        }
        manifest[name] = {
            **installed_info,
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_manifest(manifest)

        # Build message
        if result_code == "newly_installed":
            msg = f"{name}: newly installed from {source_alias or 'local'}"
        elif result_code == "content_updated":
            msg = f"{name}: content updated from {source_alias or 'local'}"
            if previous and previous.get("dirty"):
                msg += " (previous was locally modified)"
        else:
            msg = f"{name}: document unchanged"

        response = {
            "success": True,
            "result": result_code,
            "installed": installed_info,
            "targets": targets,
            "message": msg,
        }
        if previous is not None:
            response["previous"] = previous
        return response

    except Exception as e:
        return {"success": False, "result": "failed", "message": str(e)}


def uninstall_skill(name: str, platform: Optional[str] = None) -> list[str]:
    """Uninstall a skill from platforms. Returns list of removed paths."""
    platforms = {platform} if platform else SUPPORTED_PLATFORMS
    removed = []
    for t in sorted(platforms):
        dest_dir = _get_platform_install_dir(t) / name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
            removed.append(str(dest_dir))
    return removed


def publish_skill(
    name: str,
    platform: Optional[str] = None,
    marketplace: Optional[str] = None,
    path: Optional[str] = None,
    source_path: Optional[str] = None,
    message: Optional[str] = None,
) -> dict:
    """Publish a local skill to a marketplace git repo.

    Finds the local skill, clones the marketplace repo, copies the skill
    directory in, commits, and pushes. Updates the local install manifest
    to reflect the new source. Invalidates the marketplace cache so
    subsequent list/get calls pick up the change.

    Marketplace repo structure and path alignment:

        Marketplace repos follow the agentskills.io convention where each
        skill is a directory containing SKILL.md. Skills are organized in
        collections (subdirectories):

            krisrowe/skills/
            ├── coding/
            │   ├── develop-skill/SKILL.md
            │   └── code-reuse/SKILL.md
            └── prompting/
                └── proceed/SKILL.md

        The ``path`` parameter maps to the skill's location within this
        structure. For example, path='coding/my-skill' places the skill
        at coding/my-skill/SKILL.md in the repo.

        This structure is directly compatible with platform-native install
        commands:

          gemini skills install <url> --path coding/my-skill
              Installs one skill from the collection.
          gemini skills install <url> --path coding
              Installs all skills in the coding collection.
          gemini skills install <url>
              Installs all root-level skills (one level deep).

        Claude Code has no native skill CLI — skills are installed by
        copying SKILL.md to ~/.claude/skills/<name>/SKILL.md, which is
        what aicfg skills install does.

    Result codes:
      - published: Skill was committed and pushed successfully.
      - no_changes: Skill content matches what's already in the repo.
      - failed: Publish did not succeed.

    Git operations transparency:

        The response includes a ``git_ops`` list that records every git
        command executed during publish, in order. Each entry captures
        the command name, full argument list, exit code, and combined
        stdout+stderr output. This provides verifiable evidence that
        each step (clone, add, commit, push) completed as reported,
        rather than requiring the caller to trust a summary alone.

        ``git_ops`` is for human review and debugging only. Do not
        couple application logic to its structure, contents, or order —
        the sequence of git operations is an implementation detail that
        may change. Use the structured fields (success, result, ref,
        message) for control flow.

    Args:
        name: Skill name (must exist locally or at source_path).
        platform: Which platform's installed copy to use as source
                  ('claude' or 'gemini'). Auto-detected if omitted.
                  Cannot be used with source_path.
        marketplace: Target marketplace alias. Defaults to the manifest
                     source if the skill was previously installed.
                     Required for skills with no manifest entry.
        path: Destination path within the marketplace repo (e.g.
              'coding/my-skill'). Maps to the --path arg of
              'gemini skills install <url> --path <path>'. Defaults to
              the manifest path if known, or the skill name if new.
        source_path: Absolute path to a local skill directory to publish.
                     Use this for skills not installed to any platform.
                     Cannot be used with platform.
        message: Git commit message. Default: 'Publish skill: <name>'.

    Returns dict with:
      - success (bool)
      - result (str): 'published', 'no_changes', or 'failed'.
      - skill (str): Skill name.
      - marketplace (str): Marketplace alias.
      - url (str): Marketplace git URL.
      - path (str): Path within the repo.
      - ref (str): Git commit SHA (short) after push.
      - git_ops (list[dict]): Ordered list of git operations executed.
        Each entry: {cmd: {name, args}, result: {exit_code, output}}.
      - message (str): Human-readable summary.
    """
    import tempfile

    try:
        if platform and source_path:
            return {"success": False, "result": "failed",
                    "message": "Cannot specify both platform and source_path"}

        # 1. Find the local skill directory
        if source_path:
            local_dir = Path(source_path)
            if not (local_dir / "SKILL.md").exists():
                return {"success": False, "result": "failed",
                        "message": f"No SKILL.md found at {source_path}"}
        else:
            local_dir = _find_local_skill(name, platform)
            if local_dir is None:
                return {"success": False, "result": "failed",
                        "message": f"Skill '{name}' not found locally"}

        # Validate the skill
        skill_md = local_dir / "SKILL.md"
        meta, _ = parse_skill_md(skill_md)
        errors = validate_skill_meta(meta)
        if errors:
            return {"success": False, "result": "failed",
                    "message": f"Invalid skill: {'; '.join(errors)}"}

        # 2. Determine target marketplace
        manifest = _read_manifest()
        manifest_entry = manifest.get(name)

        mp_alias = marketplace
        mp_url = None
        dest_path = path

        if not mp_alias and manifest_entry:
            mp_alias = manifest_entry.get("source")
            if mp_alias == "-":
                mp_alias = None

        if not mp_alias:
            # Try to infer from registered marketplaces
            registered = _list_registered_marketplaces()
            if len(registered) == 1:
                mp_alias = registered[0]["alias"]
            elif len(registered) > 1:
                return {"success": False, "result": "failed",
                        "message": "Multiple marketplaces registered. "
                                   "Specify --marketplace."}
            else:
                return {"success": False, "result": "failed",
                        "message": "No marketplaces registered."}

        # Get marketplace URL
        for mp in _list_registered_marketplaces():
            if mp["alias"] == mp_alias:
                mp_url = mp["url"]
                break
        if not mp_url:
            return {"success": False, "result": "failed",
                    "message": f"Marketplace '{mp_alias}' not found"}

        # Determine destination path within repo
        if not dest_path and manifest_entry and manifest_entry.get("path"):
            dest_path = manifest_entry["path"]
        if not dest_path:
            # Check if skill already exists in this marketplace's cache
            for skill in _scan_skills_dir(_marketplace_cache_path(mp_alias), mp_alias):
                if skill["name"] == name:
                    dest_path = _relative_source_path(Path(skill["source_path"]))
                    break
        if not dest_path:
            dest_path = name

        # 3. Clone, copy, commit, push
        tmp_dir = None
        try:
            tmp_dir = Path(tempfile.mkdtemp(prefix="aicfg-publish-"))
            clone_path = tmp_dir / "repo"
            git_ops = []

            def _run_git(cmd_name, args, **kwargs):
                """Run a git command, record it in git_ops, return result."""
                kwargs.setdefault("timeout", 30)
                r = subprocess.run(
                    args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, **kwargs,
                )
                git_ops.append({
                    "cmd": {"name": cmd_name, "args": args},
                    "result": {"exit_code": r.returncode, "output": r.stdout},
                })
                return r

            def _fail(msg):
                return {"success": False, "result": "failed",
                        "skill": name, "marketplace": mp_alias,
                        "url": mp_url, "path": dest_path,
                        "message": msg, "git_ops": git_ops}

            # Clone
            r = _run_git("clone",
                         ["git", "clone", "--depth=1", mp_url, str(clone_path)])
            if r.returncode != 0:
                return _fail(f"git clone failed: {r.stdout.strip()}")

            # Disable hooks in the cloned repo (publish is automated, not user commits)
            subprocess.run(
                ["git", "-C", str(clone_path), "config", "core.hooksPath", "/dev/null"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )

            # Copy skill directory
            repo_dest = clone_path / dest_path
            if repo_dest.exists():
                shutil.rmtree(repo_dest)
            shutil.copytree(local_dir, repo_dest)

            # Git add
            r = _run_git("add",
                         ["git", "-C", str(clone_path), "add", dest_path])
            if r.returncode != 0:
                return _fail(f"git add failed: {r.stdout.strip()}")

            # Check for changes
            diff_result = subprocess.run(
                ["git", "-C", str(clone_path), "diff", "--cached", "--quiet"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            if diff_result.returncode == 0:
                return {
                    "success": True,
                    "result": "no_changes",
                    "skill": name,
                    "marketplace": mp_alias,
                    "url": mp_url,
                    "path": dest_path,
                    "git_ops": git_ops,
                    "message": f"{name}: no changes to publish",
                }

            # Commit
            commit_msg = message or f"Publish skill: {name}"
            r = _run_git("commit",
                         ["git", "-C", str(clone_path), "commit", "-m", commit_msg])
            if r.returncode != 0:
                return _fail(f"git commit failed: {r.stdout.strip()}")

            # Get ref
            ref_result = subprocess.run(
                ["git", "-C", str(clone_path), "rev-parse", "--short", "HEAD"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )
            ref = ref_result.stdout.strip() if ref_result.returncode == 0 else None

            # Push
            r = _run_git("push",
                         ["git", "-C", str(clone_path), "push"])
            if r.returncode != 0:
                return _fail(f"git push failed: {r.stdout.strip()}")

            # 4. Update manifest
            doc_info = _document_info(skill_md, meta)
            manifest[name] = {
                "ref": ref,
                "source": mp_alias,
                "url": mp_url,
                "path": dest_path,
                "document": doc_info,
                "installed_at": datetime.now(timezone.utc).isoformat(),
            }
            _write_manifest(manifest)

            # 5. Invalidate marketplace cache
            _invalidate_marketplace_cache(mp_alias)

            return {
                "success": True,
                "result": "published",
                "skill": name,
                "marketplace": mp_alias,
                "url": mp_url,
                "path": dest_path,
                "ref": ref,
                "git_ops": git_ops,
                "message": f"Published {name} to {mp_alias}",
            }

        finally:
            if tmp_dir and tmp_dir.exists():
                shutil.rmtree(tmp_dir)

    except Exception as e:
        return {"success": False, "result": "failed", "message": str(e)}


def _find_local_skill(name: str, platform: Optional[str] = None) -> Optional[Path]:
    """Find a locally installed skill directory.

    Args:
        name: Skill name.
        platform: Specific platform to look in. If None, checks claude then gemini.
    """
    if platform:
        skill_dir = _get_platform_install_dir(platform) / name
        if (skill_dir / "SKILL.md").exists():
            return skill_dir
        return None

    for platform_dir in [get_claude_skills_dir(), get_gemini_skills_dir()]:
        skill_dir = platform_dir / name
        if (skill_dir / "SKILL.md").exists():
            return skill_dir
    return None
