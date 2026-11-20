"""Offline self-test: runs the full apply flow against copies of the real files.

The network is stubbed out with the two files already saved in ``_reference``,
so this never touches the live install or the internet.

    python tests/selftest.py
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deadlock_fov import config, patcher, service, upstream  # noqa: E402
from deadlock_fov.config import PRESET_BY_KEY, Settings  # noqa: E402
from deadlock_fov.steam import resolve  # noqa: E402

REFERENCE = ROOT / "_reference"

CHECKS = 0
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if condition:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}" + (f" -- {detail}" if detail else ""))
        FAILURES.append(label)


def main() -> int:
    upstream_gameinfo = (REFERENCE / "gameinfo.upstream.gi").read_text(encoding="utf-8")
    upstream_video = (REFERENCE / "video.upstream.txt").read_text(encoding="utf-8")

    def fake_fetch_text(url: str) -> str:
        return upstream_gameinfo if url.endswith(".gi") else upstream_video

    upstream.fetch_text = fake_fetch_text  # offline stub

    work = Path(tempfile.mkdtemp(prefix="dlfov-selftest-"))
    config.CONFIG_FILE = work / "settings.json"

    install_root = work / "steamapps" / "common" / "Deadlock"
    (install_root / "game" / "citadel" / "cfg").mkdir(parents=True)
    source_gameinfo = REFERENCE / "gameinfo.upstream.gi"
    source_video = REFERENCE / "video.upstream.txt"
    initial_gameinfo = source_gameinfo.read_text(encoding="utf-8").replace("\n", "\r\n")
    (install_root / "game" / "citadel" / "gameinfo.gi").write_text(
        initial_gameinfo, encoding="utf-8", newline=""
    )
    initial_video = (
        '"video.cfg"\n{\n'
        '\t"Version"\t\t"20"\n'
        '\t"VendorID"\t\t"TEST_VENDOR_ID"\n'
        '\t"DeviceID"\t\t"TEST_DEVICE_ID"\n'
        + source_video.read_text(encoding="utf-8")
    )
    initial_video, _ = patcher.apply_resolution(initial_video, 1280, 1024)
    (install_root / "game" / "citadel" / "cfg" / "video.txt").write_text(
        initial_video, encoding="utf-8"
    )

    install = resolve(install_root)
    preset = PRESET_BY_KEY["recommended"]
    original_gameinfo_bytes = install.gameinfo.read_bytes()
    original_video_bytes = install.video.read_bytes()
    original_video_text, _, _ = patcher.load_text(install.video)

    # Hammer the read-only bit on, the way Steam leaves video.txt behind.
    for locked in (install.gameinfo, install.video):
        os.chmod(locked, stat.S_IREAD)
    check("both files start read-only", not os.access(install.video, os.W_OK))

    print("apply (following the OptiLock readme exactly)")
    settings = Settings(deadlock_dir=str(install_root), aspect_ratio="2.30")
    report = service.apply(
        settings,
        install,
        preset,
        write_gameinfo=True,
        write_video=True,
    )
    print("\n".join("  | " + line for line in report.text().splitlines()))
    check("apply reported success", report.ok, report.headline)
    check(
        "read-only files were overwritten and the log says so",
        report.ok and "read-only" in report.text(),
        report.text().splitlines()[0],
    )
    check(
        "both installed files end up writable",
        os.access(install.gameinfo, os.W_OK) and os.access(install.video, os.W_OK),
    )

    text, encoding, newline = patcher.load_text(install.gameinfo)
    fov = patcher.read_fov(text)
    check(f"{patcher.ASPECT_CVAR} == 2.30", fov.get(patcher.ASPECT_CVAR) == "2.30", str(fov))
    check(
        "hero_fov is left exactly as the config ships it",
        fov.get(patcher.FOV_CVAR) == "100",
        str(fov.get(patcher.FOV_CVAR)),
    )
    check("upstream version detected", settings.upstream_version == "6.0", settings.upstream_version)

    raw = install.gameinfo.read_bytes()
    check("gameinfo kept CRLF", raw.count(b"\r\n") > 1000)
    check("gameinfo has no bare LF", raw.count(b"\n") == raw.count(b"\r\n"))
    check("gameinfo has no BOM", not raw.startswith(b"\xef\xbb\xbf"))

    match = re.search(r"^.*r_aspectratio.*$", text, re.MULTILINE)
    check("aspectratio line still holds its comment", "//" in (match.group(0) if match else ""))
    print(f"  | {match.group(0) if match else 'MISSING'}")

    video_text, _, _ = patcher.load_text(install.video)
    first_lines = video_text.split("\n")[:5]
    check("video kept DeviceID", '"DeviceID"' in video_text)
    check("video kept Version/VendorID header", '"VendorID"' in video_text and '"Version"' in video_text)
    check("header layout is Version/VendorID/DeviceID", "DeviceID" in first_lines[4], str(first_lines))
    defaultres = re.search(r'"setting\.defaultres"\s+"([^"]*)"', video_text)
    check(
        "everything below DeviceID came from the repo (defaultres=-1)",
        defaultres is not None and defaultres.group(1) == "-1",
        defaultres.group(1) if defaultres else "no defaultres",
    )
    check("video braces balanced", video_text.count("{") == video_text.count("}"))
    check("video ends with a single closing brace", video_text.rstrip().endswith("}"))
    check("video keeps exactly one DeviceID", video_text.count('"DeviceID"') == 1)
    check("no leftover duplicate settings", video_text.count('"setting.knowndevice"') <= 1)

    print("backups")
    check("gameinfo backup created", patcher.backup_path(install.gameinfo).is_file())
    check("video backup created", patcher.backup_path(install.video).is_file())
    check("video.txt left writable", os.access(install.video, os.W_OK))
    check("backup left writable", os.access(patcher.backup_path(install.video), os.W_OK))
    check(
        "gameinfo backup is the untouched original",
        patcher.backup_path(install.gameinfo).read_bytes() == original_gameinfo_bytes,
    )
    check(
        "video backup is the untouched original",
        patcher.backup_path(install.video).read_bytes() == original_video_bytes,
    )

    print("check")
    result = service.check(settings, install, preset)
    print("\n".join("  | " + line for line in result.text().splitlines()))
    check("check reports up to date", result.ok, result.headline)

    print("steam overwrite detection")
    install.gameinfo.write_bytes(original_gameinfo_bytes)
    result = service.check(settings, install, preset)
    check("check notices the file was replaced", not result.ok, result.headline)

    print("restore")
    restore_report = service.restore(install, gameinfo=True, video=True)
    check("restore succeeded", restore_report.ok, restore_report.headline)
    check("gameinfo restored byte-for-byte", install.gameinfo.read_bytes() == original_gameinfo_bytes)
    check("video restored byte-for-byte", install.video.read_bytes() == original_video_bytes)

    print("aspect ladder")
    for aspect in ("1.75", "2.15", "2.49", "2.90"):
        patched, _ = patcher.apply_fov(upstream_gameinfo, aspect_ratio=aspect)
        got = patcher.read_fov(patched)
        check(
            f"ladder {aspect}",
            got.get(patcher.ASPECT_CVAR) == aspect,
            str(got),
        )
        check(
            f"ladder {aspect} leaves hero_fov alone",
            got.get(patcher.FOV_CVAR) == "100",
            str(got.get(patcher.FOV_CVAR)),
        )

    print("hero_fov can still be set when asked for explicitly")
    patched, _ = patcher.apply_fov(upstream_gameinfo, aspect_ratio="2.49", hero_fov="105")
    got = patcher.read_fov(patched)
    check(
        "explicit hero_fov is written",
        got.get(patcher.FOV_CVAR) == "105" and got.get(patcher.ASPECT_CVAR) == "2.49",
        str(got),
    )

    print("safety: refuses a restructured file")
    try:
        patcher.apply_fov('"GameInfo"\n{\n}\n', aspect_ratio="2.20")
        check("refuses file without the convars", False, "no exception raised")
    except patcher.PatchError:
        check("refuses file without the convars", True)

    print("video merge always takes the config's display lines")
    merged, _ = patcher.merge_video(upstream_video, original_video_text)
    kept = re.search(r'"setting\.defaultres"\s+"([^"]*)"', merged)
    check(
        "the preset's own defaultres wins",
        kept is not None and kept.group(1) == "-1",
        kept.group(1) if kept else "no defaultres",
    )
    check("merge still one DeviceID", merged.count('"DeviceID"') == 1)
    check("merge braces balanced", merged.count("{") == merged.count("}"))

    print("video merge without an existing file")
    fresh, notes = patcher.merge_video(upstream_video, None)
    check("creates a valid video.cfg from nothing", fresh.startswith('"video.cfg"') and fresh.rstrip().endswith("}"))
    check("fresh file braces balanced", fresh.count("{") == fresh.count("}"))

    print("display settings: read")
    original_display = patcher.read_display(original_video_text)
    check(
        "reads the resolution out of video.txt",
        original_display.get("setting.defaultres") == "1280"
        and original_display.get("setting.defaultresheight") == "1024",
        str(original_display.get("setting.defaultres")),
    )
    check(
        "describes the display in one line",
        patcher.describe_display(original_display)
        == "1280x1024 · borderless · monitor 1 · auto refresh",
        patcher.describe_display(original_display),
    )

    print("resolution: write")
    probe, probe_notes = patcher.apply_resolution(upstream_video, 2560, 1440)
    probe_display = patcher.read_display(probe)
    check(
        "apply_resolution writes width and height",
        probe_display.get("setting.defaultres") == "2560"
        and probe_display.get("setting.defaultresheight") == "1440",
        str(probe_display),
    )
    check("apply_resolution reports no problems", not probe_notes, str(probe_notes))
    check("apply_resolution keeps one of each key", probe.count('"setting.defaultres"') == 1)
    check(
        "apply_resolution does not add or drop braces",
        probe.count("}") == upstream_video.count("}"),
        f"{probe.count('}')} vs {upstream_video.count('}')}",
    )
    check(
        "apply_resolution leaves the first line alone",
        probe.lstrip().startswith('"setting.defaultres"'),
    )

    print("resolution: beats the preset's own values")
    preset_body, _ = patcher.merge_video(upstream_video, original_video_text)
    overridden, _ = patcher.apply_resolution(preset_body, 2560, 1440)
    override_display = patcher.read_display(overridden)
    check(
        "an explicit resolution wins over the preset's -1",
        override_display.get("setting.defaultres") == "2560",
        str(override_display.get("setting.defaultres")),
    )

    print("resolution: apply end to end")
    resolution_report = service.apply(
        settings,
        install,
        preset,
        write_gameinfo=False,
        write_video=True,
        resolution=(2560, 1440),
    )
    check("apply with a resolution succeeds", resolution_report.ok, resolution_report.headline)
    installed_text, _, _ = patcher.load_text(install.video)
    installed_display = patcher.read_display(installed_text)
    check(
        "installed video.txt holds the chosen resolution",
        installed_display.get("setting.defaultres") == "2560"
        and installed_display.get("setting.defaultresheight") == "1440",
        str(installed_display.get("setting.defaultres")),
    )
    check("resolution write kept one DeviceID", installed_text.count('"DeviceID"') == 1)
    check(
        "resolution write kept braces balanced",
        installed_text.count("{") == installed_text.count("}"),
    )
    check("resolution write kept the header", '"VendorID"' in installed_text)
    check(
        "resolution write is reported in the log",
        "Set the resolution to 2560x1440." in resolution_report.text(),
        resolution_report.text().splitlines()[0],
    )

    print("write: read-only and locked files")
    stubborn = work / "stubborn.txt"
    stubborn.write_text("old\n", encoding="utf-8")
    os.chmod(stubborn, stat.S_IREAD)
    check("scratch file starts read-only", not os.access(stubborn, os.W_OK))
    cleared = patcher.write_text(stubborn, "new\n", "utf-8", "\n")
    check("write_text clears the read-only flag", cleared is True)
    check("write_text wrote the new bytes", stubborn.read_text(encoding="utf-8") == "new\n")
    check("the file is writable afterwards", os.access(stubborn, os.W_OK))
    check("no .tmp file is left behind", not (work / "stubborn.txt.tmp").exists())

    print("write: a refused rename falls back to writing in place")
    blocked = work / "blocked.txt"
    blocked.write_text("old\n", encoding="utf-8")
    real_replace = os.replace
    calls = {"count": 0}

    def refuse_replace(source, target):
        calls["count"] += 1
        raise PermissionError(13, "Access is denied")

    os.replace = refuse_replace
    try:
        patcher.write_text(blocked, "still written\n", "utf-8", "\n")
    finally:
        os.replace = real_replace
    check("the rename was attempted", calls["count"] > 0, str(calls["count"]))
    check(
        "the content still landed",
        blocked.read_text(encoding="utf-8") == "still written\n",
        blocked.read_text(encoding="utf-8"),
    )
    check("the .tmp file was cleaned up", not (work / "blocked.txt.tmp").exists())
    check("no stale rename target", blocked.is_file())

    print("display settings: video.txt disabled")
    skipped = service.apply(
        settings,
        install,
        preset,
        write_gameinfo=False,
        write_video=False,
    )
    check("declines when both files are disabled", not skipped.ok, skipped.headline)

    print("a video.txt of your own")
    custom = work / "my-video.txt"
    custom.write_text(
        '"video.cfg"\n{\n'
        '\t"Version"\t\t"20"\n'
        '\t"VendorID"\t\t"CUSTOM_VENDOR_ID"\n'
        '\t"DeviceID"\t\t"CUSTOM_DEVICE_ID"\n'
        '\t"setting.defaultres"\t\t"3440"\n'
        '\t"setting.defaultresheight"\t\t"1440"\n'
        '\t"setting.fullscreen"\t\t"1"\n'
        '\t"setting.nowindowborder"\t\t"0"\n'
        '\t"setting.my_own_tweak"\t\t"42"\n'
        "}\n",
        encoding="utf-8",
    )
    custom_source = custom.read_text(encoding="utf-8")
    custom_body = patcher.video_body(custom_source)
    check("video_body strips the DeviceID header", "VendorID" not in custom_body, custom_body[:40])
    check("video_body starts at the first setting", custom_body.lstrip().startswith('"setting.defaultres"'))
    check("video_body keeps the user's own lines", "my_own_tweak" in custom_body)
    check(
        "video_body leaves a bare body alone",
        patcher.video_body(upstream_video).lstrip().startswith('"setting.defaultres"'),
    )

    custom_report = service.apply(
        settings,
        install,
        preset,
        write_gameinfo=False,
        write_video=True,
        custom_video=custom,
    )
    check("apply with your own video.txt succeeds", custom_report.ok, custom_report.headline)
    check(
        "the report names your file",
        "your own video.txt" in custom_report.text(),
        custom_report.text().splitlines()[0],
    )
    custom_text, _, _ = patcher.load_text(install.video)
    check(
        "your resolution is what ends up installed",
        re.search(r'"setting\.defaultres"\s+"([^"]*)"', custom_text).group(1) == "3440",
        custom_text[:120],
    )
    check("your own lines are installed", "my_own_tweak" in custom_text and '"42"' in custom_text)
    check(
        "the install's own DeviceID is kept, not yours",
        '"DeviceID"\t\t"TEST_DEVICE_ID"' in custom_text
        and '"CUSTOM_DEVICE_ID"' not in custom_text,
        custom_text[:200],
    )
    check("your VendorID does not overwrite the header", "CUSTOM_VENDOR_ID" not in custom_text)
    check("custom video kept one DeviceID", custom_text.count('"DeviceID"') == 1)
    check("custom video braces balanced", custom_text.count("{") == custom_text.count("}"))

    print("a video.txt of your own that is not one")
    junk = work / "not-a-video.txt"
    junk.write_text("hello\n", encoding="utf-8")
    try:
        service.apply(
            settings,
            install,
            preset,
            write_gameinfo=False,
            write_video=True,
            custom_video=junk,
        )
        check("rejects a file that is not a video.txt", False, "no exception raised")
    except patcher.PatchError:
        check("rejects a file that is not a video.txt", True)

    shutil.rmtree(work, ignore_errors=True)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("failures: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
