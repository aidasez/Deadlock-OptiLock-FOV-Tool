"""PySide6 front end."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import service
from .config import CONFIG_FILE, PRESETS, PRESET_BY_KEY, Preset, Settings
from .patcher import (
    ASPECT_CVAR,
    backup_path,
    describe_display,
    format_aspect,
    load_text,
    read_display,
    read_fov,
    same_aspect,
)
from .steam import Install, find_installs, resolve
from .theme import ArcheyPanel, mono_font, stylesheet, ui_font

APP_ICON = Path(__file__).resolve().parent / "assets" / "app_icon.png"


class Worker(QThread):
    """Runs one blocking call off the UI thread."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, func, *args, **kwargs) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # surfaced to the user instead of dying silently
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(result)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Deadlock OptiLock+FOV Tool")
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.setStyleSheet(stylesheet())
        self.setFont(ui_font(9))
        self.setMinimumWidth(740)

        self.settings = Settings.load()
        self.installs: list[Install] = []
        self.worker: Worker | None = None
        self.status_text = "Ready"
        self.status_tone = "dim"

        self._build_ui()
        self._load_settings_into_ui()
        self._refresh_installs()
        self._refresh_panel()

        if self.settings.auto_check_on_start:
            QTimer.singleShot(400, self.on_check)

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(5)

        self.panel = ArcheyPanel()
        outer.addWidget(self.panel)
        outer.addWidget(self._build_setup_group())
        outer.addWidget(self._build_video_group())
        outer.addLayout(self._build_buttons())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(8))
        self.log.setMinimumHeight(70)
        self.log.setVisible(False)
        outer.addWidget(self.log, 1)

        self.log.appendPlainText(f"# Settings file: {CONFIG_FILE}")
        self.log.appendPlainText("# Your installed video.txt is read automatically.")

    def _build_setup_group(self) -> QGroupBox:
        group = QGroupBox("Setup")
        grid = QGridLayout(group)
        grid.setContentsMargins(8, 6, 8, 5)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel("Game Folder"), 0, 0)
        self.install_combo = QComboBox()
        self.install_combo.currentIndexChanged.connect(self._on_install_changed)
        grid.addWidget(self.install_combo, 0, 1, 1, 2)
        browse = QPushButton("Browse...")
        browse.setToolTip("Pick the Deadlock folder yourself")
        browse.clicked.connect(self._on_browse)
        grid.addWidget(browse, 0, 3)

        grid.addWidget(QLabel("Aspect Ratio"), 1, 0)
        self.aspect_spin = QDoubleSpinBox()
        self.aspect_spin.setDecimals(2)
        self.aspect_spin.setRange(1.00, 4.00)
        self.aspect_spin.setSingleStep(0.01)
        self.aspect_spin.setFixedWidth(82)
        self.aspect_spin.setToolTip("A higher number gives a wider view. Default: 2.20.")
        self.aspect_spin.valueChanged.connect(self._on_aspect_changed)
        grid.addWidget(self.aspect_spin, 1, 1)
        grid.addWidget(QLabel("Config Preset"), 1, 2)
        self.preset_combo = QComboBox()
        for preset in PRESETS:
            self.preset_combo.addItem(preset.label, preset.key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        grid.addWidget(self.preset_combo, 1, 3)

        self.write_gameinfo_check = QCheckBox("FOV settings")
        self.write_gameinfo_check.setToolTip(
            "gameinfo.gi - the file that holds the field of view.\n"
            "Leave this on to install it."
        )
        self.write_gameinfo_check.toggled.connect(self._on_option_changed)

        self.write_video_check = QCheckBox("Graphics settings")
        self.write_video_check.setToolTip(
            "video.txt - resolution, quality and other graphics options.\n"
            "Your GPU/display header is always kept from the file already installed."
        )
        self.write_video_check.toggled.connect(self._on_option_changed)

        grid.addWidget(self.write_gameinfo_check, 2, 0)
        grid.addWidget(self.write_video_check, 2, 1)

        self.auto_check_check = QCheckBox("Check for updates at startup")
        self.auto_check_check.setToolTip(
            "Checks whether OptiLock has published a newer config when the window opens."
        )
        self.auto_check_check.toggled.connect(self._on_option_changed)
        grid.addWidget(self.auto_check_check, 2, 2, 1, 2)

        grid.setColumnStretch(1, 0)
        grid.setColumnStretch(3, 1)
        return group

    def _build_video_group(self) -> QGroupBox:
        group = QGroupBox("Video Settings")
        rows = QVBoxLayout(group)
        rows.setContentsMargins(8, 6, 8, 5)
        rows.setSpacing(4)

        display_row = QHBoxLayout()
        display_row.setSpacing(8)
        display_row.addWidget(QLabel("Your Display"))
        self.video_state_label = QLabel("Not read yet")
        self.video_state_label.setObjectName("value")
        self.video_state_label.setWordWrap(True)
        display_row.addWidget(self.video_state_label, 1)
        read_game = QPushButton("Read from Game")
        read_game.setToolTip("Re-read the display settings from the installed video.txt")
        read_game.clicked.connect(self.on_read_video)
        display_row.addWidget(read_game)
        rows.addLayout(display_row)

        resolution_row = QHBoxLayout()
        resolution_row.setSpacing(8)
        self.set_resolution_check = QCheckBox("Set My Resolution")
        self.set_resolution_check.setToolTip(
            "Off: the game picks your resolution automatically.\n"
            "On: the width and height below are written into the config."
        )
        self.set_resolution_check.toggled.connect(self._on_resolution_changed)
        resolution_row.addWidget(self.set_resolution_check)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(320, 7680)
        self.width_spin.setSingleStep(10)
        self.width_spin.valueChanged.connect(self._on_resolution_changed)
        resolution_row.addWidget(self.width_spin)

        times = QLabel("x")
        times.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resolution_row.addWidget(times)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(200, 4320)
        self.height_spin.setSingleStep(10)
        self.height_spin.valueChanged.connect(self._on_resolution_changed)
        resolution_row.addWidget(self.height_spin)

        # Keep all write options on one line so the card stays shallow.
        self.custom_video_check = QCheckBox("Use My Own Video.txt")
        self.custom_video_check.setToolTip(
            "Use a video.txt of your own instead of the OptiLock one.\n"
            "Your settings below the DeviceID line are kept."
        )
        self.custom_video_check.toggled.connect(self._on_option_changed)
        resolution_row.addStretch(1)
        resolution_row.addWidget(self.custom_video_check)
        self.custom_video_button = QPushButton("Choose...")
        self.custom_video_button.clicked.connect(self._choose_custom_video)
        resolution_row.addWidget(self.custom_video_button)
        rows.addLayout(resolution_row)

        return group

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.apply_button = QPushButton("Apply Config")
        self.apply_button.setDefault(True)
        self.apply_button.setToolTip("Download the selected config and install it with your settings")
        self.apply_button.clicked.connect(self.on_apply)
        row.addWidget(self.apply_button)

        self.check_button = QPushButton("Check for Updates")
        self.check_button.setToolTip("See whether a newer config exists, or the game replaced yours")
        self.check_button.clicked.connect(self.on_check)
        row.addWidget(self.check_button)

        self.more_button = QPushButton("More...")
        menu = QMenu(self.more_button)
        self.restore_action = menu.addAction("Restore Original Files")
        self.restore_action.setToolTip("Put back the backups taken before the first apply")
        self.restore_action.triggered.connect(self.on_restore)
        self.open_action = menu.addAction("Open Game Folder")
        self.open_action.triggered.connect(self._on_open_folder)
        menu.addSeparator()
        self.details_action = menu.addAction("Show Details")
        self.details_action.setCheckable(True)
        self.details_action.toggled.connect(self._set_details_visible)
        self.more_button.setMenu(menu)
        row.addWidget(self.more_button)

        row.addStretch(1)
        return row

    def _set_details_visible(self, shown: bool) -> None:
        self.log.setVisible(shown)
        self.details_action.setText("Hide Details" if shown else "Show Details")
        layout = self.centralWidget().layout()
        if layout is not None:
            # Qt caches the window's minimum size from the layout; invalidate so
            # the window can shrink again when the log is hidden.
            layout.invalidate()
            layout.activate()
        self.setMinimumSize(0, 0)
        self.resize(self.width(), self.sizeHint().height())

    def _show_details(self) -> None:
        self.details_action.setChecked(True)
        self._set_details_visible(True)

    # ------------------------------------------------------------- settings --

    def _load_settings_into_ui(self) -> None:
        settings = self.settings

        # Snapshot first: filling in one widget must never let its change
        # handler read the others while they are still empty.
        aspect_ratio = _as_float(settings.aspect_ratio, 2.2)
        preset = settings.preset
        write_gameinfo = settings.write_gameinfo
        write_video = settings.write_video
        auto_check = settings.auto_check_on_start
        use_custom = settings.use_custom_video
        set_resolution = settings.set_resolution
        width = _as_int(settings.resolution_width, 1920)
        height = _as_int(settings.resolution_height, 1080)

        targets = (
            self.aspect_spin,
            self.preset_combo,
            self.write_gameinfo_check,
            self.write_video_check,
            self.auto_check_check,
            self.custom_video_check,
            self.set_resolution_check,
            self.width_spin,
            self.height_spin,
        )
        for widget in targets:
            widget.blockSignals(True)
        try:
            self.aspect_spin.setValue(aspect_ratio)
            index = self.preset_combo.findData(preset)
            self.preset_combo.setCurrentIndex(index if index >= 0 else 0)
            self.write_gameinfo_check.setChecked(write_gameinfo)
            self.write_video_check.setChecked(write_video)
            self.auto_check_check.setChecked(auto_check)
            self.custom_video_check.setChecked(use_custom)
            self.set_resolution_check.setChecked(set_resolution)
            self.width_spin.setValue(width)
            self.height_spin.setValue(height)
        finally:
            for widget in targets:
                widget.blockSignals(False)

        # Keep the stored preset valid even if the config file was hand-edited.
        settings.preset = self.preset_combo.currentData()
        self._update_custom_video_button()
        self._sync_resolution_widgets()

    def _persist(self) -> None:
        self.settings.save()

    def _on_aspect_changed(self) -> None:
        self.settings.aspect_ratio = f"{self.aspect_spin.value():.2f}"
        self._persist()
        self._refresh_panel()

    def _on_preset_changed(self) -> None:
        self.settings.preset = self.preset_combo.currentData()
        self._persist()
        self._refresh_panel()

    def _on_option_changed(self) -> None:
        self.settings.write_gameinfo = self.write_gameinfo_check.isChecked()
        self.settings.write_video = self.write_video_check.isChecked()
        self.settings.auto_check_on_start = self.auto_check_check.isChecked()
        self.settings.use_custom_video = self.custom_video_check.isChecked()
        self._sync_resolution_widgets()
        self._persist()
        self._refresh_panel()

    def _sync_resolution_widgets(self) -> None:
        """The width/height boxes only work while 'Set My Resolution' is ticked."""
        enabled = self.set_resolution_check.isChecked()
        self.width_spin.setEnabled(enabled)
        self.height_spin.setEnabled(enabled)

    def _on_resolution_changed(self) -> None:
        self.settings.set_resolution = self.set_resolution_check.isChecked()
        self.settings.resolution_width = str(self.width_spin.value())
        self.settings.resolution_height = str(self.height_spin.value())
        self._sync_resolution_widgets()
        self._persist()
        self._refresh_panel()

    def on_read_video(self) -> None:
        install = self._current_install()
        if install is None:
            QMessageBox.warning(self, "No Folder Selected", "Pick your Deadlock folder first.")
            return
        if not install.video.is_file():
            QMessageBox.warning(
                self,
                "No video.txt Yet",
                f"{install.video}\n\nThis file does not exist yet. Run the game once, "
                "or read another file with 'Read from File...'.",
            )
            return
        self._load_video(install.video, "installed video.txt")

    def _choose_custom_video(self) -> None:
        install = self._current_install()
        start = self.settings.custom_video_path or (str(install.video) if install is not None else "")
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Choose Your Video.txt",
            start,
            "Config Files (*.txt *.cfg);;All Files (*)",
        )
        if not chosen:
            return
        path = Path(chosen)
        try:
            text, _, _ = load_text(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could Not Read It", f"{path}\n\n{exc}")
            return
        if '"setting.' not in text:
            QMessageBox.warning(
                self,
                "That Does Not Look Like a Video.txt",
                f"{path}\n\nThis file has no graphics settings in it.",
            )
            return

        self.settings.custom_video_path = str(path)
        self.custom_video_check.setChecked(True)
        self._update_custom_video_button()
        self._persist()
        self._load_video(path, path.name)
        self.log.appendPlainText("# Your video.txt will be used instead of the OptiLock one.")
        self._refresh_panel()

    def _update_custom_video_button(self) -> None:
        path = self.settings.custom_video_path
        if path:
            self.custom_video_button.setText(_elide(Path(path).name, 24))
            self.custom_video_button.setToolTip(path)
        else:
            self.custom_video_button.setText("Choose...")
            self.custom_video_button.setToolTip("Pick your own video.txt to use instead of the OptiLock one")

    def _load_video(self, path: Path, description: str) -> None:
        try:
            text, _, _ = load_text(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could Not Read It", f"{path}\n\n{exc}")
            return

        values = read_display(text)
        if not values:
            QMessageBox.warning(
                self,
                "Nothing to Read",
                f"{path}\n\nThis file has no display settings in it, "
                "so it does not look like a video.txt.",
            )
            return

        self._fill_resolution(values)
        summary = describe_display(values)
        self.video_state_label.setText(summary)
        self.video_state_label.setToolTip(f"{description} - {path}")
        self.log.appendPlainText(f"$ Read {path}")
        self.log.appendPlainText(f"  {summary}")
        self._refresh_panel()

    def _fill_resolution(self, values: dict[str, str]) -> None:
        """Put the file's resolution in the boxes without flipping any toggles."""
        for key, widget in (
            ("setting.defaultres", self.width_spin),
            ("setting.defaultresheight", self.height_spin),
        ):
            raw = values.get(key, "")
            # "-1" means auto, so leave the box alone instead of showing it.
            if raw.lstrip("-").isdigit() and int(raw) > 0:
                widget.blockSignals(True)
                widget.setValue(int(raw))
                widget.blockSignals(False)
        self.settings.resolution_width = str(self.width_spin.value())
        self.settings.resolution_height = str(self.height_spin.value())
        self._persist()

    # ------------------------------------------------------------- installs --

    def _current_preset(self) -> Preset:
        return PRESET_BY_KEY.get(self.preset_combo.currentData(), PRESET_BY_KEY["recommended"])

    def _refresh_installs(self) -> None:
        extra = Path(self.settings.deadlock_dir) if self.settings.deadlock_dir else None
        self.installs = find_installs(extra=extra)

        self.install_combo.blockSignals(True)
        self.install_combo.clear()
        if not self.installs:
            self.install_combo.addItem("No Deadlock folder found - press Browse...", -1)
        else:
            for index, install in enumerate(self.installs):
                self.install_combo.addItem(install.describe(), index)
        self.install_combo.blockSignals(False)

        if self.installs:
            preferred = 0
            if self.settings.deadlock_dir:
                target = str(Path(self.settings.deadlock_dir)).lower()
                for index, install in enumerate(self.installs):
                    if str(install.root).lower() == target:
                        preferred = index
                        break
            elif len(self.installs) > 1:
                self.log.appendPlainText(
                    f"# Found {len(self.installs)} Deadlock installs; using the one Steam has installed."
                )
            self.install_combo.setCurrentIndex(preferred)
        self._on_install_changed()

    def _current_install(self) -> Install | None:
        index = self.install_combo.currentData()
        if isinstance(index, int) and 0 <= index < len(self.installs):
            return self.installs[index]
        return None

    def _on_install_changed(self) -> None:
        install = self._current_install()
        if install is not None:
            self.settings.deadlock_dir = str(install.root)
            self._persist()
        self._auto_read_video()
        self._refresh_panel()

    def _auto_read_video(self) -> None:
        """Mirror the installed video.txt without dialogs or log noise.

        Runs when the window opens, when the install changes, and after an
        apply, so the panel and the state line always describe the file that is
        actually on disk. The resolution boxes are only refilled when the
        override is off, so a saved override is never quietly overwritten.
        """
        install = self._current_install()
        if install is None or not install.video.is_file():
            return
        try:
            text, _, _ = load_text(install.video)
        except OSError:
            return
        values = read_display(text)
        if not values:
            return
        if not self.set_resolution_check.isChecked():
            self._fill_resolution(values)
        self.video_state_label.setText(describe_display(values))
        self.video_state_label.setToolTip(f"Installed video.txt - {install.video}")
        self._refresh_panel()

    def _on_browse(self) -> None:
        start = str(self.settings.deadlock_dir or "")
        chosen = QFileDialog.getExistingDirectory(self, "Choose Your Deadlock Folder", start)
        if not chosen:
            return
        path = Path(chosen)
        if not (path / "game" / "citadel").is_dir() and not (path / "gameinfo.gi").is_file():
            answer = QMessageBox.question(
                self,
                "Is That the Right Folder?",
                f"{path}\n\nThis folder does not contain game\\citadel. Use it anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.settings.deadlock_dir = str(path)
        self.installs = [resolve(path)] + [
            item for item in self.installs if str(item.root).lower() != str(path).lower()
        ]
        self.install_combo.blockSignals(True)
        self.install_combo.clear()
        for index, install in enumerate(self.installs):
            self.install_combo.addItem(install.describe(), index)
        self.install_combo.setCurrentIndex(0)
        self.install_combo.blockSignals(False)
        self._on_install_changed()

    def _on_open_folder(self) -> None:
        install = self._current_install()
        if install is None:
            return
        os.startfile(str(install.root))  # noqa: S606 - intentional shell open

    # ---------------------------------------------------------------- panel --

    def _refresh_panel(self) -> None:
        """Rebuild the info block from current state."""
        install = self._current_install()
        info: list[tuple[str, str, str]] = []

        if install is not None:
            info.append(("Game Folder", str(install.root), "fg"))
            info.append(self._gameinfo_line(install))
            info.append(self._aspect_line(install))
            info.append(("Config Preset", self._current_preset().label, "fg"))
            info.append(self._video_source_line())
            info.append(self._backup_line(install))
        else:
            info.append(("Game Folder", "Not found - press Browse...", "warn"))

        if service.game_running():
            info.append(("Game Running", "Yes - close it before applying", "warn"))
        else:
            info.append(("Game Running", "No", "dim"))

        info.append(("Status", self.status_text, self.status_tone))
        self.panel.set_info(info)

    def _gameinfo_line(self, install: Install) -> tuple[str, str, str]:
        path = install.gameinfo
        if not path.is_file():
            return ("FOV File", "gameinfo.gi is missing", "err")
        from . import upstream as upstream_module

        try:
            text, _, _ = load_text(path)
        except OSError as exc:
            return ("FOV File", f"Could not read it ({exc})", "err")
        version = upstream_module.config_version(text)
        label = f"OptiLock ver. {version}" if version else "Unknown version"
        return ("FOV File", label, "fg")

    def _video_source_line(self) -> tuple[str, str, str]:
        path = self.settings.custom_video_path
        if self.custom_video_check.isChecked() and path:
            if not Path(path).is_file():
                return ("Settings From", f"Your file is gone: {Path(path).name}", "err")
            return ("Settings From", f"Your own video.txt ({Path(path).name})", "accent")
        return ("Settings From", "The OptiLock config you selected", "dim")

    def _aspect_line(self, install: Install) -> tuple[str, str, str]:
        if not install.gameinfo.is_file():
            return ("Aspect Ratio", "Nothing installed yet", "warn")
        try:
            text, _, _ = load_text(install.gameinfo)
        except OSError as exc:
            return ("Aspect Ratio", f"Could not read it ({exc})", "err")
        current = read_fov(text).get(ASPECT_CVAR)
        if current is None:
            return ("Aspect Ratio", "The installed file has no aspect ratio line", "warn")
        wanted = self.settings.aspect_ratio
        if same_aspect(current, wanted):
            return ("Aspect Ratio", f"{format_aspect(current)} - already applied", "ok")
        return (
            "Aspect Ratio",
            f"{format_aspect(current)} now  →  {format_aspect(wanted)} after applying",
            "warn",
        )

    def _backup_line(self, install: Install) -> tuple[str, str, str]:
        present = [
            backup_path(path).name
            for path in (install.gameinfo, install.video)
            if backup_path(path).is_file()
        ]
        if not present:
            return ("Backup Files", "None yet - the first apply saves them", "dim")
        return ("Backup Files", " · ".join(present), "fg")

    # -------------------------------------------------------------- actions --

    def _set_status(self, text: str, tone: str = "fg") -> None:
        self.status_text = text
        self.status_tone = tone
        self._refresh_panel()

    def _run(self, func, on_success, *args, **kwargs) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Busy", "Please wait for the current operation to finish.")
            return
        self._set_busy(True)
        worker = Worker(func, *args, **kwargs)
        worker.succeeded.connect(on_success)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(lambda: self._set_busy(False))
        self.worker = worker
        worker.start()

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.check_button, self.apply_button, self.more_button):
            widget.setEnabled(not busy)
        if busy:
            self._set_status("Working...", "warn")

    def _on_worker_failed(self, message: str) -> None:
        self._set_status("Failed - see the details below", "err")
        self.log.appendPlainText(f"!! {message}")
        self._show_details()
        QMessageBox.critical(self, "Something Went Wrong", message)

    def on_check(self) -> None:
        install = self._current_install()
        if install is None:
            QMessageBox.warning(self, "No Folder Selected", "Pick your Deadlock folder first.")
            return
        self.log.appendPlainText(f"$ Check for updates  ({self._current_preset().label})")
        self._run(
            service.check,
            self._on_check_done,
            self.settings,
            install,
            self._current_preset(),
        )

    def _on_check_done(self, report: service.Report) -> None:
        self.log.appendPlainText(report.text())
        self.log.appendPlainText("")
        self._set_status(report.headline, "ok" if report.ok else "warn")
        self._persist()
        self._refresh_installs_silently()

    def on_apply(self) -> None:
        install = self._current_install()
        if install is None:
            QMessageBox.warning(self, "No Folder Selected", "Pick your Deadlock folder first.")
            return
        if service.game_running():
            answer = QMessageBox.question(
                self,
                "Deadlock Is Running",
                "The game is open and can overwrite these files when you quit.\n\n"
                "Apply anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        custom = None
        if self.custom_video_check.isChecked() and self.settings.custom_video_path:
            custom = Path(self.settings.custom_video_path)
        resolution = None
        if self.set_resolution_check.isChecked():
            resolution = (self.width_spin.value(), self.height_spin.value())

        self.log.appendPlainText(
            f"$ Apply  aspect ratio {self.settings.aspect_ratio}  ({self._current_preset().label})"
        )
        if resolution is not None:
            self.log.appendPlainText(f"$ Resolution  {resolution[0]}x{resolution[1]}")
        if custom is not None:
            self.log.appendPlainText(f"$ Your video.txt  {custom}")

        self._run(
            service.apply,
            self._on_apply_done,
            self.settings,
            install,
            self._current_preset(),
            write_gameinfo=self.write_gameinfo_check.isChecked(),
            write_video=self.write_video_check.isChecked(),
            resolution=resolution,
            custom_video=custom,
        )

    def _on_apply_done(self, report: service.Report) -> None:
        self.log.appendPlainText(report.text())
        self.log.appendPlainText("")
        self._set_status(report.headline, "ok" if report.ok else "err")
        if report.ok:
            self._auto_read_video()
            # The service records the hashes/version it just wrote; keep them.
            self._persist()
            QMessageBox.information(self, "All Done", report.headline)

    def on_restore(self) -> None:
        install = self._current_install()
        if install is None:
            QMessageBox.warning(self, "No Folder Selected", "Pick your Deadlock folder first.")
            return
        answer = QMessageBox.question(
            self,
            "Restore Original Files",
            "Put back the original gameinfo.gi and video.txt saved in the .bak files?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.log.appendPlainText("$ Restore original files")
        self._run(
            service.restore,
            self._on_restore_done,
            install,
            gameinfo=self.write_gameinfo_check.isChecked(),
            video=self.write_video_check.isChecked(),
        )

    def _on_restore_done(self, report: service.Report) -> None:
        self.log.appendPlainText(report.text())
        self.log.appendPlainText("")
        self._set_status(report.headline, "ok" if report.ok else "err")
        if report.ok:
            self._auto_read_video()
        self._persist()
        self._refresh_panel()

    def _refresh_installs_silently(self) -> None:
        """Re-read install metadata (size, version) without touching the selection."""
        install = self._current_install()
        if install is None:
            return
        index = self.install_combo.currentIndex()
        if 0 <= index < self.install_combo.count():
            self.install_combo.setItemText(index, install.describe())
        self._refresh_panel()


def _as_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int(value: str, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Deadlock OptiLock+FOV Tool")
    app.setWindowIcon(QIcon(str(APP_ICON)))
    app.setStyleSheet(stylesheet())
    app.setFont(ui_font(9))
    window = MainWindow()
    window.resize(max(820, window.sizeHint().width()), window.sizeHint().height())
    window.show()
    return app.exec()
