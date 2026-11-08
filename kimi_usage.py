import json
import math
import os
import shlex
import shutil
import struct
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QProcess,
    QProcessEnvironment,
    QRectF,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

# Change this if the command you run in your terminal has a different name.
CLI_COMMAND = "kimi-code-usage"

APP_STYLE = """
QWidget {
    font-family: -apple-system, "SF Pro Text", "Helvetica Neue", "Segoe UI", sans-serif;
    color: #1C1C1E;
}
QMainWindow, QDialog, QWidget#root {
    background: #F2F4F8;
}
QFrame#card {
    background: #FFFFFF;
    border: 1px solid #E4E8EF;
    border-radius: 16px;
}
QLabel#appTitle {
    font-size: 17px;
    font-weight: 700;
}
QLabel#cardTitle {
    font-size: 11px;
    font-weight: 700;
    color: #8A8F99;
    letter-spacing: 1px;
}
QLabel#sectionTitle {
    font-size: 14px;
    font-weight: 600;
}
QLabel#muted {
    color: #8A8F99;
    font-size: 12px;
}
QLabel#value {
    font-size: 15px;
    font-weight: 700;
}
QPushButton {
    background: #FFFFFF;
    border: 1px solid #D9DEE7;
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton:hover { background: #F5F7FA; }
QPushButton:pressed { background: #E9EDF3; }
QPushButton#primary {
    background: #0A84FF;
    border: none;
    color: #FFFFFF;
}
QPushButton#primary:hover { background: #2B7FE0; }
QPushButton#primary:pressed { background: #1F6FCC; }
QSpinBox, QLineEdit {
    background: #F5F7FA;
    border: 1px solid #D9DEE7;
    border-radius: 8px;
    padding: 5px 8px;
}
QSpinBox { min-width: 90px; }
QProgressBar {
    background: #E9EDF3;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk {
    border-radius: 5px;
}
QMenu {
    background: #FFFFFF;
    border: 1px solid #D9DEE7;
    padding: 4px;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
    color: #1C1C1E;
}
QMenu::item:selected {
    background: #0A84FF;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background: #E4E8EF;
    margin: 4px 8px;
}
QToolTip {
    background: #FFFFFF;
    color: #1C1C1E;
    border: 1px solid #D9DEE7;
    padding: 4px 8px;
}
"""

PROGRESS_STYLE = """
QProgressBar {
    background: #E9EDF3;
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
}
QProgressBar::chunk {
    border-radius: 5px;
    background: %s;
}
"""

BADGE_STYLES = {
    "ok": ("#E3F6E9", "#1F9D42"),
    "bad": ("#FFECEA", "#D70015"),
    "neutral": ("#EFF2F6", "#6B7280"),
}


DEFAULT_INTERVAL_MINUTES = 5
DEFAULT_ALERT_THRESHOLD = 80
DEFAULT_SOUND_ALERT = True


def app_directory():
    # PyInstaller sets sys.frozen; there the data files sit next to the exe.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # Nuitka (standalone and onefile): data files live next to the compiled
    # module. In onefile mode that is the temporary unpack directory, not the
    # exe's folder, so sys.executable cannot be used here.
    return Path(__file__).resolve().parent


def ensure_alert_sound():
    """Create a gentle two-note chime next to the app if it is missing."""
    sound_path = app_directory() / "alert.wav"
    if sound_path.exists():
        return sound_path

    rate = 44100
    # A soft rising fifth (E5 -> A5), each note eased in and out with a
    # sin^2 envelope so there are no clicks or sharp attacks.
    notes = [(659.25, 0.0, 0.45), (880.00, 0.15, 0.55)]
    duration = 0.8

    samples = []
    for i in range(int(rate * duration)):
        t = i / rate
        value = 0.0
        for freq, start, length in notes:
            if start <= t < start + length:
                envelope = math.sin(math.pi * (t - start) / length) ** 2
                value += math.sin(2 * math.pi * freq * t) * envelope
        samples.append(struct.pack("<h", int(0.3 * 32767 * value)))

    with wave.open(str(sound_path), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"".join(samples))

    return sound_path


def read_int_setting(config, name, default, minimum, maximum):
    value = config.get(name, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(
            f'"{name}" in config.json must be an integer '
            f"between {minimum} and {maximum}."
        )
    return value


EXTRA_PATH_DIRS = (
    str(Path.home() / ".local" / "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    str(Path.home() / "bin"),
)


def build_search_path(environment):
    """GUI apps get a minimal PATH from launchd; extend it with the usual
    locations for user-installed CLI tools."""
    parts = (environment.value("PATH") or os.defpath).split(os.pathsep)
    for directory in EXTRA_PATH_DIRS:
        if directory not in parts:
            parts.append(directory)
    return os.pathsep.join(parts)


def resolve_cli(environment):
    """Locate CLI_COMMAND, falling back to the user's login shell."""
    search_path = build_search_path(environment)
    found = shutil.which(CLI_COMMAND, path=search_path)
    if found:
        return found, search_path

    shell = os.environ.get("SHELL") or "/bin/sh"
    try:
        result = subprocess.run(
            [shell, "-lic", f"command -v {shlex.quote(CLI_COMMAND)}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, search_path

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if lines and Path(lines[-1]).is_file():
        return lines[-1], search_path
    return None, search_path


def config_path():
    """Where config.json lives. Packaged apps use a per-user copy, seeded
    from the bundled template, so the app bundle itself stays untouched."""
    bundled = app_directory() / "config.json"
    if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
        return bundled

    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    user_path = base / "Kimi Usage Monitor" / "config.json"

    if user_path.exists():
        return user_path
    if bundled.exists():
        try:
            user_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, user_path)
            return user_path
        except OSError:
            pass
    return bundled


def read_config():
    """Read config.json; return (environment, interval, threshold, sound_alert)."""
    path = config_path()

    environment = QProcessEnvironment.systemEnvironment()

    if not path.exists():
        return (
            environment,
            DEFAULT_INTERVAL_MINUTES,
            DEFAULT_ALERT_THRESHOLD,
            DEFAULT_SOUND_ALERT,
        )

    try:
        with path.open(encoding="utf-8") as file:
            config = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read config.json or its JSON is invalid.") from exc

    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object.")

    variables = config.get("environment", {})
    if not isinstance(variables, dict):
        raise ValueError("The environment field must be a JSON object.")

    for name, value in variables.items():
        if (
            not isinstance(name, str)
            or not name
            or "=" in name
            or "\0" in name
            or not isinstance(value, str)
            or "\0" in value
        ):
            raise ValueError(
                "Environment variable names and values must be valid strings."
            )
        environment.insert(name, value)

    interval = read_int_setting(config, "interval_minutes", DEFAULT_INTERVAL_MINUTES, 1, 1440)
    threshold = read_int_setting(config, "alert_threshold", DEFAULT_ALERT_THRESHOLD, 1, 100)

    sound_alert = config.get("sound_alert", DEFAULT_SOUND_ALERT)
    if not isinstance(sound_alert, bool):
        raise ValueError('"sound_alert" in config.json must be true or false.')

    return environment, interval, threshold, sound_alert


def write_config(token, interval, threshold, sound_alert):
    """Update config.json, preserving keys the app does not manage."""
    path = config_path()

    config = {}
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            config = {}
    if not isinstance(config, dict):
        config = {}

    environment = config.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    token = token.strip()
    if token:
        environment["KIMI_API_KEY"] = token
    else:
        environment.pop("KIMI_API_KEY", None)
    config["environment"] = environment

    config["interval_minutes"] = interval
    config["alert_threshold"] = threshold
    config["sound_alert"] = sound_alert

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def parse_limit(raw):
    """Return the 6h limit if available, otherwise the 5h limit."""
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("kimi"), list):
        raise ValueError("Missing Kimi usage data.")

    entries = data["kimi"]
    entry = None

    for label in ("6h Limit", "5h Limit"):
        entry = next(
            (
                item
                for item in entries
                if isinstance(item, dict) and item.get("label") == label
            ),
            None,
        )
        if entry is not None:
            break

    if entry is None:
        raise ValueError("No 5h or 6h limit found.")

    percentage = entry.get("percent")
    if (
        isinstance(percentage, bool)
        or not isinstance(percentage, (int, float))
        or not math.isfinite(percentage)
        or not 0 <= percentage <= 100
    ):
        raise ValueError("Invalid usage percentage.")

    return entry, percentage


def usage_color(percent):
    if percent >= 90:
        return QColor("#FF3B30")
    if percent >= 70:
        return QColor("#FF9500")
    return QColor("#34C759")


def style_badge(label, kind):
    background, foreground = BADGE_STYLES[kind]
    label.setStyleSheet(
        f"background: {background}; color: {foreground}; border-radius: 9px;"
        " padding: 2px 10px; font-size: 11px; font-weight: 600;"
    )


class RingGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._percent = None
        self._subtext = ""
        self.setMinimumSize(180, 180)

    def set_usage(self, percent, subtext=""):
        self._percent = percent
        self._subtext = subtext
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        side = min(self.width(), self.height())
        pen_width = 13
        margin = pen_width / 2 + 4
        rect = QRectF(
            (self.width() - side) / 2 + margin,
            (self.height() - side) / 2 + margin,
            side - 2 * margin,
            side - 2 * margin,
        )

        track_pen = QPen(QColor("#E9EDF3"), pen_width)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawArc(rect, 0, 360 * 16)

        if self._percent is not None:
            arc_pen = QPen(usage_color(self._percent), pen_width)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            span = -round(min(max(self._percent, 0), 100) / 100 * 360 * 16)
            if span:
                painter.drawArc(rect, 90 * 16, span)

        center_text = f"{self._percent:g}%" if self._percent is not None else "—"
        painter.setPen(QColor("#1C1C1E"))
        font = QFont()
        font.setPointSize(30)
        font.setBold(True)
        painter.setFont(font)
        text_rect = QRectF(rect)
        text_rect.translate(0, -8 if self._subtext else 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, center_text)

        if self._subtext:
            painter.setPen(QColor("#8A8F99"))
            sub_font = QFont()
            sub_font.setPointSize(10)
            painter.setFont(sub_font)
            sub_rect = QRectF(
                rect.x(),
                rect.y() + rect.height() * 0.64,
                rect.width(),
                rect.height() * 0.3,
            )
            painter.drawText(
                sub_rect,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                self._subtext,
            )

        painter.end()


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(15, 23, 42, 18))
        self.setGraphicsEffect(shadow)


class SettingsDialog(QDialog):
    def __init__(self, parent, token, interval, threshold, sound_alert):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.token_edit = QLineEdit(token)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("sk-kimi-...")
        self.token_edit.setMinimumWidth(240)

        show_button = QPushButton("Show")
        show_button.setCheckable(True)
        show_button.toggled.connect(self.on_show_toggled)

        token_row = QHBoxLayout()
        token_row.addWidget(self.token_edit, stretch=1)
        token_row.addWidget(show_button)

        self.interval_edit = QSpinBox()
        self.interval_edit.setRange(1, 1440)
        self.interval_edit.setSuffix(" minutes")
        self.interval_edit.setValue(interval)

        self.threshold_edit = QSpinBox()
        self.threshold_edit.setRange(1, 100)
        self.threshold_edit.setSuffix("%")
        self.threshold_edit.setValue(threshold)

        self.sound_edit = QCheckBox("Play a sound when the alert fires")
        self.sound_edit.setChecked(sound_alert)

        form.addRow("API key:", token_row)
        form.addRow("Refresh interval:", self.interval_edit)
        form.addRow("Alert threshold:", self.threshold_edit)
        form.addRow("", self.sound_edit)
        layout.addLayout(form)

        path_label = QLabel(f"Saved to: {config_path()}")
        path_label.setObjectName("muted")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("Save")
        save_button.setObjectName("primary")
        save_button.setDefault(True)
        save_button.clicked.connect(self.accept)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)
        layout.addLayout(buttons)

    def on_show_toggled(self, checked):
        self.token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )

    def values(self):
        return (
            self.token_edit.text(),
            self.interval_edit.value(),
            self.threshold_edit.value(),
            self.sound_edit.isChecked(),
        )


class UsageMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Kimi Usage Monitor")
        self.resize(400, 470)

        self.interval_minutes = DEFAULT_INTERVAL_MINUTES
        self.alert_threshold = DEFAULT_ALERT_THRESHOLD
        self.sound_alert = DEFAULT_SOUND_ALERT
        try:
            _, self.interval_minutes, self.alert_threshold, self.sound_alert = (
                read_config()
            )
        except ValueError:
            pass  # refresh() surfaces the error in the status line

        self.sound = None
        try:
            self.sound = QSoundEffect(self)
            self.sound.setSource(QUrl.fromLocalFile(str(ensure_alert_sound())))
            self.sound.setVolume(0.5)
        except OSError:
            pass  # alert.wav cannot be created; stay silent

        self.process = QProcess(self)
        self.process.finished.connect(self.on_finished)
        self.process.errorOccurred.connect(self.on_process_error)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)

        self.timeout_timer = QTimer(self)
        self.timeout_timer.setSingleShot(True)
        self.timeout_timer.timeout.connect(self.on_timeout)

        self.timed_out = False
        self.alert_active = False
        self.cli_path = None

        root = QWidget()
        root.setObjectName("root")
        main = QVBoxLayout(root)
        main.setContentsMargins(18, 16, 18, 14)
        main.setSpacing(14)

        # Header
        header = QHBoxLayout()
        header.setSpacing(8)
        self.header_dot = QLabel()
        self.header_dot.setFixedSize(10, 10)
        self.header_dot.setStyleSheet("background: #C7CBD3; border-radius: 5px;")
        title = QLabel("Kimi Code")
        title.setObjectName("appTitle")
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self.open_settings)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        header.addWidget(self.header_dot)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(settings_button)
        header.addWidget(refresh_button)
        main.addLayout(header)

        # Ring card
        ring_card = Card()
        ring_layout = QVBoxLayout(ring_card)
        ring_layout.setContentsMargins(20, 16, 20, 18)
        ring_layout.setSpacing(6)
        self.limit_label = QLabel("USAGE")
        self.limit_label.setObjectName("cardTitle")
        self.limit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ring = RingGauge()
        self.remaining_label = QLabel("Remaining: unavailable")
        self.remaining_label.setObjectName("muted")
        self.remaining_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring_layout.addWidget(self.limit_label)
        ring_layout.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)
        ring_layout.addWidget(self.remaining_label)
        main.addWidget(ring_card)

        # Usage card
        usage_card = Card()
        usage_layout = QVBoxLayout(usage_card)
        usage_layout.setContentsMargins(20, 16, 20, 16)
        usage_layout.setSpacing(8)

        row = QHBoxLayout()
        self.usage_title = QLabel("Session limit")
        self.usage_title.setObjectName("sectionTitle")
        self.percent_label = QLabel("—")
        self.percent_label.setObjectName("value")
        self.badge = QLabel("No data")
        style_badge(self.badge, "neutral")
        row.addWidget(self.usage_title)
        row.addStretch()
        row.addWidget(self.percent_label)
        row.addWidget(self.badge)
        usage_layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        usage_layout.addWidget(self.progress)

        reset_row = QHBoxLayout()
        self.reset_label = QLabel("Reset: unavailable")
        self.reset_label.setObjectName("muted")
        reset_row.addWidget(self.reset_label)
        reset_row.addStretch()
        usage_layout.addLayout(reset_row)

        main.addWidget(usage_card)
        main.addStretch()

        # Footer
        footer = QHBoxLayout()
        self.status = QLabel("Waiting for usage data.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        footer.addWidget(self.status, stretch=1)
        main.addLayout(footer)

        self.setCentralWidget(root)

        icon_path = app_directory() / "kimi_icon.svg"
        if icon_path.exists():
            app_icon = QIcon(str(icon_path))
        else:
            app_icon = self.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        self.setWindowIcon(app_icon)

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon, self)
            self.tray.setToolTip("Kimi Usage Monitor")

            menu = QMenu(self)

            show_action = QAction("Show", self)
            show_action.triggered.connect(self.show_window)

            refresh_action = QAction("Refresh", self)
            refresh_action.triggered.connect(self.refresh)

            quit_action = QAction("Quit", self)
            quit_action.triggered.connect(self.quit_app)

            menu.addAction(show_action)
            menu.addAction(refresh_action)
            menu.addSeparator()
            menu.addAction(quit_action)

            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_tray_activated)
            self.tray.show()

        self.start_timer()
        QTimer.singleShot(0, self.refresh)

    def start_timer(self):
        self.refresh_timer.start(self.interval_minutes * 60_000)

    def open_settings(self):
        try:
            environment, interval, threshold, sound_alert = read_config()
        except ValueError as exc:
            self.status.setText(str(exc))
            return

        dialog = SettingsDialog(
            self,
            environment.value("KIMI_API_KEY"),
            interval,
            threshold,
            sound_alert,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        token, interval, threshold, sound_alert = dialog.values()
        try:
            write_config(token, interval, threshold, sound_alert)
        except OSError as exc:
            self.status.setText(f"Could not save config.json: {exc}")
            return

        if interval != self.interval_minutes:
            self.interval_minutes = interval
            self.start_timer()
        self.alert_threshold = threshold
        self.sound_alert = sound_alert
        self.alert_active = False

        self.status.setText("Settings saved.")
        self.refresh()

    def refresh(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.status.setText("A refresh is already running.")
            return

        try:
            environment, interval, threshold, sound_alert = read_config()
        except ValueError as exc:
            self.status.setText(str(exc))
            return

        if interval != self.interval_minutes:
            self.interval_minutes = interval
            self.start_timer()
        self.alert_threshold = threshold
        self.sound_alert = sound_alert

        search_path = build_search_path(environment)
        environment.insert("PATH", search_path)

        program = self.cli_path or resolve_cli(environment)[0]
        if program is None:
            self.header_dot.setStyleSheet("background: #FF3B30; border-radius: 5px;")
            self.status.setText(
                f"Could not find {CLI_COMMAND}. Check the command name "
                "and whether it is on the application's PATH."
            )
            return
        self.cli_path = program

        self.timed_out = False
        self.status.setText("Refreshing...")
        if sys.platform == "win32":
            # CreateProcess cannot run .cmd/.bat shims (e.g. npm installs)
            # directly, so go through the shell.
            self.process.setProgram("cmd.exe")
            self.process.setArguments(["/c", program, "--json"])
        else:
            self.process.setProgram(program)
            self.process.setArguments(["--json"])
        self.process.setProcessEnvironment(environment)

        self.timeout_timer.start(30_000)
        self.process.start()

    def on_timeout(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.timed_out = True
            self.process.kill()

    def on_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.timeout_timer.stop()
            self.cli_path = None  # re-resolve on the next refresh
            self.header_dot.setStyleSheet("background: #FF3B30; border-radius: 5px;")
            self.status.setText(
                f"Could not start {CLI_COMMAND}. Check the command name "
                "and whether it is on the application's PATH."
            )

    def on_finished(self, exit_code, exit_status):
        self.timeout_timer.stop()

        if self.timed_out:
            self.status.setText("Refresh timed out after 30 seconds.")
            return

        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            self.status.setText(
                f"CLI failed with exit code {exit_code}. "
                "Check its authentication and configuration."
            )
            return

        raw = bytes(self.process.readAllStandardOutput()).decode(
            "utf-8", errors="replace"
        )

        try:
            entry, percentage = parse_limit(raw)
        except (ValueError, TypeError, KeyError):
            self.status.setText(
                "The CLI returned no usage data. Check the API key "
                "in Settings, then press Refresh."
            )
            return

        self.apply_usage(entry, percentage)

    def apply_usage(self, entry, percentage):
        label = str(entry.get("label") or "Usage")
        self.limit_label.setText(label.upper())
        self.usage_title.setText(label)

        reset_at = entry.get("reset_at")
        reset_text = str(reset_at) if reset_at else ""
        self.ring.set_usage(percentage, f"resets {reset_text}" if reset_text else "")
        self.reset_label.setText(
            f"Resets: {reset_text}" if reset_text else "Reset: unavailable"
        )

        remaining = entry.get("remaining")
        if (
            isinstance(remaining, (int, float))
            and not isinstance(remaining, bool)
            and math.isfinite(remaining)
        ):
            suffix = "%" if entry.get("unit") == "%" else ""
            self.remaining_label.setText(f"Remaining: {remaining:g}{suffix}")
        else:
            self.remaining_label.setText("Remaining: unavailable")

        self.percent_label.setText(f"{percentage:g}%")
        self.progress.setValue(round(percentage))
        self.progress.setStyleSheet(PROGRESS_STYLE % usage_color(percentage).name())
        self.update_badge(percentage)

        color = usage_color(percentage).name()
        self.header_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
        if self.tray:
            self.tray.setToolTip(f"Kimi usage: {percentage:g}%")

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status.setText(f"Updated {timestamp}")
        self.check_threshold(percentage)

    def update_badge(self, percentage):
        if percentage >= self.alert_threshold:
            self.badge.setText("Over threshold")
            style_badge(self.badge, "bad")
        else:
            self.badge.setText("On pace")
            style_badge(self.badge, "ok")

    def check_threshold(self, percentage):
        above = percentage >= self.alert_threshold

        if above and not self.alert_active:
            if self.tray:
                self.tray.showMessage(
                    "Kimi usage warning",
                    f"Usage has reached {percentage:g}%.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    5000,
                )
            if self.sound_alert and self.sound:
                self.sound.play()

        self.alert_active = above

    def show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def closeEvent(self, event):
        if self.tray and self.tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self.stop_process()
            event.accept()

    def stop_process(self):
        self.refresh_timer.stop()
        self.timeout_timer.stop()

        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(3000)

    def quit_app(self):
        self.stop_process()
        if self.tray:
            self.tray.hide()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)
    icon_path = app_directory() / "kimi_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = UsageMonitor()
    window.show()
    sys.exit(app.exec())
