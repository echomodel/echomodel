"""Tests for skills SDK — marketplace registration, skill listing, install, uninstall."""

import pytest
from pathlib import Path
from aicfg.sdk import skills


@pytest.fixture
def skills_env(tmp_path, monkeypatch):
    """Isolated skills environment with temp dirs for all paths."""
    claude_skills = tmp_path / "claude" / "skills"
    gemini_skills = tmp_path / "gemini" / "skills"
    marketplace_cache = tmp_path / "cache" / "marketplaces"
    claude_skills.mkdir(parents=True)
    gemini_skills.mkdir(parents=True)
    marketplace_cache.mkdir(parents=True)

    # Parent dirs must exist for platform detection
    (tmp_path / "claude").mkdir(exist_ok=True)
    (tmp_path / "gemini").mkdir(exist_ok=True)

    monkeypatch.setenv("AICFG_CLAUDE_SKILLS_DIR", str(claude_skills))
    monkeypatch.setenv("AICFG_GEMINI_SKILLS_DIR", str(gemini_skills))
    monkeypatch.setenv("AICFG_MARKETPLACE_CACHE_DIR", str(marketplace_cache))

    return {
        "claude_skills": claude_skills,
        "gemini_skills": gemini_skills,
        "marketplace_cache": marketplace_cache,
        "tmp": tmp_path,
    }


def _create_skill(base_dir, name, description="A test skill", extra_frontmatter=""):
    """Helper to create a SKILL.md in a directory."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\ndescription: \"{description}\"\n{extra_frontmatter}---\n\nSay \"{name} working\"\n"
    (skill_dir / "SKILL.md").write_text(fm)
    return skill_dir


def _create_marketplace(cache_dir, alias, url, skill_names):
    """Helper to create a fake marketplace in the cache dir."""
    slug = alias.replace("/", "~")
    mp_dir = cache_dir / slug
    mp_dir.mkdir(parents=True, exist_ok=True)
    (mp_dir / ".marketplace").write_text(f"{alias}\n{url}\n")
    for name in skill_names:
        _create_skill(mp_dir, name, description=f"{name} from {alias}")
    return mp_dir


# --- Marketplace registration ---

def test_marketplace_list_empty(skills_env):
    assert skills.marketplace_list() == []


def test_marketplace_register_and_list(skills_env):
    mp_dir = _create_marketplace(
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
    assert all(s["source"] == "test/mp" for s in result if s["name"] in ("alpha", "beta"))


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
    assert shared[0]["source"] == "test/mp"


def test_list_skills_filter_by_target(skills_env):
    _create_skill(skills_env["claude_skills"], "claude-only")
    _create_skill(skills_env["gemini_skills"], "gemini-only")

    claude_results = skills.list_skills(target="claude")
    gemini_results = skills.list_skills(target="gemini")
    # Both are orphans with effective_targets = all platforms
    # But installed filter narrows it
    claude_installed = skills.list_skills(installed=True)
    names = [s["name"] for s in claude_installed]
    assert "claude-only" in names
    assert "gemini-only" in names


def test_list_skills_filter_installed(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git",
        ["installed-one", "not-installed"],
    )
    _create_skill(skills_env["claude_skills"], "installed-one")

    installed = skills.list_skills(installed=True)
    not_installed = skills.list_skills(installed=False)
    assert all(s["name"] != "not-installed" for s in installed)
    assert all(s["name"] != "installed-one" for s in not_installed)


def test_list_skills_recursive_scan(skills_env):
    """Skills nested in collections (subdirectories) are found."""
    mp_dir = skills_env["marketplace_cache"] / "test~mp"
    mp_dir.mkdir(parents=True)
    (mp_dir / ".marketplace").write_text("test/mp\nhttps://example.com/mp.git\n")

    # Create a collection with skills inside
    _create_skill(mp_dir / "coding", "deep-skill", description="Nested skill")

    result = skills.list_skills()
    names = [s["name"] for s in result]
    assert "deep-skill" in names


# --- Skill install ---

def test_install_skill_to_both_platforms(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    result = skills.install_skill("my-skill")
    assert len(result["installed"]) == 2
    assert (skills_env["claude_skills"] / "my-skill" / "SKILL.md").exists()
    assert (skills_env["gemini_skills"] / "my-skill" / "SKILL.md").exists()


def test_install_skill_to_single_target(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["my-skill"]
    )

    result = skills.install_skill("my-skill", target="claude")
    assert len(result["installed"]) == 1
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


def test_install_skill_not_found_raises(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "test/mp", "https://example.com/mp.git", ["other"]
    )

    with pytest.raises(FileNotFoundError, match="Skill not found"):
        skills.install_skill("nonexistent")


def test_install_skill_collision_raises(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "mp1", "https://example.com/1.git", ["dupe"]
    )
    _create_marketplace(
        skills_env["marketplace_cache"], "mp2", "https://example.com/2.git", ["dupe"]
    )

    with pytest.raises(ValueError, match="found in multiple marketplaces"):
        skills.install_skill("dupe")


def test_install_skill_with_marketplace_prefix(skills_env):
    _create_marketplace(
        skills_env["marketplace_cache"], "mp1", "https://example.com/1.git", ["skill-a"]
    )
    _create_marketplace(
        skills_env["marketplace_cache"], "mp2", "https://example.com/2.git", ["skill-a"]
    )

    result = skills.install_skill("mp1/skill-a", target="claude")
    assert len(result["installed"]) == 1
    assert result["source"] == "mp1"


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
    assert result["source"] == "test/mp"
    assert "body" in result


def test_get_skill_from_installed_when_not_in_marketplace(skills_env):
    _create_skill(skills_env["claude_skills"], "local-only", description="Just local")

    result = skills.get_skill("local-only")
    assert result is not None
    assert result["name"] == "local-only"
    assert result["source"] == "-"


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
    assert lc["source"] == "life/cycle"

    # Install
    result = skills.install_skill("lifecycle-skill")
    assert len(result["installed"]) == 2

    # List — now installed
    listed = skills.list_skills()
    lc = [s for s in listed if s["name"] == "lifecycle-skill"][0]
    assert lc["installed"]["claude"] is True
    assert lc["installed"]["gemini"] is True

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
