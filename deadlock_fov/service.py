"""High level actions the GUI calls: check for updates, apply, restore."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import patcher, upstream
from .config import Preset, Settings
from .steam import Install

CREATE_NO_WINDOW = 0x08000000


@dataclass
class Report:
    ok: bool
    headline: str
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join([self.headline, *self.lines]) if self.lines else self.headline


def game_running() -> bool:
    """True when Deadlock is open, in which case writing could be undone on exit."""
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq deadlock.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "deadlock.exe" in completed.stdout.lower()


def _local_fov(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        text, _, _ = patcher.load_text(path)
    except OSError:
        return {}
    return patcher.read_fov(text)


def check(settings: Settings, install: Install, preset: Preset) -> Report:
    """Compare the repo config and the installed file against what we recorded."""
    lines: list[str] = []
    stale: list[str] = []

    gameinfo_url = upstream.raw_url(preset, preset.gameinfo)
    text = upstream.fetch_text(gameinfo_url)
    remote_sha = upstream.sha256(text)
    remote_version = upstream.config_version(text)
    remote_aspect = patcher.read_fov(text).get(patcher.ASPECT_CVAR)

    lines.append(f"Preset: {preset.label}")
    if remote_version:
        lines.append(f"Newest version in the repo: ver. {remote_version}")

    if not settings.upstream_sha256:
        lines.append("This config has not been downloaded yet.")
        stale.append("nothing has been installed yet")
    elif remote_sha == settings.upstream_sha256:
        lines.append("The repo config has not changed since your last download.")
    else:
        lines.append("The repo has a newer config than the one you downloaded.")
        stale.append("a newer config is available in the repo")

    if remote_aspect:
        lines.append(f"Aspect ratio in the repo config: {remote_aspect}")

    # What is on disk right now.
    if install.gameinfo.is_file():
        local_sha = patcher.hash_file(install.gameinfo)
        current = _local_fov(install.gameinfo)
        installed = current.get(patcher.ASPECT_CVAR)
        if installed is None:
            lines.append(f"The installed gameinfo.gi has no {patcher.ASPECT_CVAR} line.")
        else:
            lines.append(f"Aspect ratio installed right now: {installed}")
        if settings.applied_gameinfo_sha256 and local_sha != settings.applied_gameinfo_sha256:
            lines.append(
                "gameinfo.gi was replaced or edited since this tool last wrote it "
                "(a game update or Steam's 'verify files' does that)."
            )
            stale.append("your installed gameinfo.gi changed since the last apply")
        if installed is not None and not patcher.same_aspect(installed, settings.aspect_ratio):
            lines.append(
                f"You want {settings.aspect_ratio}, so the installed file needs updating."
            )
            stale.append(
                f"the installed aspect ratio is {installed}, not {settings.aspect_ratio}"
            )
    else:
        lines.append(f"No gameinfo.gi installed at {install.gameinfo}")
        stale.append("gameinfo.gi is not installed")

    if install.video.is_file():
        try:
            current_video, _, _ = patcher.load_text(install.video)
            header_ok = patcher.DEVICE_ID_RE.search(current_video) is not None
            lines.append(
                "video.txt can be updated safely." if header_ok else "video.txt has no DeviceID line!"
            )
        except OSError as exc:
            lines.append(f"video.txt could not be read ({exc})")
    else:
        lines.append("video.txt is not installed yet.")

    if stale:
        return Report(False, "An update is needed.", lines + [""] + [
            "Why: " + "; ".join(stale) + ".",
            "Press 'Apply Config' to fix it.",
        ])
    return Report(True, "Everything is up to date.", lines)


def apply(
    settings: Settings,
    install: Install,
    preset: Preset,
    *,
    write_gameinfo: bool,
    write_video: bool,
    resolution: tuple[int, int] | None = None,
    custom_video: Path | None = None,
) -> Report:
    """Download the configs, apply the saved FOV, and write them into the install."""
    if not write_gameinfo and not write_video:
        return Report(False, "Nothing to do: both files are turned off.", [])

    lines: list[str] = []
    warnings: list[str] = []
    if resolution and not write_video:
        warnings.append("the resolution was not written because video.txt is turned off")
        resolution = None
    gameinfo_url = upstream.raw_url(preset, preset.gameinfo)
    video_url = upstream.raw_url(preset, preset.video)

    # ---- download and patch in memory first; nothing is written until this works
    text = upstream.fetch_text(gameinfo_url)
    remote_version = upstream.config_version(text)
    patcher.validate_gameinfo(text)
    lines.append(f"Downloaded {preset.folder}/{preset.gameinfo}")
    if remote_version:
        lines.append(f"Config version: ver. {remote_version}")

    patched, fov_warnings = patcher.apply_fov(
        text,
        aspect_ratio=settings.aspect_ratio,
    )
    warnings.extend(fov_warnings)
    lines.append(f"Set the aspect ratio to {settings.aspect_ratio}.")

    video_body: str | None = None
    if write_video:
        if custom_video is not None:
            try:
                custom_text, _, _ = patcher.load_text(custom_video)
            except OSError as exc:
                raise patcher.PatchError(
                    f"your own video.txt could not be read: {custom_video} ({exc})"
                ) from exc
            video_body = patcher.video_body(custom_text)
            if '"setting.' not in video_body:
                raise patcher.PatchError(
                    f"{custom_video} has no setting.* lines, so it does not look like a video.txt"
                )
            lines.append(f"Using your own video.txt: {custom_video}")
        else:
            video_body = upstream.fetch_text(video_url)
            lines.append(f"Downloaded {preset.folder}/{preset.video}")

    # ---- write gameinfo.gi
    if write_gameinfo:
        target = install.gameinfo
        backup = patcher.ensure_backup(target)
        if backup:
            lines.append(f"Backup of the original: {backup.name}")
        _, encoding, newline = patcher.load_text(target) if target.is_file() else ("", "utf-8", "\r\n")
        if patcher.write_text(target, patched, encoding, newline):
            lines.append("gameinfo.gi was read-only; that flag was cleared so it could be replaced.")
        settings.applied_gameinfo_sha256 = patcher.hash_file(target)
        settings.upstream_sha256 = upstream.sha256(text)
        settings.upstream_version = remote_version
        lines.append(f"Wrote {target}")

        verify = _local_fov(target)
        if verify.get(patcher.ASPECT_CVAR) != settings.aspect_ratio:
            raise patcher.PatchError(
                f"verification failed: {target} does not contain the requested aspect ratio"
            )
        lines.append("Checked the file on disk: the new aspect ratio is there.")

    # ---- write video.txt
    if write_video and video_body is not None:
        target = install.video
        current: str | None = None
        encoding, newline = "utf-8", "\r\n"
        if target.is_file():
            current, encoding, newline = patcher.load_text(target)
        merged, video_notes = patcher.merge_video(video_body, current)
        warnings.extend(video_notes)

        # The chosen resolution is applied last so it beats the preset's values.
        if resolution:
            width, height = resolution
            merged, resolution_notes = patcher.apply_resolution(merged, width, height)
            warnings.extend(resolution_notes)
            lines.append(f"Set the resolution to {width}x{height}.")

        backup = patcher.ensure_backup(target)
        if backup:
            lines.append(f"Backup of the original: {backup.name}")
        if patcher.write_text(target, merged, encoding, newline):
            lines.append("video.txt was read-only; that flag was cleared so it could be replaced.")
        settings.applied_video_sha256 = patcher.hash_file(target)
        settings.upstream_video_sha256 = upstream.sha256(video_body)
        lines.append(f"Wrote {target}")

    settings.save()

    headline = "Applied successfully."
    if warnings:
        headline = "Applied, with notes."
        lines.extend(f"note: {item}" for item in warnings)
    return Report(True, headline, lines)


def restore(install: Install, *, gameinfo: bool, video: bool) -> Report:
    lines: list[str] = []
    failures: list[str] = []

    for wanted, target in ((gameinfo, install.gameinfo), (video, install.video)):
        if not wanted:
            continue
        if patcher.restore_backup(target):
            lines.append(f"restored {target}")
        else:
            failures.append(f"no backup found for {target}")

    if failures:
        return Report(False, "Restore incomplete.", failures + lines)
    return Report(True, "Restored from backup.", lines)


def default_install_dir() -> Path | None:
    from .steam import find_installs

    installs = find_installs()
    return installs[0].root if installs else None
