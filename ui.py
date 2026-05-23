from __future__ import annotations

import io
import os
import sys
import traceback
import ctypes
import subprocess
from pathlib import Path
from threading import Event

from PyQt6.QtCore import QObject, QRectF, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig


def _resource_dir() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _log_file_path() -> Path:
    return _runtime_base_dir() / "automation.log"


def _logo_candidates() -> list[Path]:
    resource = _resource_dir()
    runtime = _runtime_base_dir()
    return [
        resource / "ccl_pd.jpeg",
        runtime / "ccl_pd.jpeg",
        resource / "logo.png",
        runtime / "logo.png",
        resource / "assets" / "ccl_pd.jpeg",
        runtime / "assets" / "ccl_pd.jpeg",
        resource / "assets" / "logo.png",
        runtime / "assets" / "logo.png",
    ]


class LogStream(io.TextIOBase):
    def __init__(self, emit_signal, mirror_stream, log_file_path: Path) -> None:
        self.emit_signal = emit_signal
        self.mirror_stream = mirror_stream
        self.log_file_path = log_file_path
        self._buffer = ""

    def write(self, text):
        if not text:
            return 0

        self.mirror_stream.write(text)
        self.mirror_stream.flush()

        try:
            with self.log_file_path.open("a", encoding="utf-8") as log_file:
                log_file.write(text)
        except Exception:
            pass

        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.emit_signal(line.rstrip("\r"))
        return len(text)

    def flush(self):
        if self._buffer:
            self.emit_signal(self._buffer.rstrip("\r"))
            self._buffer = ""
        self.mirror_stream.flush()


class AutomationWorker(QObject):
    log_line = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, csv_path: str) -> None:
        super().__init__()
        self.csv_path = csv_path
        self._stop_requested = Event()
        self._process: subprocess.Popen | None = None

    def stop(self) -> None:
        self._stop_requested.set()
        self._terminate_process_tree()

    def run(self) -> None:
        try:
            self.status_changed.emit("Running automation...")
            self._run_subprocess_automation()
            self.status_changed.emit("Completed successfully.")
            self.finished.emit(True, "Automation completed successfully.")
        except BaseException as error:
            tb_text = traceback.format_exc()
            self.log_line.emit(tb_text.rstrip())
            self.status_changed.emit("Failed.")
            self.finished.emit(False, str(error))

    def _run_subprocess_automation(self) -> None:
        command = self._build_automation_command(self.csv_path)
        self._write_runtime_log(f"Running command: {' '.join(command)}")
        self._write_runtime_log("Automation starting in background...")
        self.log_line.emit(f"Running command: {' '.join(command)}")
        self.log_line.emit("Automation starting in background...")

        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        env = {
            **os.environ,
            "OA_PARENT_PID": str(os.getpid()),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }

        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=str(_runtime_base_dir()),
            creationflags=creationflags,
            env=env,
        )

        if self._process.stdout is not None:
            log_stream = LogStream(self.log_line.emit, io.StringIO(), _log_file_path())
            while True:
                if self._stop_requested.is_set():
                    self._terminate_process_tree()
                    raise RuntimeError("Automation cancelled by user.")

                line = self._process.stdout.readline()
                if line:
                    log_stream.write(line)
                    continue

                if self._process.poll() is not None:
                    break
            log_stream.flush()

        return_code = self._process.wait()
        if self._stop_requested.is_set():
            raise RuntimeError("Automation cancelled by user.")

        if return_code != 0:
            raise RuntimeError(
                f"Automation process exited with code {return_code}. Check logs at {_log_file_path()}"
            )

    @staticmethod
    def _write_runtime_log(message: str) -> None:
        try:
            with _log_file_path().open("a", encoding="utf-8") as log_file:
                log_file.write(message + "\n")
        except Exception:
            pass

    def _terminate_process_tree(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is not None:
            return

        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
        else:
            process.terminate()

    @staticmethod
    def _build_automation_command(csv_path: str) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-automation", csv_path]

        main_script = Path(__file__).resolve().with_name("main.py")
        return [sys.executable, str(main_script), "--run-automation", csv_path]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Overleaf Automation Tool")
        self.resize(980, 660)
        self._setup_window_icon()

        self.base_config = AppConfig.from_environment()
        self.thread: QThread | None = None
        self.worker: AutomationWorker | None = None
        self._run_in_progress = False
        self._closing = False

        self.csv_path_input = QLineEdit()
        self.csv_path_input.setReadOnly(True)
        self.csv_path_input.setPlaceholderText("Select recipients CSV file...")

        default_csv_path = Path(self.base_config.recipients_csv_path)
        if not default_csv_path.is_absolute():
            default_csv_path = Path.cwd() / default_csv_path
        self.csv_path_input.setText(str(default_csv_path))

        self.browse_button = QPushButton("Choose File")
        self.open_logs_button = QPushButton("Open Logs")
        self.start_button = QPushButton("Start Automation")
        self.status_label = QLabel("Status: Idle")
        self.log_output = QPlainTextEdit()
        self.logo_label = QLabel()
        self.footer_label = QLabel(
            "This automation software is built by UIU Computer Club Programming Department."
        )

        self._setup_theme()
        self._setup_logo()

        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Run logs will appear here...")

        self.browse_button.clicked.connect(self.choose_csv)
        self.open_logs_button.clicked.connect(self.open_logs)
        self.start_button.clicked.connect(self.start_automation)

        header = QLabel("Overleaf Team Automation")
        header.setObjectName("title")
        subtitle = QLabel("Share links and email all team members directly from your CSV file")
        subtitle.setObjectName("subtitle")

        csv_group = QGroupBox("Recipients File")
        csv_layout = QVBoxLayout()
        csv_hint = QLabel("Upload a CSV file in the supported format to begin.")
        csv_hint.setObjectName("hint")
        csv_row = QHBoxLayout()
        csv_row.addWidget(self.csv_path_input, 1)
        csv_row.addWidget(self.browse_button)
        csv_row.addWidget(self.open_logs_button)
        csv_layout.addWidget(csv_hint)
        csv_layout.addLayout(csv_row)
        csv_group.setLayout(csv_layout)

        control_row = QHBoxLayout()
        control_row.addWidget(self.start_button)
        control_row.addStretch(1)
        control_row.addWidget(self.status_label)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(14, 10, 14, 10)
        footer_layout.setSpacing(12)
        footer_layout.addWidget(self.logo_label)
        footer_layout.addWidget(self.footer_label, 1)
        footer.setLayout(footer_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)
        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addWidget(csv_group)
        layout.addLayout(control_row)
        layout.addWidget(self.log_output, 1)
        layout.addWidget(footer)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _setup_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #fff8ef; }
            QLabel#title {
                color: #9a4f00;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#subtitle {
                color: #5e5e5e;
                font-size: 13px;
            }
            QLabel#hint {
                color: #6a6a6a;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #ffc47a;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 10px;
                background: #fffefc;
                font-weight: 600;
                color: #8a4800;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit {
                border: 1px solid #ffcc8f;
                border-radius: 8px;
                padding: 9px 10px;
                background: white;
                color: #343434;
            }
            QLineEdit:focus {
                border: 1px solid #f08801;
            }
            QPushButton {
                background: #f08801;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 9px 14px;
                font-weight: 600;
            }
            QPushButton:hover { background: #de7a00; }
            QPushButton:pressed { background: #bf6800; }
            QPushButton:disabled {
                background: #f7c98b;
                color: #fff6eb;
            }
            QPlainTextEdit {
                border: 1px solid #ffd8a8;
                border-radius: 10px;
                background: #ffffff;
                color: #1f1f1f;
                padding: 6px;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
            }
            QLabel {
                color: #333333;
            }
            QFrame#footer {
                background: #111111;
                border-radius: 10px;
            }
            """
        )
        self.footer_label.setStyleSheet("color: #f8f8f8; font-size: 12px; font-weight: 500;")
        self.status_label.setStyleSheet(
            "background: #fff1df; color: #8a4800; border: 1px solid #ffcc8f; border-radius: 7px; padding: 6px 10px;"
        )

    def _setup_window_icon(self) -> None:
        source = self._load_logo_source()
        if source is not None:
            self.setWindowIcon(QIcon(source))

    def _setup_logo(self) -> None:
        logo_size = 44
        self.logo_label.setFixedSize(logo_size, logo_size)
        self.logo_label.setPixmap(self._build_logo_pixmap(logo_size))

    def _build_logo_pixmap(self, size: int) -> QPixmap:
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = canvas.rect().adjusted(1, 1, -1, -1)
        rect_f = QRectF(rect)

        source = self._load_logo_source()
        if source is not None:
            clip_path = QPainterPath()
            clip_path.addEllipse(rect_f)
            painter.setClipPath(clip_path)
            painter.drawPixmap(rect, source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            painter.setClipping(False)
            painter.setPen(QColor("#f08801"))
            painter.drawEllipse(rect_f)
        else:
            painter.setBrush(QColor("#f08801"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(rect_f)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect_f, Qt.AlignmentFlag.AlignCenter, "UIU")

        painter.end()
        return canvas

    @staticmethod
    def _load_logo_source() -> QPixmap | None:
        for path in _logo_candidates():
            if path.exists() and path.is_file():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap
        return None

    def choose_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select recipients CSV",
            str(Path.cwd()),
            "CSV Files (*.csv);;All Files (*)",
        )
        if file_path:
            self.csv_path_input.setText(file_path)

    def open_logs(self) -> None:
        log_path = _log_file_path()
        if not log_path.exists():
            QMessageBox.information(
                self,
                "No Logs Yet",
                f"No log file exists yet. It will be created after the first run.\nPath: {log_path}",
            )
            return
        import os

        os.startfile(str(log_path))

    def append_log(self, message: str) -> None:
        if message:
            self.log_output.appendPlainText(message)

    def set_busy(self, busy: bool) -> None:
        self._run_in_progress = busy
        self.start_button.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.csv_path_input.setEnabled(not busy)
        self.open_logs_button.setEnabled(True)

    def start_automation(self) -> None:
        if self._run_in_progress:
            QMessageBox.information(self, "Already running", "Automation is already running.")
            return

        csv_path = self.csv_path_input.text().strip()
        if not csv_path:
            QMessageBox.warning(self, "Missing CSV", "Please select a CSV file first.")
            return

        csv_file = Path(csv_path)
        if not csv_file.exists() or not csv_file.is_file():
            QMessageBox.warning(self, "Invalid CSV", "The selected file does not exist.")
            return
        if csv_file.suffix.lower() != ".csv":
            QMessageBox.warning(self, "Invalid File Type", "Please select a .csv file.")
            return

        self.log_output.clear()
        self.append_log(f"Log file: {_log_file_path()}")
        self.status_label.setText("Status: Preparing...")
        self.set_busy(True)
        self.status_label.setText("Status: Launching automation...")

        self.thread = QThread(self)
        self.worker = AutomationWorker(str(csv_file))
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.log_line.connect(self.append_log)
        self.worker.status_changed.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self._cleanup_worker_state)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()

    def on_finished(self, success: bool, message: str) -> None:
        self.set_busy(False)
        if success:
            self.status_label.setText(f"Status: {message}")
        else:
            self.status_label.setText("Status: Failed")
        if not success and not self._closing:
            QMessageBox.critical(self, "Automation failed", message)

    def _cleanup_worker_state(self) -> None:
        self.thread = None
        self.worker = None

    def closeEvent(self, event) -> None:
        self._closing = True
        if self._run_in_progress and self.worker is not None:
            answer = QMessageBox.question(
                self,
                "Stop Running Automation",
                "Automation is still running. Do you want to stop it and close the app?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._closing = False
                event.ignore()
                return

            self.status_label.setText("Status: Stopping...")
            try:
                self.worker.stop()
            except Exception:
                pass

            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(3000)

        event.accept()


def launch_app() -> None:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("uiu.ccpd.overleaf.automation")
        except Exception:
            pass

    app = QApplication(sys.argv)
    for path in _logo_candidates():
        if path.exists() and path.is_file():
            app.setWindowIcon(QIcon(str(path)))
            break
    window = MainWindow()
    window.show()
    sys.exit(app.exec())