# Deadlock OptiLock+FOV Tool

Keeps the [OptiLock](https://github.com/dacooderr/OptiLock) Deadlock config installed,
with **your** field of view, and re-applies it every time the config or the game updates.

It does four things:

1. Downloads `gameinfo.gi` and `video.txt` fresh from the OptiLock repo (never from a
   stale local copy, so a new game version is always picked up).
2. Rewrites `r_aspectratio` in `gameinfo.gi` with the value you chose, and remembers it.
   `citadel_camera_hero_fov` is left exactly as the config ships it.
3. Writes both files into your Deadlock install, keeping a one-time backup of each.
4. Optionally pins the resolution you choose, and optionally uses **your own**
   `video.txt` instead of the downloaded one.

## Requirements

- Windows, Python 3.10+
- `PySide6` (`pip install -r requirements.txt`)

## Running it

```
run.bat
```

or

```
python main.py
```

## Interface

Compact, single-window layout inspired by **shadcn/ui**: a neutral zinc dark theme,
subtle borders, clean system typography, and tightly grouped controls. The app uses
native PySide6 widgets styled to match the design; it does not embed the React library.

The window is about 880 x 350 with the log hidden, and the layout is designed to show
the important controls without scrolling:

- **Setup** holds the game folder, your aspect ratio, the config preset, and the three
  checkboxes (**FOV settings**, **Graphics settings**, **Check for updates at startup**).
- **Video Settings** shows what your installed `video.txt` currently holds, the
  resolution override, and the option to use your own `video.txt`.
- **Apply Config** installs everything. **Check for Updates** compares the repo and your
  installed file. **More...** opens the rarer actions: **Restore Original Files**,
  **Open Game Folder**, and **Show Details** (the log). The log also opens by itself if
  something fails.
- The panel at the top shows the game folder, the installed OptiLock version, the
  installed and wanted aspect ratio, the selected preset, where the graphics settings
  come from, whether backups exist, whether the game is running, and the current status.

All text is written in plain words and each label, button and sentence starts with a
capital letter, so a first-time user can follow it without knowing the file names.

The ASCII logo is **switched off** by default and the panel closes up the space it
would have taken. Set `SHOW_LOGO = True` in `deadlock_fov/logo.py` to bring it back -
the art is still there.

| File | What lives there |
|---|---|
| `deadlock_fov/logo.py` | The ASCII art plus the `SHOW_LOGO` switch. Only `█` and spaces, one tuple per row with a tone number (1 = bold, 2 = dim). |
| `deadlock_fov/theme.py` | The `PALETTE`, UI and monospace font helpers, the `ArcheyPanel` widget, card radii, and the widget stylesheet. |

The panel is painted by `ArcheyPanel` in `deadlock_fov/theme.py`. Logo notes:

- The logo is painted as **filled rectangles**, not text glyphs. `U+2588` is inset
  inside its cell in most fonts, so drawing glyphs leaves visible seams and the
  shape breaks into a grid of little squares.
- Only full blocks are used. Half blocks (`▄` `▀`) only tile correctly when the line
  box is exactly one glyph tall and collapse into noise at normal line spacing.

## What it changes, exactly

### `gameinfo.gi` -> `<Deadlock>\game\citadel\gameinfo.gi`

The downloaded file replaces the old one wholesale (this is what the OptiLock readme
tells you to do), and then this one line is rewritten:

```
r_aspectratio                "2.15"   // 1.75=80fov | 2.15=90fov | 2.49=100fov
```

Only the aspect ratio is exposed - that is the value the game derives its FOV from, and
it is what the readme's ladder is talking about. `citadel_camera_hero_fov` stays at the
value the selected config ships, so switching presets still changes the camera as the
author intended.

The rewrite is anchored on the convar **name**, not on surrounding whitespace or the
comment, so it still works if the author reformats the file. Afterwards the value is
read back off disk and verified. If the convar is missing - i.e. the author restructured
the file - the tool refuses to write anything rather than corrupt it.

### `video.txt` -> `<Deadlock>\game\citadel\cfg\video.txt`

A merge, exactly as the OptiLock readme describes it, in this order:

1. Everything up to and including the `DeviceID` line is kept untouched.
2. Everything below `DeviceID` (including the old closing brace) is removed.
3. The source `video.txt` is pasted in its place, so the file ends with exactly
   one closing brace and one `DeviceID`.

```
"video.cfg"                                          <- kept
{                                                    <- kept
	"Version"		"20"                                 <- kept
	"VendorID"		"<your VendorID>"                  <- kept
	"DeviceID"		"<your DeviceID>"                  <- kept
	"setting.defaultres"		"-1"                     <- from the config
	...                                                   <- from the config
}                                                    <- from the config
```

The *source* is the downloaded config for the selected preset. Tick **Use My Own
Video.txt** and pick a file instead, and everything below `DeviceID` comes from your
file: your resolution, your quality settings, your own extra tweaks. Only the header
(`Version` / `VendorID` / `DeviceID`) still comes from the installed file, so one
`DeviceID` and one closing brace are guaranteed. A bare body (no header at all) works
too - anything above the first `setting.*` line is simply ignored.

Because the stock config sets `setting.defaultres` to `-1`, the game re-detects your
resolution after an apply. Tick **Set My Resolution** to pin it instead: the width
and height you set are written into `setting.defaultres` / `setting.defaultresheight`
*after* the merge, so they beat the preset. The boxes are greyed out until the box is
ticked, start filled with whatever the installed `video.txt` says, and are remembered
between runs.

The override is **off** by default, which is exactly what the repo instructions say.

The installed `video.txt` is read automatically when the window opens (and again after
an apply), so **Video Settings** always shows your real display. **Read from Game**
re-reads it on demand. Reading never changes anything on disk; only **Apply Config**
writes.

## Update detection

*Checked when the window opens, and whenever you press **Check for Updates**.*

Two separate things are watched:

| What | How | Why |
|---|---|---|
| The OptiLock config itself | SHA-256 of the downloaded file, compared with the last download | The author publishes a new version (e.g. `ver. 4.6` -> `ver. 6.0`) |
| Your installed `gameinfo.gi` | SHA-256 of the file on disk, compared with the hash recorded when the tool wrote it | Steam updated the game, you ran *Verify integrity of game files*, or you edited it by hand - all of which silently undo the FOV |

Either condition is reported as "Update needed"; pressing **Apply Config**
re-downloads the current config and re-applies your saved aspect ratio. All your choices
are stored in the settings file, so you never have to re-enter them.

## Backups and restore

The first time the tool writes a file it saves `<file>.bak` next to it and **never
overwrites that backup**, so the `.bak` always holds your original file. **More... ->
Restore Original Files** copies them back.

Per install you get:

- `gameinfo.gi.bak`
- `cfg\video.txt.bak`

## Settings

Stored as JSON at `%APPDATA%\DeadlockFovTool\settings.json`:

```json
{
  "deadlock_dir": "E:\\SteamLibrary\\steamapps\\common\\Deadlock",
  "preset": "recommended",
  "aspect_ratio": "2.20",
  "write_gameinfo": true,
  "write_video": true,
  "auto_check_on_start": true,
  "set_resolution": false,
  "resolution_width": "1920",
  "resolution_height": "1080",
  "use_custom_video": false,
  "custom_video_path": ""
}
```

`resolution_width` / `resolution_height` are only written when `set_resolution` is true,
and `custom_video_path` is only read when `use_custom_video` is true.

Deleting the file just resets the tool to defaults; it does not touch the game files.

## The install folder

Deadlock is found automatically:

1. Steam's install path is read from the registry
   (`HKCU\Software\Valve\Steam\SteamPath`, then `HKLM\...\Valve\Steam\InstallPath`).
2. Every library in `steamapps\libraryfolders.vdf` is scanned for `common\Deadlock`.
3. Installs with an `appmanifest_1422450.acf` (i.e. actually installed, not a leftover
   folder) are listed first and selected by default.

If detection is wrong, use **Browse...** to pick the folder containing `game`.

## Presets

All five configs in the repo are selectable:

- OptiLock FPS Config (Recommended)
- OptiLock Community Config
- OptiLock Potato Config
- OptiLock Ultra Potato Config (Shadows)
- OptiLock Ultra Potato Config (No Shadows)

## Tests

No network and no writes to your real install:

```
python tests\selftest.py    # patch + merge logic against copies of the real files
python tests\gui_smoke.py   # builds the window offscreen, checks state, screenshots
```

Run them with `QT_QPA_PLATFORM=windows` if you want the screenshot to use real fonts.

`tests/selftest.py` uses the two reference files in `_reference\` and stubs the
download, so it exercises the exact byte-for-byte behaviour - CRLF preservation, the
`DeviceID` merge, one closing brace, read-only attribute handling, backup and restore,
the display override, and using your own `video.txt` as the body.

## Building a single .exe

```
build_exe.bat
```

Produces a single self-contained `dist\Deadlock FOV Tool.exe` via PyInstaller
(onefile, recipe in `Deadlock FOV Tool.spec`). It unpacks itself to a temp folder at
launch, so the first window takes a couple of seconds.

The spec keeps the exe around **23 MB** instead of 44 MB by leaving out the Qt pieces a
widget-only app never loads: the 20 MB software OpenGL fallback, Qt Quick/QML, PDF,
translations, and the image-format plugins (PNG is built into Qt). If a future change
needs one of them, remove its entry from `DROP_FILES` / `DROP_PREFIXES` in the spec.

## Things worth knowing

- **Close Deadlock before applying.** The game can overwrite these files when you quit.
  The tool warns you if `deadlock.exe` is running.
- **Only `r_aspectratio` is yours.** The camera FOV convar stays at whatever value the
  chosen preset ships; the tool never rewrites it. Edit it by hand if you want a
  different camera FOV - later applies leave it alone.
- **VAC.** This only copies and edits text config files - no memory patching, no code
  injection - but a wider FOV is a client-side visibility change, so treat it as
  at-your-own-risk like any Deadlock config edit.
- **Steam verify / game updates will undo it.** That is expected; re-run the tool, or
  leave **Check for updates at startup** enabled.
- **`video.txt` is often flagged read-only** in a fresh install, and Steam re-flags it.
  The read-only attribute is enough to make every write fail with "access denied", so
  the tool always clears it before writing - it does not stop to ask, and it does not
  skip the file. If a stale handle still refuses the write, it retries and then falls
  back to writing the file in place; only a file genuinely held open by a running
  Deadlock makes it give up, and then it tells you to close the game. The file is left
  writable afterwards, which is also why in-game graphics changes start saving again.
- The `Essential Fixes` folder in the repo contains `.vpk` mod files, not configs, so
  it is not offered as a preset.
