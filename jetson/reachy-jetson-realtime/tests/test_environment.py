import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("JETSON_REALTIME_RUN_LIVE_TESTS") != "1",
    reason="Jetson hardware checks require JETSON_REALTIME_RUN_LIVE_TESTS=1.",
)


def test_jetson_l4t_release_present() -> None:
    """Jetson Linux should expose the L4T release marker."""
    release_file = Path("/etc/nv_tegra_release")

    assert release_file.exists()
    assert "R39" in release_file.read_text(encoding="utf-8")


def test_work_folder_is_writable() -> None:
    """The checked-out probe folder should be writable by the active user."""
    project_root = Path(__file__).resolve().parents[1]
    probe = project_root / ".write-test"

    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    probe.unlink()
