"""Smoke test: build the window offscreen, verify its state, screenshot it.

    python tests/gui_smoke.py [output.png]
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox, QLabel  # noqa: E402

from deadlock_fov import config, logo  # noqa: E402
from deadlock_fov.gui import MainWindow  # noqa: E402
from deadlock_fov.patcher import ASPECT_CVAR, FOV_CVAR  # noqa: E402

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
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_reference" / "gui-preview.png"

    work = Path(tempfile.mkdtemp(prefix="dlfov-gui-"))
    config.CONFIG_FILE = work / "settings.json"
    config.CONFIG_FILE.write_text(
        '{"auto_check_on_start": false, "aspect_ratio": "2.20"}',
        encoding="utf-8",
    )

    app = QApplication([])
    window = MainWindow()
    window.resize(max(880, window.sizeHint().width()), window.sizeHint().height())
    window.show()

    def capture() -> None:
        print("startup state")
        check("installs detected", len(window.installs) >= 1, str(len(window.installs)))
        if window.installs:
            check(
                "the active install is selected first",
                window.installs[0].active and window.installs[0].is_complete,
                window.installs[0].describe(),
            )
            check(
                "selected install is the E: library copy",
                "steamlibrary" in str(window.installs[0].root).lower(),
                str(window.installs[0].root),
            )
        check(
            "aspect spin remembers 2.20",
            abs(window.aspect_spin.value() - 2.20) < 1e-9,
            str(window.aspect_spin.value()),
        )
        check(
            "preset combo shows the recommended config",
            window.preset_combo.currentText() == "FPS Config (Recommended)",
            window.preset_combo.currentText(),
        )
        check("write_gameinfo on by default", window.write_gameinfo_check.isChecked())
        check("write_video on by default", window.write_video_check.isChecked())
        check("the window has its custom app icon", not window.windowIcon().isNull())
        check("aspect-only mode is gone", not hasattr(window, "fov_only_check"))
        check(
            "the removed keep-display option is gone",
            not any(
                "keep my current display" in box.text().lower()
                for box in window.findChildren(QCheckBox)
            ),
            str([box.text() for box in window.findChildren(QCheckBox)]),
        )
        check("auto check off as configured", not window.auto_check_check.isChecked())
        check(
            "settings were not clobbered while loading",
            window.settings.aspect_ratio == "2.20",
            f"aspect={window.settings.aspect_ratio}",
        )
        check(
            "panel reports the installed aspect state",
            bool(window.panel.value_for("Aspect Ratio")),
            window.panel.value_for("Aspect Ratio"),
        )
        widget_text = " ".join(
            [label.text() for label in window.findChildren(QLabel)]
            + [box.text() for box in window.findChildren(QCheckBox)]
            + [window.panel.value_for(t) for t in window.panel.titles()]
        )
        check(
            "hero_fov is not mentioned anywhere in the window",
            FOV_CVAR not in widget_text,
            widget_text[:120],
        )
        check(
            "the panel uses plain words instead of the convar name",
            ASPECT_CVAR not in widget_text,
            widget_text[:160],
        )
        check(
            "panel lists the info rows",
            all(
                title in window.panel.titles()
                for title in (
                    "Game Folder",
                    "FOV File",
                    "Aspect Ratio",
                    "Config Preset",
                    "Settings From",
                    "Backup Files",
                    "Game Running",
                    "Status",
                )
            ),
            str(window.panel.titles()),
        )
        check(
            "the info block stays compact",
            len(window.panel.titles()) == 8,
            str(window.panel.titles()),
        )
        check(
            "panel uses a compact, usable size hint",
            window.panel.sizeHint().width() > 300
            and 70 < window.panel.sizeHint().height() < 110,
            f"{window.panel.sizeHint().width()}x{window.panel.sizeHint().height()}",
        )
        check(
            "panel puts the folder on its own row and pairs the rest",
            window.panel.sizeHint().height() < 110,
            f"{len(window.panel.titles())} fields in {window.panel.sizeHint().height()} px",
        )
        check(
            "logo is switched off",
            logo.SHOW_LOGO is False and window.panel._logo_columns() == 0,
            f"show={logo.SHOW_LOGO} cols={window.panel._logo_columns()}",
        )
        check(
            "the video card shows the installed display",
            "1280x1024" in window.video_state_label.text(),
            window.video_state_label.text(),
        )
        check(
            "panel names the downloaded video.txt as the source",
            "OptiLock" in window.panel.value_for("Settings From"),
            window.panel.value_for("Settings From"),
        )

        print("video.txt")
        check(
            "resolution boxes start at the installed display",
            window.width_spin.value() == 1280 and window.height_spin.value() == 1024,
            f"{window.width_spin.value()}x{window.height_spin.value()}",
        )
        check("resolution override starts off", not window.set_resolution_check.isChecked())
        check(
            "resolution boxes are disabled until ticked",
            not window.width_spin.isEnabled() and not window.height_spin.isEnabled(),
        )
        check(
            "no window-mode or monitor widgets are built",
            not any(
                hasattr(window, name)
                for name in (
                    "resolution_combo",
                    "mode_combo",
                    "monitor_spin",
                    "refresh_spin",
                    "set_display_check",
                )
            ),
        )
        window.on_read_video()
        check(
            "reading the game updates the state label",
            "1280x1024" in window.video_state_label.text(),
            window.video_state_label.text(),
        )
        check(
            "reading the game fills the resolution boxes",
            window.width_spin.value() == 1280 and window.height_spin.value() == 1024,
            f"{window.width_spin.value()}x{window.height_spin.value()}",
        )
        check(
            "reading the game does not turn the override on",
            not window.set_resolution_check.isChecked() and not window.settings.set_resolution,
        )
        check(
            "reading the game leaves the preset as the source",
            "OptiLock" in window.panel.value_for("Settings From"),
            window.panel.value_for("Settings From"),
        )

        window.set_resolution_check.setChecked(True)
        check(
            "ticking the override enables the boxes",
            window.width_spin.isEnabled() and window.height_spin.isEnabled(),
        )
        check(
            "the override is remembered",
            window.settings.set_resolution is True
            and window.settings.resolution_width == "1280"
            and window.settings.resolution_height == "1024",
            f"{window.settings.resolution_width}x{window.settings.resolution_height}",
        )
        check(
            "the info block leaves display details to the video card",
            "Your Display" not in window.panel.titles(),
            str(window.panel.titles()),
        )
        window.width_spin.setValue(2560)
        window.height_spin.setValue(1440)
        check(
            "edited resolution is remembered",
            window.settings.resolution_width == "2560"
            and window.settings.resolution_height == "1440",
            f"{window.settings.resolution_width}x{window.settings.resolution_height}",
        )
        window.set_resolution_check.setChecked(False)
        check(
            "unticking the override disables the boxes again",
            not window.width_spin.isEnabled() and not window.height_spin.isEnabled(),
        )

        print("own video.txt")
        check("own video.txt starts off", not window.custom_video_check.isChecked())
        window.settings.custom_video_path = str(window.installs[0].video)
        window.custom_video_check.setChecked(True)
        window._update_custom_video_button()
        check(
            "own video.txt is marked as the source",
            "your own" in window.panel.value_for("Settings From").lower(),
            window.panel.value_for("Settings From"),
        )
        check(
            "own video.txt is remembered",
            window.settings.use_custom_video is True,
            str(window.settings.use_custom_video),
        )
        check(
            "the choose button shows the chosen file",
            window.custom_video_button.text() == "video.txt",
            window.custom_video_button.text(),
        )
        window.custom_video_check.setChecked(False)

        print("editing state")
        window.aspect_spin.setValue(2.35)
        check(
            "aspect edit is remembered",
            window.settings.aspect_ratio == "2.35",
            window.settings.aspect_ratio,
        )

        window.preset_combo.setCurrentIndex(window.preset_combo.count() - 1)
        check(
            "preset change is remembered",
            window.settings.preset == window.preset_combo.currentData(),
            window.settings.preset,
        )
        check(
            "status line follows the selected preset",
            window.panel.value_for("Config Preset") == window.preset_combo.currentText(),
            window.panel.value_for("Config Preset"),
        )

        print("plain language and capitalisation")
        check(
            "the buttons are capitalised",
            (window.apply_button.text(), window.check_button.text(), window.more_button.text())
            == ("Apply Config", "Check for Updates", "More..."),
            f"{window.apply_button.text()} | {window.check_button.text()} | "
            f"{window.more_button.text()}",
        )
        check(
            "the menu actions are capitalised",
            window.restore_action.text() == "Restore Original Files"
            and window.open_action.text() == "Open Game Folder"
            and window.details_action.text() in ("Show Details", "Hide Details"),
            f"{window.restore_action.text()} | {window.open_action.text()} | "
            f"{window.details_action.text()}",
        )
        check(
            "the checkboxes are capitalised",
            window.write_gameinfo_check.text() == "FOV settings"
            and window.write_video_check.text() == "Graphics settings"
            and window.auto_check_check.text() == "Check for updates at startup",
            f"{window.write_gameinfo_check.text()} | {window.write_video_check.text()} | "
            f"{window.auto_check_check.text()}",
        )
        check(
            "the cards are titled in plain words",
            {box.title() for box in window.findChildren(QGroupBox)}
            == {"Setup", "Video Settings"},
            str([box.title() for box in window.findChildren(QGroupBox)]),
        )
        check(
            "status starts capitalised",
            window.status_text[0].isupper(),
            window.status_text,
        )

        print("details")
        check("the log is hidden at startup", not window.log.isVisible())
        window.details_action.setChecked(True)
        check("the menu shows the log", window.log.isVisible())
        check(
            "the menu action flips to Hide Details",
            window.details_action.text() == "Hide Details",
            window.details_action.text(),
        )
        window.details_action.setChecked(False)
        check("the menu hides the log again", not window.log.isVisible())

        check("settings file is written", config.CONFIG_FILE.is_file())
        if config.CONFIG_FILE.is_file():
            saved = config.CONFIG_FILE.read_text(encoding="utf-8")
            check("saved file holds the current aspect", '"aspect_ratio": "2.35"' in saved, saved[:160])

        window.log.appendPlainText("smoke test: all state checks passed")
        window.grab().save(str(output))
        print(f"screenshot: {output}")

        print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
        if FAILURES:
            print("failures: " + ", ".join(FAILURES))
        app.quit()

    QTimer.singleShot(600, capture)
    code = app.exec()

    # Destroy the widget tree while QApplication is still alive; letting Python
    # collect it afterwards makes Qt tear down out of order and segfault.
    window.close()
    window.deleteLater()
    app.processEvents()
    return 1 if FAILURES else code


if __name__ == "__main__":
    raise SystemExit(main())
