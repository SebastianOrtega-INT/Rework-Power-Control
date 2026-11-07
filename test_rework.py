import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from storage import StationStore

if os.name != "nt":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox, QPushButton

from ui import IdentityDialog, MainWindow, STYLESHEET


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.store = StationStore(":memory:")
        self.store.load_demo_operators()
        self.addCleanup(self.store.close)

    def test_lookup_preserves_identifier(self):
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO operators (wwid, name) VALUES (?, ?)", ("00123", "Operador")
            )
        self.assertEqual(self.store.lookup_operator(" 00123 ").wwid, "00123")
        self.assertIsNone(self.store.lookup_operator("123"))
        self.assertIsNone(self.store.lookup_operator("' OR 1=1 --"))

    def test_unknown_and_inactive_cannot_start(self):
        with self.store.connection:
            self.store.connection.execute("UPDATE operators SET active = 0 WHERE wwid = '100002'")
        for wwid in ("", "unknown", "100002"):
            with self.subTest(wwid=wwid), self.assertRaises(ValueError):
                self.store.start_session(1, wwid, 15)
        self.assertEqual(len(self.store.recent_sessions()), 0)

    def test_station_and_duration_are_checked(self):
        for station, minutes in ((0, 15), (5, 15), (1, 0), (1, 99)):
            with self.subTest(station=station, minutes=minutes), self.assertRaises(ValueError):
                self.store.start_session(station, "100001", minutes)

    def test_one_open_session_per_station(self):
        session_id, operator = self.store.start_session(1, "100001", 15)
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.start_session(1, "100002", 30)
        self.store.start_session(2, "100002", 30)
        self.store.finish_session(session_id, "manual")
        self.store.start_session(1, operator.wwid, 15)
        self.assertEqual(len(self.store.recent_sessions()), 3)

    def test_audit_keeps_original_name_and_first_close(self):
        session_id, operator = self.store.start_session(1, "100001", 15)
        with self.store.connection:
            self.store.connection.execute("UPDATE operators SET name = 'Otro nombre'")
        self.store.finish_session(session_id, "manual")
        self.store.finish_session(session_id, "timeout")
        row = self.store.recent_sessions()[0]
        self.assertEqual(row["operator_name"], operator.name)
        self.assertEqual(row["end_reason"], "manual")
        self.assertIsNotNone(row["ended_at"])

    def test_recovery_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            first = StationStore(path)
            first.load_demo_operators()
            first.start_session(1, "100001", 15)
            first.close()
            second = StationStore(path)
            try:
                second.recover_sessions()
                row = second.recent_sessions()[0]
                self.assertEqual(row["end_reason"], "interrupted")
                self.assertIsNotNone(row["ended_at"])
                second.start_session(1, "100001", 30)
            finally:
                second.close()

    def test_reports_are_persisted(self):
        self.store.save_report(2, "Otro", "  Cable roto  ")
        row = self.store.connection.execute("SELECT * FROM reports").fetchone()
        self.assertEqual(row["station"], 2)
        self.assertEqual(row["notes"], "Cable roto")


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLESHEET)

    def setUp(self):
        self.store = StationStore(":memory:")
        self.store.load_demo_operators()
        self.window = MainWindow(self.store, demo=True)
        self.card = self.window.cards[0]
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for card in self.window.cards:
            if card.session_id is not None:
                card.finish_session("shutdown")
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.store.close()

    def activate_card(self):
        def identify():
            dialog = self.app.activeModalWidget()
            dialog.receive_identifier("12251003")
            dialog.confirm()
        QTimer.singleShot(0, identify)
        self.card.start_workflow()

    def test_badge_prompt_and_no_exit_button(self):
        dialog = IdentityDialog(self.store, 1, self.window)
        self.assertEqual(dialog.badge_prompt.text(), "Acerca tu badge al lector de barcode o NFC.")
        self.assertNotIn("Salir", [widget.text() for widget in self.window.findChildren(QPushButton)])

    def test_identity_change_requires_new_validation(self):
        dialog = IdentityDialog(self.store, 1, self.window)
        dialog.receive_identifier("unknown")
        self.assertFalse(dialog.activate.isEnabled())
        dialog.receive_identifier("100001")
        self.assertTrue(dialog.activate.isEnabled())
        dialog.wwid.setText("100002")
        self.assertIsNone(dialog.operator)
        self.assertFalse(dialog.activate.isEnabled())

    def test_cancellation_does_not_create_session(self):
        QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
        self.card.start_workflow()
        self.assertIsNone(self.card.session_id)
        self.assertFalse(self.card.timer.isActive())
        self.assertEqual(len(self.store.recent_sessions()), 0)

    def test_activation_and_timeout(self):
        self.activate_card()
        self.assertEqual(self.card.operator.wwid, "12251003")
        self.assertEqual(self.card.operator.name, "Operador de prueba (DEMO)")
        self.assertTrue(self.card.timer.isActive())
        self.assertEqual(self.window.history.rowCount(), 1)
        self.card.deadline = time.monotonic() - 1
        self.card.update_timer()
        self.assertIsNone(self.card.session_id)
        self.assertFalse(self.card.timer.isActive())
        self.assertEqual(self.store.recent_sessions()[0]["end_reason"], "timeout")
        self.assertEqual(self.store.recent_sessions()[0]["wwid"], "12251003")

    def test_manual_close(self):
        self.activate_card()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
            self.card.stop_manual()
        self.assertIsNone(self.card.session_id)
        self.assertEqual(self.store.recent_sessions()[0]["end_reason"], "manual")

    def test_close_failure_blocks_restart_until_retry(self):
        self.activate_card()
        session_id = self.card.session_id
        with patch.object(self.store, "finish_session", side_effect=sqlite3.OperationalError("locked")):
            with patch.object(QMessageBox, "critical"):
                self.assertFalse(self.card.finish_session("manual"))
        self.assertEqual(self.card.session_id, session_id)
        self.assertEqual(self.card.pending_reason, "manual")
        self.assertFalse(self.card.timer.isActive())
        self.assertTrue(self.card.finish_session("manual"))
        self.assertIsNone(self.card.session_id)

    def test_screen_sizes_and_desktop_controls(self):
        self.window.show()
        self.app.processEvents()
        for width, height in ((1100, 780), (800, 600), (480, 800)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertEqual(self.window.width(), width)
            if width == 1100:
                scroll = self.window.tabs.widget(0)
                for card in self.window.cards:
                    point = card.start.mapTo(scroll.viewport(), card.start.rect().bottomRight())
                    self.assertTrue(scroll.viewport().rect().contains(point))


if __name__ == "__main__":
    unittest.main()