"""Persistent settings and OptiLock preset definitions."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_NAME = "DeadlockFovTool"

# Where the configs come from.
GITHUB_OWNER = "dacooderr"
GITHUB_REPO = "OptiLock"
GITHUB_BRANCH = "main"

# Steam application id for Deadlock.
DEADLOCK_APPID = "1422450"


@dataclass(frozen=True)
class Preset:
    """One downloadable config folder inside the OptiLock repository."""

    key: str
    label: str
    folder: str
    gameinfo: str = "gameinfo.gi"
    video: str = "video.txt"


PRESETS: tuple[Preset, ...] = (
    Preset(
        "recommended",
        "FPS Config (Recommended)",
        "OptiLock FPS Config (Recommended)",
    ),
    Preset(
        "community",
        "Community Config",
        "OptiLock Community Config",
    ),
    Preset(
        "potato",
        "Potato Config",
        "OptiLock Potato Config",
    ),
    Preset(
        "ultra_potato_shadows",
        "Ultra Potato (Shadows)",
        "OptiLock Ultra Potato Config",
        video="video(Shadows).txt",
    ),
    Preset(
        "ultra_potato_noshadows",
        "Ultra Potato (No Shadows)",
        "OptiLock Ultra Potato Config",
        video="video(No Shadows).txt",
    ),
)

PRESET_BY_KEY = {preset.key: preset for preset in PRESETS}
DEFAULT_PRESET = "recommended"


def config_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_NAME


CONFIG_FILE = config_dir() / "settings.json"


@dataclass
class Settings:
    """Everything the tool remembers between runs."""

    # Where Deadlock lives. Empty means "auto-detect".
    deadlock_dir: str = ""

    # Which OptiLock config to download.
    preset: str = DEFAULT_PRESET

    # The aspect ratio the user picked. Re-applied after every update.
    # ``citadel_camera_hero_fov`` is deliberately left alone.
    aspect_ratio: str = "2.2"

    # Behaviour
    write_gameinfo: bool = True
    write_video: bool = True
    auto_check_on_start: bool = True

    # Resolution override. Off by default: the repo's video.txt ships
    # setting.defaultres "-1", so the game re-detects it. When on, the width and
    # height below are written after the merge.
    set_resolution: bool = False
    resolution_width: str = "1920"
    resolution_height: str = "1080"

    # A video.txt the user supplies. When enabled it replaces the downloaded
    # video.txt as the source of everything below DeviceID.
    use_custom_video: bool = False
    custom_video_path: str = ""

    # Update detection bookkeeping.
    upstream_sha256: str = ""
    upstream_version: str = ""
    upstream_video_sha256: str = ""
    applied_gameinfo_sha256: str = ""
    applied_video_sha256: str = ""

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        allowed = {field.name for field in fields(cls)}
        return cls(**{key: value for key, value in raw.items() if key in allowed})

    def save(self) -> None:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(
            json.dumps(asdict(self), indent=2) + "\n",
            encoding="utf-8",
        )

    @property
    def preset_object(self) -> Preset:
        return PRESET_BY_KEY.get(self.preset, PRESET_BY_KEY[DEFAULT_PRESET])
