from __future__ import annotations

from pathlib import Path

from runtime_config_store import (
    get_execution_profile,
    get_runtime_config_metadata,
    get_runtime_config_path,
)


def test_runtime_config_uses_profile_specific_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("INTERVIEW_COACH_RUNTIME_CONFIG_PATH", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("INTERVIEW_COACH_PROFILE", "Main Stable")

    path = get_runtime_config_path()

    assert path == tmp_path / "xdg" / "interview-coach" / "profiles" / "main-stable" / "runtime_config.json"
    assert get_execution_profile() == "main-stable"


def test_runtime_config_override_path_wins(monkeypatch, tmp_path: Path) -> None:
    override_path = tmp_path / "custom" / "runtime_config.json"
    monkeypatch.setenv("INTERVIEW_COACH_RUNTIME_CONFIG_PATH", str(override_path))
    monkeypatch.setenv("INTERVIEW_COACH_PROFILE", "ignored-profile")

    assert get_runtime_config_path() == override_path
    metadata = get_runtime_config_metadata()
    assert metadata["config_path"] == str(override_path)
    assert metadata["profile"] == "ignored-profile"
