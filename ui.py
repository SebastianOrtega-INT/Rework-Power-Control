import sqlite3
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QLayout, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
    QStyle, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)


STYLESHEET = """
QWidget { font-family: 'Segoe UI'; font-size: 14px; color: #202b32; }
QMainWindow, QDialog { background: #eef2f3; }
QLabel { background: transparent; border: none; }
QLabel#brand { font-size: 28px; font-weight: 700; }
QLabel#heading { font-size: 22px; font-weight: 700; }
QLabel#muted { color: #596a73; }
QFrame#header { background: #ffffff; border-bottom: 2px solid #007b83; }
QFrame#station { background: #ffffff; border: 1px solid #cbd6da; border-radius: 8px; }
QPushButton { min-height: 42px; padding: 4px 16px; border: 1px solid #bac9cf;
    border-radius: 6px; background: #ffffff; font-weight: 600; }
QPushButton:hover { background: #e1eff0; border-color: #007b83; }
QPushButton:pressed { background: #c8e3e5; }
QPushButton:disabled { color: #89969c; background: #edf0f1; }
QPushButton#primary { background: #007b83; color: white; border: none; }
QPushButton#primary:hover { background: #00656c; }
QPushButton#primary:disabled { background: #a2b9bc; }
QPushButton#stop { color: #af303c; border-color: #d99a9f; }
QLineEdit, QComboBox, QTextEdit { background: white; border: 1px solid #b6c6cd;
    border-radius: 4px; padding: 10px; selection-background-color: #007b83; }
QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 2px solid #007b83; }
QTabWidget::pane { border: none; }
QTabBar::tab { padding: 14px 24px; background: #e0e7ea; margin-right: 3px; }
QTabBar::tab:selected { background: #ffffff; color: #006c74; border-bottom: 3px solid #007b83; }
QProgressBar { background: #e7edef; border: none; border-radius: 3px; height: 8px; }
QProgressBar::chunk { background: #007b83; border-radius: 3px; }
QTableWidget { background: white; alternate-background-color: #f3f7f8;
    border: 1px solid #cbd6da; gridline-color: #e4ebee; }
QHeaderView::section { background: #e1e9ec; border: none; padding: 10px; font-weight: 600; }
QScrollArea { border: none; background: transparent; }
"""


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, icon, name=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setIcon(widget.style().standardIcon(icon))
    return widget


class IdentityDialog(QDialog):
    def __init__(self, store, station, parent=None):
        super().__init__(parent)
        self.store = store
        self.operator = None
        self.minutes = None
        self.setWindowTitle("Validacion de identidad")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.addWidget(label(f"Activar estacion {station:02d}", "heading"))
        self.badge_prompt = label("Acerca tu badge al lector de barcode o NFC.", "muted", True)
        layout.addWidget(self.badge_prompt)
        self.wwid = QLineEdit()
        self.wwid.setPlaceholderText("WWID del badge")
        self.wwid.setMaxLength(64)
        self.wwid.setClearButtonEnabled(True)
        self.wwid.setAccessibleName("Identificador WWID")
        form = QFormLayout()
        form.addRow("WWID", self.wwid)
        layout.addLayout(form)
        validate = button("Validar identidad", QStyle.SP_DialogApplyButton, "primary")
        validate.clicked.connect(self.validate_identity)
        self.wwid.returnPressed.connect(self.validate_identity)
        self.wwid.textChanged.connect(self.reset_identity)
        layout.addWidget(validate)
        self.identity = label("Identidad pendiente", "muted", True)
        layout.addWidget(self.identity)
        self.duration = QComboBox()
        for minutes in (15, 30, 45, 60):
            self.duration.addItem(f"{minutes} minutos", minutes)
        form_time = QFormLayout()
        form_time.addRow("Duracion", self.duration)
        layout.addLayout(form_time)
        actions = QDialogButtonBox(QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.activate = actions.addButton("Confirmar activacion", QDialogButtonBox.AcceptRole)
        self.activate.setObjectName("primary")
        self.activate.setEnabled(False)
        self.activate.setAutoDefault(False)
        actions.accepted.connect(self.confirm)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self.wwid.setFocus()

    def reset_identity(self):
        self.operator = None
        self.activate.setEnabled(False)
        self.identity.setText("Identidad pendiente")

    def receive_identifier(self, identifier):
        self.wwid.setText(identifier.strip())
        self.validate_identity()

    def validate_identity(self):
        try:
            self.operator = self.store.lookup_operator(self.wwid.text())
        except sqlite3.Error:
            self.reset_identity()
            self.identity.setText("No se puede consultar la base de datos.")
            return
        self.activate.setEnabled(self.operator is not None)
        self.identity.setText(
            f"{self.operator.name}\nWWID {self.operator.wwid}"
            if self.operator else "WWID no registrado o usuario inactivo."
        )

    def confirm(self):
        self.validate_identity()
        if self.operator is not None:
            self.minutes = self.duration.currentData()
            self.accept()


class StationCard(QFrame):
    changed = pyqtSignal()

    def __init__(self, station_number, store, parent=None):
        super().__init__(parent)
        self.station_number = station_number
        self.store = store
        self.session_id = None
        self.operator = None
        self.deadline = 0.0
        self.total_seconds = 0
        self.pending_reason = None
        self.setObjectName("station")
        self.setMinimumHeight(230)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(self.style().standardIcon(QStyle.SP_ComputerIcon).pixmap(32, 32))
        top.addWidget(icon)
        top.addWidget(label(f"Estacion {station_number:02d}", "heading"))
        top.addStretch()
        self.badge = label("DISPONIBLE")
        top.addWidget(self.badge)
        layout.addLayout(top)
        layout.addWidget(label("SISTEMA DE SOLDADURA", "muted"))
        self.identity = label("Sin operador asignado", "muted", True)
        layout.addWidget(self.identity)
        self.clock = label("00:00")
        self.clock.setStyleSheet("font-size: 28px; font-weight: 600; font-family: Consolas;")
        layout.addWidget(self.clock)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(8)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)
        self.start = button("Activar sistema", QStyle.SP_MediaPlay, "primary")
        self.stop = button("Finalizar sesion", QStyle.SP_MediaStop, "stop")
        self.start.clicked.connect(self.start_workflow)
        self.stop.clicked.connect(self.stop_manual)
        self.stop.hide()
        layout.addWidget(self.start)
        layout.addWidget(self.stop)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.set_badge("DISPONIBLE", "#167044")

    def set_badge(self, text, color):
        self.badge.setText(text)
        self.badge.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")

    def start_workflow(self):
        if self.session_id is not None:
            return
        dialog = IdentityDialog(self.store, self.station_number, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        try:
            self.session_id, self.operator = self.store.start_session(
                self.station_number, dialog.operator.wwid, dialog.minutes
            )
        except (sqlite3.Error, ValueError) as error:
            QMessageBox.warning(self, "Activacion bloqueada", str(error))
            return
        self.total_seconds = dialog.minutes * 60
        self.deadline = time.monotonic() + self.total_seconds
        self.identity.setText(f"{self.operator.name} | WWID {self.operator.wwid}")
        self.start.hide()
        self.stop.show()
        self.set_badge("EN USO", "#007b83")
        self.update_timer()
        self.timer.start(250)
        self.changed.emit()

    def update_timer(self):
        remaining = max(0, int(self.deadline - time.monotonic() + 0.999))
        self.clock.setText(f"{remaining // 60:02d}:{remaining % 60:02d}")
        self.progress.setValue(round(remaining * 100 / self.total_seconds))
        if remaining == 0:
            self.finish_session("timeout")

    def stop_manual(self):
        if self.pending_reason:
            self.finish_session(self.pending_reason)
            return
        answer = QMessageBox.question(
            self, "Finalizar sesion", f"Finalizar la estacion {self.station_number:02d}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.finish_session("manual")

    def finish_session(self, reason):
        if self.session_id is None:
            return True
        self.timer.stop()
        try:
            self.store.finish_session(self.session_id, reason)
        except sqlite3.Error as error:
            self.pending_reason = reason
            self.set_badge("CIERRE PENDIENTE", "#af303c")
            self.stop.setText("Reintentar cierre")
            QMessageBox.critical(self, "Error al guardar el cierre", str(error))
            return False
        self.session_id = None
        self.operator = None
        self.pending_reason = None
        self.clock.setText("00:00")
        self.progress.setValue(0)
        self.identity.setText("Sin operador asignado")
        self.set_badge("DISPONIBLE", "#167044")
        self.stop.setText("Finalizar sesion")
        self.stop.hide()
        self.start.show()
        self.changed.emit()
        return True


class ReportDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Reportar incidencia")
        self.resize(500, 440)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Nueva incidencia", "heading"))
        form = QFormLayout()
        self.station = QComboBox()
        for station in range(1, 5):
            self.station.addItem(f"Estacion {station:02d}", station)
        self.issue = QComboBox()
        self.issue.addItems([
            "Fallo de estacion", "Punta danada", "Fallo del calentador",
            "Error de temperatura", "Cable danado", "Fallo de alimentacion",
            "Calibracion requerida", "Fallo del ventilador", "Otro",
        ])
        self.notes = QTextEdit()
        form.addRow("Estacion", self.station)
        form.addRow("Problema", self.issue)
        form.addRow("Observaciones", self.notes)
        layout.addLayout(form)
        actions = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        actions.button(QDialogButtonBox.Save).setText("Guardar incidencia")
        actions.button(QDialogButtonBox.Cancel).setText("Cancelar")
        actions.accepted.connect(self.save_report)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def save_report(self):
        try:
            self.store.save_report(
                self.station.currentData(), self.issue.currentText(), self.notes.toPlainText()
            )
        except sqlite3.Error as error:
            QMessageBox.warning(self, "No se pudo guardar", str(error))
            return
        QMessageBox.information(self, "Incidencia registrada", "El reporte se ha guardado.")
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, store, demo=False):
        super().__init__()
        self.store = store
        self.setWindowTitle("Rework Station | Control de sistemas")
        self.resize(1100, 780)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)
        header = QFrame()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        titles = QVBoxLayout()
        titles.addWidget(label("REWORK STATION", "brand"))
        titles.addWidget(label("CONTROL DE SISTEMAS / MINNOWBOARD", "muted"))
        header_layout.addLayout(titles)
        header_layout.addStretch()
        self.date = label("", "muted")
        header_layout.addWidget(self.date)
        self.logo = QLabel()
        self.logo.setObjectName("logo")
        self.logo.setFixedSize(112, 52)
        self.logo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.logo.setAccessibleName("Logo Intel")
        logo_image = QPixmap(str(Path(__file__).resolve().parent / "Intel-Logo-PNG-Pic.png"))
        if logo_image.isNull():
            self.logo.setText("intel")
        else:
            self.logo.setPixmap(logo_image.scaled(
                self.logo.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))
        header_layout.addWidget(self.logo)
        layout.addWidget(header)
        self.summary = label("", "muted")
        layout.addWidget(self.summary)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        systems = QWidget()
        self.grid = QGridLayout(systems)
        self.grid.setSpacing(16)
        self.cards = []
        for station in range(1, 5):
            card = StationCard(station, store)
            card.changed.connect(self.refresh)
            self.cards.append(card)
        scroll.setWidget(systems)
        self.tabs.addTab(scroll, "Sistemas")
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.addWidget(label("Registro de uso", "heading"))
        self.history = QTableWidget(0, 7)
        self.history.setHorizontalHeaderLabels([
            "Estacion", "WWID", "Operador", "Inicio", "Minutos", "Fin", "Estado",
        ])
        self.history.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.history.setAlternatingRowColors(True)
        self.history.verticalHeader().hide()
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.history.horizontalHeader().setStretchLastSection(True)
        history_layout.addWidget(self.history)
        refresh = button("Actualizar registro", QStyle.SP_BrowserReload)
        refresh.clicked.connect(self.refresh)
        history_layout.addWidget(refresh, alignment=Qt.AlignRight)
        self.tabs.addTab(history_page, "Historial")
        self.tabs.currentChanged.connect(self.refresh)
        footer = QHBoxLayout()
        self.hardware_status = label("DEMO | GPIO sin conectar" if demo else "GPIO sin conectar", "muted")
        footer.addWidget(self.hardware_status)
        footer.addStretch()
        report = button("Reportar incidencia", QStyle.SP_MessageBoxWarning)
        report.clicked.connect(self.open_report)
        footer.addWidget(report)
        layout.addLayout(footer)
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_date)
        self.clock_timer.start(1000)
        self.update_date()
        self.arrange_cards()
        self.refresh()
        self.setMinimumSize(460, 360)

    def arrange_cards(self):
        columns = 2 if self.width() >= 900 else 1
        for card in self.cards:
            self.grid.removeWidget(card)
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        self.date.setVisible(self.width() >= 700)
        self.hardware_status.setVisible(self.width() >= 600)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "cards"):
            self.arrange_cards()

    def update_date(self):
        self.date.setText(datetime.now().strftime("%d/%m/%Y  %H:%M:%S"))

    @staticmethod
    def local_date(value):
        return datetime.fromisoformat(value).astimezone().strftime("%d/%m %H:%M:%S") if value else "-"

    def refresh(self):
        active = sum(card.session_id is not None for card in self.cards)
        self.summary.setText(f"04 sistemas  |  {4 - active:02d} disponibles  |  {active:02d} en uso")
        try:
            rows = self.store.recent_sessions()
        except sqlite3.Error:
            self.summary.setText("Registro no disponible. Compruebe la base de datos.")
            self.history.setRowCount(0)
            return
        reasons = {
            "manual": "Finalizada", "timeout": "Tiempo agotado",
            "shutdown": "Cierre de aplicacion", "interrupted": "Interrumpida",
        }
        self.history.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                f"{row['station']:02d}", row["wwid"], row["operator_name"],
                self.local_date(row["started_at"]), str(row["planned_minutes"]),
                self.local_date(row["ended_at"]), reasons.get(row["end_reason"], "En uso"),
            ]
            for column, value in enumerate(values):
                self.history.setItem(row_index, column, QTableWidgetItem(value))

    def open_report(self):
        ReportDialog(self.store, self).exec_()

    def closeEvent(self, event):
        active = [card for card in self.cards if card.session_id is not None]
        if active:
            answer = QMessageBox.question(
                self, "Cerrar panel", "Hay sesiones abiertas. Finalizarlas y salir?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for card in active:
                if not card.finish_session(card.pending_reason or "shutdown"):
                    event.ignore()
                    return
        event.accept()