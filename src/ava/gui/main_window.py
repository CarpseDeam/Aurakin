# src/ava/gui/main_window.py
from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent

from src.ava.core.event_bus import EventBus
from src.ava.gui.chat_interface import ChatInterface
from src.ava.gui.enhanced_sidebar import EnhancedSidebar
from src.ava.gui.status_bar import StatusBar


class MainWindow(QMainWindow):  # <-- PROMOTED from QWidget to QMainWindow
    """
    Main window of the application, holding the sidebar and chat interface.
    """

    def __init__(self, event_bus: EventBus, project_root: Path):
        super().__init__()
        self.event_bus = event_bus
        self.project_root = project_root
        self._closing = False

        # --- Window Properties ---
        self.setWindowTitle("Aurakin")
        self.resize(1400, 900)
        self.setMinimumSize(800, 600)

        # --- Central Widget and Layout ---
        # QMainWindow has a special way of setting its main content area
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Components ---
        self.sidebar = EnhancedSidebar(event_bus)
        self.chat_interface = ChatInterface(event_bus, self.project_root)

        # --- Add Components to Layout ---
        main_layout.addWidget(self.sidebar, 1)
        main_layout.addWidget(self.chat_interface, 3)

        # --- Status Bar Setup (NEW) ---
        # Now that this is a QMainWindow, we can set a status bar
        self.status_bar = StatusBar(self.event_bus)
        self.setStatusBar(self.status_bar)

    def closeEvent(self, event: QCloseEvent):
        """
        Handles the window close event by properly quitting the application,
        which allows the main async loop to perform graceful cleanup.
        """
        if not self._closing:
            self._closing = True
            print("[MainWindow] Close event triggered. Asking application to quit gracefully.")
            # This is the correct, standard way to initiate a shutdown.
            # It will trigger the 'aboutToQuit' signal in the main event loop.
            QApplication.instance().quit()
        event.accept()