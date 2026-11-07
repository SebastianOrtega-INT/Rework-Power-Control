import argparse
import sqlite3
import sys
from pathlib import Path

from PyQt5.QtCore import QLockFile
from PyQt5.QtWidgets import QApplication, QMessageBox

from storage import DEFAULT_DATABASE, StationStore
from ui import MainWindow, STYLESHEET


def main():
    parser = argparse.ArgumentParser(description="Panel de estaciones de retrabajo")
    parser.add_argument("--demo", action="store_true", help="Habilitar usuarios de prueba")
    parser.add_argument("--windowed", action="store_true", help="Abrir en ventana")
    parser.add_argument("--database", type=Path, help="Ruta a la base SQLite")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("Rework Station")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    database = args.database or (
        DEFAULT_DATABASE.with_name("rework_demo.db") if args.demo else DEFAULT_DATABASE
    )
    database = database.resolve()
    lock = QLockFile(str(database) + ".lock")
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.warning(
            None, "Base de datos ocupada",
            "Otra instancia utiliza esta base o no se puede crear el archivo de bloqueo.",
        )
        return 1
    try:
        store = StationStore(database)
        store.recover_sessions()
        if args.demo:
            store.load_demo_operators()
    except sqlite3.Error as error:
        QMessageBox.critical(None, "Base de datos no disponible", str(error))
        return 1
    window = MainWindow(store, demo=args.demo)
    if args.windowed:
        window.show()
    else:
        window.showFullScreen()
    try:
        return app.exec_()
    finally:
        store.close()
        lock.unlock()


if __name__ == "__main__":
    sys.exit(main())