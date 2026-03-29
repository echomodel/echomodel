"""Tests for skills SDK — marketplace registration, skill listing, install, uninstall."""

import json
import pytest
from pathlib import Path
from aicfg.sdk import skills
from aicfg.sdk.config import get_install_manifest_path


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    """Isolated skills environment with temp dirs for all paths."""
    claude_skills = tmp_path / "claude" / "skills"
    gemini_skills = tmp_path / "gemini" / "skills"
    marketplace_cache = tmp_path / "cache" / "marketplaces"
    manifest_path = tmp_path / "install-manifest.json"
    claude_skills.mkdir(parents=True)
    gemini_skills.mkdir(parents=True)
    marketplace_cache.mkdir(parents=True)

    # Parent dirs must exist for platform detection
    (tmp_path / "claude").mkdir(exist_ok=True)
    (tmp_path / "gemini").mkdir(exist_ok=True)

    monkeypatch.setenv("AICFG_CLAUDE_SKILLS_DIR", str(claude_skills))
    monkeypatch.setenv("AICFG_GEMINI_SKILLS_DIR", str(gemini_skills))
    monkeypatch.setenv("AICFG_MARKETPLACE_CACHE_DIR", str(marketplace_cache))
    monkeypatch.setenv("AICFG_INSTALL_MANIFEST_PATH", str(manifest_path))

    return {
        "claude_skills": claude_skills,
        "gemini_skills": gemini_skills,
        "marketplace_cache": marketplace_cache,
        "manifest_path": manifest_path,
        "tmp": tmp_path,
    }


def _create_skill(base_dir, name, description="A test skill", extra_frontmatter="", body=None):
    """Helper to create a SKILL.md in a directory."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body_text = body or f'Say "{name} working"'
    fm = f"---\nname: {name}\ndescription: \"{description}\"\n{extra_frontmatter}---\n\n{body_text}\n"
    (skill_dir / "SKILL.md").write_text(fm)
    return skill_dir


def _create_marketplace(cache_dir, alias, url, skill_names, ref=None):
    """Helper to create a fake marketplace in the cache dir."""
    slug = alias.replace("/", "~")
    mp_dir = cache_dir / slug
    mp_dir.mkdir(parents=True, exist_ok=True)
    content = f"{alias}\n{url}\n"
    if ref:
        content += f"{ref}\n"
    (mp_dir / ".marketplace").write_text(content)
    for name in skill_names:
        _create_skill(mp_dir, name, description=f"{name} from {alias}")
    return mp_dir


def _read_manifest(env):
    path = env["manifest_path"]
    if not path.exists():
        return {}
    return json.loads(path.read_text())


# --- Marketplace registration ---

def test_marketplace_list_empty(skills_env):
    assert skills.marketplace_list() == []


def test_marketplace_register_and_list(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["s1"]
    )
    result = skills.marketplace_list()
    assert len(result) == 1
    assert result[0]["alias"] == "test/mp"
    assert result[0]["url"] == "https://example.com/mp.git"


def test_marketplace_remove(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["s1"]
    )
    assert len(skills.marketplace_list()) == 1
    skills.marketplace_remove("test/mp")
    assert skills.marketplace_list() == []


def test_marketplace_remove_nonexistent_raises(skills_env):
    with pytest.raises(ValueError, match="not found"):
        skills.marketplace_remove("nonexistent")


# --- Skill listing ---

def test_list_skills_from_marketplace(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["alpha", "beta"],
    )
    result = skills.list_skills()
    names = [s["name"] for s in result]
    assert "alpha" in names
    assert "beta" in names


def test_list_skills_shows_installed_status(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["alpha"]
    )
    _create_skill(skills_env["claude_skills"], "alpha")

    result = skills.list_skills()
    alpha = [s for s in result if s["name"] == "alpha"][0]
    assert alpha["installed"]["claude"] is True
    assert alpha["installed"]["gemini"] is False


def test_list_skills_includes_orphan_installed_skills(skills_env):
    _create_skill(skills_env["claude_skills"], "orphan", description="I have no marketplace")

    result = skills.list_skills()
    orphan = [s for s in result if s["name"] == "orphan"][0]
    assert orphan["source"] == "-"
    assert orphan["installed"]["claude"] is True


def test_list_skills_marketplace_takes_precedence_over_installed(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["shared"]
    )
    _create_skill(skills_env["claude_skills"], "shared")

    result = skills.list_skills()
    shared = [s for s in result if s["name"] == "shared"]
    assert len(shared) == 1


def test_list_skills_recursive_scan(skills_env):
    """Skills nested in collections (subdirectories) are found."""
    mp_dir = skills_env["marketplace_cache"] / "test~mp"
    mp_dir.mkdir(parents=True)
    (mp_dir / ".marketplace").write_text("test/mp\nhttps://example.com/mp.git\n")

    _create_skill(mp_dir / "coding", "deep-skill", description="Nested skill")

    result = skills.list_skills()
    names = [s["name"] for s in result]
    assert "deep-skill" in names


# --- Skill listing: installed filter ---

def test_list_skills_installed_any(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["installed-one", "not-installed"],
    )
    _create_skill(skills_env["claude_skills"], "installed-one")

    result = skills.list_skills(installed="any")
    names = [s["name"] for s in result]
    assert "installed-one" in names
    assert "not-installed" not in names


def test_list_skills_installed_none(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["installed-one", "not-installed"],
    )
    _create_skill(skills_env["claude_skills"], "installed-one")

    result = skills.list_skills(installed="none")
    names = [s["name"] for s in result]
    assert "not-installed" in names
    assert "installed-one" not in names


def test_list_skills_installed_claude(skills_env):
    _create_skill(skills_env["claude_skills"], "claude-only")
    _create_skill(skills_env["gemini_skills"], "gemini-only")

    result = skills.list_skills(installed="claude")
    names = [s["name"] for s in result]
    assert "claude-only" in names
    assert "gemini-only" not in names


def test_list_skills_installed_gemini(skills_env):
    _create_skill(skills_env["claude_skills"], "claude-only")
    _create_skill(skills_env["gemini_skills"], "gemini-only")

    result = skills.list_skills(installed="gemini")
    names = [s["name"] for s in result]
    assert "gemini-only" in names
    assert "claude-only" not in names


def test_list_skills_installed_default_shows_all(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["available"],
    )
    _create_skill(skills_env["claude_skills"], "local-only")

    result = skills.list_skills()
    names = [s["name"] for s in result]
    assert "available" in names
    assert "local-only" in names


# --- Skill listing: manifest-based source ---

def test_list_skills_source_from_manifest(skills_env):
    """Installed skills get source from manifest, not marketplace scanning."""
    _create_marketplace(
        skills_env["marketplace_cache"], "mp-a", "https://example.com/a.git", ["my-skill"]
    )
    # Install from mp-a
    result = skills.install_skill("my-skill")
    assert result["success"]

    # Now register a second marketplace that also has my-skill
    _create_marketplace(
        skills_env["marketplace_cache"], "mp-b", "https://example.com/b.git", ["my-skill"]
    )

    listed = skills.list_skills()
    my_skill = [s for s in listed if s["name"] == "my-skill"][0]
    # Source should come from manifest (mp-a), not from marketplace scanning
    assert my_skill["source"] == "mp-a"


# --- Skill install ---

def test_install_skill_to_both_platforms(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    result = skills.install_skill("my-skill")
    assert result["success"] is True
    assert result["result"] == "newly_installed"
    assert len(result["targets"]) == 2
    assert (skills_env["claude_skills"] / "my-skill" / "SKILL.md").exists()
    assert (skills_env["gemini_skills"] / "my-skill" / "SKILL.md").exists()


def test_install_skill_to_single_target(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    result = skills.install_skill("my-skill", target="claude")
    assert result["success"] is True
    assert len(result["targets"]) == 1
    assert (skills_env["claude_skills"] / "my-skill" / "SKILL.md").exists()
    assert not (skills_env["gemini_skills"] / "my-skill" / "SKILL.md").exists()


def test_install_skill_copies_file_unchanged(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill", target="claude")

    source = skills_env["marketplace_cache"] / "test~mp" / "my-skill" / "SKILL.md"
    installed = skills_env["claude_skills"] / "my-skill" / "SKILL.md"
    assert source.read_text() == installed.read_text()


def test_install_skill_not_found_returns_failed(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["other"]
    )

    result = skills.install_skill("nonexistent")
    assert result["success"] is False
    assert result["result"] == "failed"
    assert "not found" in result["message"].lower()


def test_install_skill_collision_returns_failed(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "mp1", "https://example.com/1.git", ["dupe"]
    )
    _create_marketplace(
        skills_env["marketplace_cache"], "mp2", "https://example.com/2.git", ["dupe"]
    )

    result = skills.install_skill("dupe")
    assert result["success"] is False
    assert result["result"] == "failed"
    assert "multiple marketplaces" in result["message"].lower()


def test_install_skill_with_marketplace_prefix(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "mp1", "https://example.com/1.git", ["skill-a"]
    )
    _create_marketplace(
        skills_env["marketplace_cache"], "mp2", "https://example.com/2.git", ["skill-a"]
    )

    result = skills.install_skill("mp1/skill-a", target="claude")
    assert result["success"] is True
    assert len(result["targets"]) == 1
    assert result["installed"]["source"] == "mp1"


# --- Install manifest ---

def test_install_writes_manifest(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["my-skill"], ref="abc1234",
    )

    skills.install_skill("my-skill")

    manifest = _read_manifest(skills_env)
    assert "my-skill" in manifest
    entry = manifest["my-skill"]
    assert entry["source"] == "test/mp"
    assert entry["url"] == "https://example.com/mp.git"
    assert entry["ref"] == "abc1234"
    assert "hash" in entry["document"]
    assert "length" in entry["document"]
    assert "installed_at" in entry


def test_install_newly_installed_has_no_previous(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    result = skills.install_skill("my-skill")
    assert result["result"] == "newly_installed"
    assert "previous" not in result


def test_reinstall_document_unchanged(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill")
    result = skills.install_skill("my-skill")

    assert result["result"] == "document_unchanged"
    assert "previous" in result
    assert result["previous"]["dirty"] is False


def test_reinstall_content_updated(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill")

    # Modify the source SKILL.md in the marketplace cache
    source_md = skills_env["marketplace_cache"] / "test~mp" / "my-skill" / "SKILL.md"
    source_md.write_text(source_md.read_text() + "\nUpdated content\n")

    result = skills.install_skill("my-skill")

    assert result["result"] == "content_updated"
    assert "previous" in result
    assert result["previous"]["dirty"] is False


def test_reinstall_dirty_detection(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill")

    # Modify the installed copy on disk
    installed_md = skills_env["claude_skills"] / "my-skill" / "SKILL.md"
    installed_md.write_text(installed_md.read_text() + "\nLocal edit\n")

    result = skills.install_skill("my-skill")

    assert result["result"] == "document_unchanged"
    assert result["previous"]["dirty"] is True


def test_reinstall_dirty_and_updated(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill")

    # Modify both source and installed copy
    source_md = skills_env["marketplace_cache"] / "test~mp" / "my-skill" / "SKILL.md"
    source_md.write_text(source_md.read_text() + "\nUpstream change\n")

    installed_md = skills_env["claude_skills"] / "my-skill" / "SKILL.md"
    installed_md.write_text(installed_md.read_text() + "\nLocal edit\n")

    result = skills.install_skill("my-skill")

    assert result["result"] == "content_updated"
    assert result["previous"]["dirty"] is True


def test_reinstall_dirty_previous_document_reflects_disk(skills_env):
    """When dirty, previous.document should reflect the disk state, not manifest."""
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    skills.install_skill("my-skill")
    manifest = _read_manifest(skills_env)
    original_hash = manifest["my-skill"]["document"]["hash"]

    # Modify installed copy
    installed_md = skills_env["claude_skills"] / "my-skill" / "SKILL.md"
    installed_md.write_text(installed_md.read_text() + "\nLocal edit\n")

    result = skills.install_skill("my-skill")

    assert result["previous"]["dirty"] is True
    assert result["previous"]["document"]["hash"] != original_hash


def test_install_manifest_records_ref(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["my-skill"], ref="deadbeef",
    )

    result = skills.install_skill("my-skill")
    assert result["installed"]["ref"] == "deadbeef"

    manifest = _read_manifest(skills_env)
    assert manifest["my-skill"]["ref"] == "deadbeef"


def test_install_manifest_records_path(skills_env):
    """Manifest path should be the skill's relative path within the marketplace."""
    mp_dir = skills_env["marketplace_cache"] / "test~mp"
    mp_dir.mkdir(parents=True)
    (mp_dir / ".marketplace").write_text("test/mp\nhttps://example.com/mp.git\n")
    _create_skill(mp_dir / "coding", "nested-skill", description="Nested")

    result = skills.install_skill("nested-skill")
    assert result["success"]
    # Path should be relative within the marketplace, e.g. "coding/nested-skill"
    assert "coding" in result["installed"]["path"]
    assert "nested-skill" in result["installed"]["path"]


# --- Skill uninstall ---

def test_uninstall_skill_removes_from_both(skills_env):
    _create_skill(skills_env["claude_skills"], "doomed")
    _create_skill(skills_env["gemini_skills"], "doomed")

    removed = skills.uninstall_skill("doomed")
    assert len(removed) == 2
    assert not (skills_env["claude_skills"] / "doomed").exists()
    assert not (skills_env["gemini_skills"] / "doomed").exists()


def test_uninstall_skill_single_target(skills_env):
    _create_skill(skills_env["claude_skills"], "doomed")
    _create_skill(skills_env["gemini_skills"], "doomed")

    removed = skills.uninstall_skill("doomed", target="claude")
    assert len(removed) == 1
    assert not (skills_env["claude_skills"] / "doomed").exists()
    assert (skills_env["gemini_skills"] / "doomed" / "SKILL.md").exists()


def test_uninstall_skill_not_installed_returns_empty(skills_env):
    removed = skills.uninstall_skill("ghost")
    assert removed == []


# --- get_skill ---

def test_get_skill_from_marketplace(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["info-skill"]
    )

    result = skills.get_skill("info-skill")
    assert result is not None
    assert result["name"] == "info-skill"
    assert "body" in result


def test_get_skill_from_installed_when_not_in_marketplace(skills_env):
    _create_skill(skills_env["claude_skills"], "local-only", description="Just local")

    result = skills.get_skill("local-only")
    assert result is not None
    assert result["name"] == "local-only"
    assert result["source"] == "-"


def test_get_skill_source_from_manifest(skills_env):
    """Installed skill's source comes from manifest, not marketplace scan."""
    _create_marketplace(
        skills_env["marketplace_cache"], "orig/mp", "https://example.com/orig.git", ["my-skill"]
    )
    skills.install_skill("my-skill")

    result = skills.get_skill("my-skill")
    assert result["source"] == "orig/mp"


def test_get_skill_not_found(skills_env):
    assert skills.get_skill("nonexistent") is None


# --- Full transaction: register marketplace, list, install, verify, uninstall ---

def test_full_skill_lifecycle(skills_env):
    # Create marketplace with a skill
    _create_marketplace(
        skills_env["marketplace_cache"], "life/cycle", "https://example.com/lc.git",
        ["lifecycle-skill"],
    )

    # List — skill appears, not installed
    listed = skills.list_skills()
    lc = [s for s in listed if s["name"] == "lifecycle-skill"][0]
    assert lc["installed"]["claude"] is False
    assert lc["installed"]["gemini"] is False

    # Install
    result = skills.install_skill("lifecycle-skill")
    assert result["success"] is True
    assert result["result"] == "newly_installed"
    assert len(result["targets"]) == 2

    # List — now installed, source from manifest
    listed = skills.list_skills()
    lc = [s for s in listed if s["name"] == "lifecycle-skill"][0]
    assert lc["installed"]["claude"] is True
    assert lc["installed"]["gemini"] is True
    assert lc["source"] == "life/cycle"

    # Show
    detail = skills.get_skill("lifecycle-skill")
    assert detail["body"].strip() == 'Say "lifecycle-skill working"'

    # Uninstall
    removed = skills.uninstall_skill("lifecycle-skill")
    assert len(removed) == 2

    # List — back to not installed
    listed = skills.list_skills()
    lc = [s for s in listed if s["name"] == "lifecycle-skill"][0]
    assert lc["installed"]["claude"] is False
    assert lc["installed"]["gemini"] is False
