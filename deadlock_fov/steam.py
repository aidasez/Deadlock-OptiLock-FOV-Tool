"""Locate Steam libraries and Deadlock installs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import DEADLOCK_APPID

GAMEINFO_REL = Path("game") / "citadel" / "gameinfo.gi"
VIDEO_REL = Path("game") / "citadel" / "cfg" / "video.txt"
MANIFEST_NAME = f"appmanifest_{DEADLOCK_APPID}.acf"


@dataclass
class Install:
    """A Deadlock install found inside a Steam library."""

    root: Path
    library: Path
    active: bool

    @property
    def gameinfo(self) -> Path:
        return self.root / GAMEINFO_REL

    @property
    def video(self) -> Path:
        return self.root / VIDEO_REL

    @property
    def is_complete(self) -> bool:
        return self.gameinfo.is_file()

    def describe(self) -> str:
        gameinfo = self.gameinfo
        if gameinfo.is_file():
            size = f"{gameinfo.stat().st_size:,} bytes"
        else:
            size = "No gameinfo.gi"
        flags = ["Active" if self.active else "Inactive", size]
        return f"{self.root}   [{', '.join(flags)}]"


def _registry_steam_path() -> Path | None:
    try:
        import winreg
    except ImportError:  # not on Windows
        return None

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    for hive, key, value in locations:
        try:
            with winreg.OpenKey(hive, key) as handle:
                raw, _ = winreg.QueryValueEx(handle, value)
        except OSError:
            continue
        if raw:
            return Path(str(raw).replace("/", "\\"))
    return None


def steam_root() -> Path | None:
    """The Steam installation directory, if one can be found."""
    return _registry_steam_path()


def library_folders() -> list[Path]:
    """Every ``steamapps`` directory this machine knows about."""
    steam = _registry_steam_path()
    if steam is None:
        return []

    roots = [steam / "steamapps"]
    vdf = steam / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        text = vdf.read_text(encoding="utf-8", errors="replace")
        for raw in re.findall(r'"path"\s*"([^"]*)"', text):
            roots.append(Path(raw.replace("\\\\", "\\")) / "steamapps")

    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def find_installs(extra: Path | None = None) -> list[Install]:
    """All Deadlock installs, most likely candidate first."""
    found: dict[str, Install] = {}

    for library in library_folders():
        root = library / "common" / "Deadlock"
        if root.is_dir():
            found[str(root).lower()] = Install(
                root=root,
                library=library,
                active=(library / MANIFEST_NAME).is_file(),
            )

    if extra is not None and extra.is_dir():
        found.setdefault(
            str(extra).lower(),
            Install(
                root=extra,
                library=extra.parent.parent,
                active=(extra.parent / MANIFEST_NAME).is_file(),
            ),
        )

    return sorted(
        found.values(),
        key=lambda item: (not item.active, not item.is_complete, str(item.root).lower()),
    )


def resolve(path: Path) -> Install:
    """Wrap a manually chosen Deadlock folder."""
    return Install(
        root=path,
        library=path.parent.parent,
        active=(path.parent / MANIFEST_NAME).is_file(),
    )
