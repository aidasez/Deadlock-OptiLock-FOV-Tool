"""Text surgery: the FOV tweak for gameinfo.gi and the video.txt merge.

Two rules govern everything here:

* ``gameinfo.gi`` - the OptiLock file is copied in whole, then the two FOV
  convars are rewritten. The rewrite is anchored on the convar *name* (not on
  surrounding whitespace or the comment), so it survives reformatting, and it
  is verified afterwards. If neither convar is present we refuse to write,
  rather than overwrite a file the author restructured.
* ``video.txt`` - only the part below ``DeviceID`` is replaced, so the game
  keeps recognising the device. Optionally the user's display settings are
  carried over so applying a config does not reset their resolution.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
from pathlib import Path

ASPECT_CVAR = "r_aspectratio"
FOV_CVAR = "citadel_camera_hero_fov"

# Keys carried over from the user's own video.txt when "keep my display
# settings" is enabled. These are the ones that decide resolution / monitor /
# window mode, i.e. the ones that are genuinely personal.
DISPLAY_KEYS: tuple[str, ...] = (
    "setting.defaultres",
    "setting.defaultresheight",
    "setting.recommendedheight",
    "setting.refreshrate_numerator",
    "setting.refreshrate_denominator",
    "setting.fullscreen",
    "setting.nowindowborder",
    "setting.fullscreen_min_on_focus_loss",
    "setting.monitor_index",
    "setting.high_dpi",
    "setting.aspectratiomode",
    "setting.mat_viewportscale",
    "setting.r_fullscreen_gamma",
)

DEVICE_ID_RE = re.compile(r'^[ \t]*"DeviceID"[ \t]+"[^"]*"[ \t]*$', re.MULTILINE)
KEY_VALUE_RE = re.compile(r'^[ \t]*"([^"]+)"[ \t]+"([^"]*)"[ \t]*$', re.MULTILINE)

# The three ways the game can present a frame. ``setting.fullscreen`` is the
# exclusive-fullscreen flag, ``setting.nowindowborder`` the borderless one; the
# OptiLock config itself ships 0/1, i.e. borderless.
DISPLAY_MODES: dict[str, tuple[str, str]] = {
    "borderless": ("0", "1"),
    "windowed": ("0", "0"),
    "fullscreen": ("1", "0"),
}

VIDEO_ROOT = '"video.cfg"\n{\n'

BACKUP_SUFFIX = ".bak"


class PatchError(RuntimeError):
    """Raised when patching would be unsafe, so nothing is written."""


# --------------------------------------------------------------------------- #
# reading / writing, preserving encoding and line endings exactly
# --------------------------------------------------------------------------- #


def newline_of(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and crlf >= lf:
        return "\r\n"
    return "\n"


def _normalise(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def load_text(path: Path) -> tuple[str, str, str]:
    """Return ``(text, encoding, newline)`` with text normalised to ``\\n``."""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        encoding = "utf-16"
    elif raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        encoding = "utf-8"
    text = raw.decode(encoding, errors="replace")
    return _normalise(text), encoding, newline_of(text)


def make_writable(path: Path) -> bool:
    """Clear the read-only flag, unconditionally.

    Steam marks some config files read-only, and the attribute alone is enough
    to make every write fail with "Access is denied". The flag is cleared even
    when ``os.access`` claims the file is writable, because that check can lie
    for elevated processes.

    Returns True when a flag actually had to be cleared.
    """
    if not path.exists():
        return False

    changed = False
    try:
        attributes = path.stat().st_file_attributes
    except (AttributeError, OSError):
        attributes = 0

    readonly_bit = getattr(stat, "FILE_ATTRIBUTE_READONLY", 0x00000001)
    if attributes & readonly_bit or not os.access(path, os.W_OK):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            changed = True
        except OSError:
            # Nothing else to try here; the write itself will report the reason.
            pass
    return changed


def _replace_with_retry(source: Path, target: Path, attempts: int = 4) -> None:
    """Move ``source`` onto ``target``, retrying a transient lock."""
    last: OSError | None = None
    for attempt in range(attempts):
        try:
            make_writable(target)
            os.replace(source, target)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(0.15 * (attempt + 1))
    assert last is not None
    raise last


def write_text(path: Path, text: str, encoding: str, newline: str) -> bool:
    """Write ``text`` to ``path``, clearing read-only and retrying locks.

    Returns True when the read-only flag had to be cleared first.
    """
    data = _normalise(text).replace("\n", newline).encode(encoding)
    path.parent.mkdir(parents=True, exist_ok=True)

    cleared = make_writable(path)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_bytes(data)
        make_writable(temp)
        _replace_with_retry(temp, path)
    except PermissionError as rename_error:
        # A read-only target or a handle held open elsewhere can refuse the
        # rename while still allowing the bytes to be written in place.
        temp.unlink(missing_ok=True)
        try:
            make_writable(path)
            with open(path, "wb") as handle:
                handle.write(data)
        except PermissionError:
            raise PatchError(
                f"{path.name} could not be overwritten: Windows refused the write "
                f"({rename_error}). Close Deadlock and Steam's file prompts, then try again."
            ) from rename_error
    finally:
        temp.unlink(missing_ok=True)
    return cleared


def hash_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# gameinfo.gi
# --------------------------------------------------------------------------- #


def _cvar_pattern(name: str) -> re.Pattern[str]:
    return re.compile(
        rf'^([ \t]*{re.escape(name)}[ \t]+)"([^"]*)"([ \t]*)(//.*)?$',
        re.MULTILINE,
    )


def _set_cvar(text: str, name: str, value: str) -> tuple[str, bool]:
    pattern = _cvar_pattern(name)
    match = pattern.search(text)
    if match is None:
        return text, False

    old = match.group(2)
    trailing = len(match.group(3)) - (len(value) - len(old))
    if trailing < 1:
        trailing = 1

    def repl(hit: re.Match[str]) -> str:
        comment = hit.group(4) or ""
        return f'{hit.group(1)}"{value}"{" " * trailing}{comment}'

    new_text, count = pattern.subn(repl, text, count=1)
    return new_text, count == 1


def read_fov(text: str) -> dict[str, str]:
    """Current values of the two FOV convars, if the file defines them."""
    found: dict[str, str] = {}
    for name in (ASPECT_CVAR, FOV_CVAR):
        match = _cvar_pattern(name).search(text)
        if match is not None:
            found[name] = match.group(2)
    return found


def same_aspect(left: str, right: str) -> bool:
    """True when two aspect values mean the same number (``2.2`` == ``2.20``)."""
    try:
        return abs(float(left) - float(right)) < 1e-9
    except ValueError:
        return left == right


def format_aspect(value: str) -> str:
    """Show an aspect ratio with two decimals when it is a number."""
    try:
        return f"{float(value):.2f}"
    except ValueError:
        return value


def validate_gameinfo(text: str) -> None:
    """Cheap sanity check on a freshly downloaded gameinfo.gi."""
    if '"GameInfo"' not in text:
        raise PatchError('the downloaded gameinfo.gi has no "GameInfo" block')
    if text.count("{") != text.count("}"):
        raise PatchError("the downloaded gameinfo.gi has unbalanced braces")


def apply_fov(
    text: str,
    aspect_ratio: str,
    hero_fov: str | None = None,
) -> tuple[str, list[str]]:
    """Rewrite the aspect-ratio convar, and ``hero_fov`` too when one is given.

    ``hero_fov=None`` (the default the tool uses) leaves
    ``citadel_camera_hero_fov`` exactly as the config ships it.
    """
    patched, ok_aspect = _set_cvar(text, ASPECT_CVAR, aspect_ratio)

    ok_fov: bool | None = None
    if hero_fov is not None:
        patched, ok_fov = _set_cvar(patched, FOV_CVAR, hero_fov)

    if not ok_aspect and not ok_fov:
        raise PatchError(
            f"neither {ASPECT_CVAR} nor {FOV_CVAR} is present in the downloaded "
            "gameinfo.gi - the config was restructured, so nothing was written"
        )

    warnings: list[str] = []
    if not ok_aspect:
        if hero_fov is None:
            warnings.append(f"{ASPECT_CVAR} was not found - nothing was changed")
        else:
            warnings.append(f"{ASPECT_CVAR} was not found - only {FOV_CVAR} was set")
    if hero_fov is not None and not ok_fov:
        warnings.append(f"{FOV_CVAR} was not found - only {ASPECT_CVAR} was set")

    # Confirm the edit actually landed before anyone writes to disk.
    check = read_fov(patched)
    if ok_aspect and check.get(ASPECT_CVAR) != aspect_ratio:
        raise PatchError(f"failed to set {ASPECT_CVAR} to {aspect_ratio}")
    if hero_fov is not None and ok_fov and check.get(FOV_CVAR) != hero_fov:
        raise PatchError(f"failed to set {FOV_CVAR} to {hero_fov}")

    return patched, warnings


# --------------------------------------------------------------------------- #
# video.txt
# --------------------------------------------------------------------------- #


def video_header(current: str) -> str:
    """Everything up to and including the ``DeviceID`` line."""
    match = DEVICE_ID_RE.search(current)
    if match is None:
        raise PatchError("your video.txt has no DeviceID line, so the safe merge could not be done")
    return current[: match.end()]


def video_body(text: str) -> str:
    """The part of a video.txt that the merge replaces.

    Accepts either a whole file (header stripped) or a bare body, so a user can
    hand over any video.txt they like without having to trim it first.
    """
    match = DEVICE_ID_RE.search(text)
    if match is not None:
        text = text[match.end():]
    return text.lstrip("\n").lstrip()


def _set_video_key(body: str, key: str, value: str) -> str:
    """Rewrite ``key`` in place, or add it just before the closing brace."""
    pattern = re.compile(
        rf'^([ \t]*"{re.escape(key)}"[ \t]+)"[^"]*"([ \t]*)$',
        re.MULTILINE,
    )
    if pattern.search(body):
        return pattern.sub(
            lambda hit, v=value: f'{hit.group(1)}"{v}"{hit.group(2)}',
            body,
            count=1,
        )
    if body.rstrip().endswith("}"):
        index = body.rindex("}")
        return f'{body[:index]}\t"{key}"\t\t"{value}"\n{body[index:]}'
    return body + f'\n\t"{key}"\t\t"{value}"\n'


def read_display(text: str) -> dict[str, str]:
    """The display-related settings a video.txt currently holds."""
    found: dict[str, str] = {}
    for key, value in KEY_VALUE_RE.findall(text):
        if key in DISPLAY_KEYS:
            found[key] = value
    return found


def display_mode(values: dict[str, str]) -> str:
    """Which of :data:`DISPLAY_MODES` these settings describe."""
    fullscreen = values.get("setting.fullscreen", "0")
    borderless = values.get("setting.nowindowborder", "0")
    for name, (want_full, want_borderless) in DISPLAY_MODES.items():
        if fullscreen == want_full and borderless == want_borderless:
            return name
    return "fullscreen" if fullscreen == "1" else "borderless"


def apply_resolution(body: str, width: int, height: int) -> tuple[str, list[str]]:
    """Force a resolution into a video body. Returns warnings."""
    wanted = {
        "setting.defaultres": str(int(width)),
        "setting.defaultresheight": str(int(height)),
    }
    for key, value in wanted.items():
        body = _set_video_key(body, key, value)

    written = read_display(body)
    wrong = [key for key, value in wanted.items() if written.get(key) != value]
    notes = ["could not write " + ", ".join(wrong)] if wrong else []
    return body, notes


def describe_display(values: dict[str, str]) -> str:
    """One-line summary such as ``1920x1080 · borderless · monitor 1``."""
    width = values.get("setting.defaultres", "")
    height = values.get("setting.defaultresheight", "")
    if not width or not height:
        size = "no resolution"
    elif "-1" in (width, height):
        size = "auto resolution"
    else:
        size = f"{width}x{height}"

    try:
        monitor = int(values.get("setting.monitor_index", "0")) + 1
    except ValueError:
        monitor = 1
    numerator = values.get("setting.refreshrate_numerator", "0")
    denominator = values.get("setting.refreshrate_denominator", "0")
    try:
        rate = int(numerator) // int(denominator)
    except (ValueError, ZeroDivisionError):
        rate = 0
    refresh = f"{rate} Hz" if rate > 0 else "auto refresh"

    return f"{size} · {display_mode(values)} · monitor {monitor} · {refresh}"


def merge_video(
    upstream_body: str,
    current: str | None,
) -> tuple[str, list[str]]:
    """Header from the user's file + the downloaded settings below it."""
    notes: list[str] = []
    body = upstream_body.lstrip("\n").lstrip()

    if current:
        header = video_header(current)
    else:
        header = VIDEO_ROOT.rstrip("\n")
        notes.append("No existing video.txt was found, so one was created from scratch.")

    merged = header.rstrip("\n") + "\n" + body
    if not merged.endswith("\n"):
        merged += "\n"
    return merged, notes


# --------------------------------------------------------------------------- #
# backups (one per file, created once, never overwritten)
# --------------------------------------------------------------------------- #


def backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def ensure_backup(path: Path) -> Path | None:
    """Create ``<file>.bak`` once, holding the file as it was before we touch it."""
    if not path.is_file():
        return None
    backup = backup_path(path)
    if not backup.exists():
        shutil.copy2(path, backup)
        make_writable(backup)  # keep the backup easy to copy back later
    return backup


def restore_backup(path: Path) -> bool:
    backup = backup_path(path)
    if not backup.is_file():
        return False
    data = backup.read_bytes()
    make_writable(path)
    try:
        shutil.copy2(backup, path)
    except PermissionError:
        make_writable(path)
        with open(path, "wb") as handle:
            handle.write(data)
    make_writable(path)
    return True
