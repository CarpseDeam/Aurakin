# src/ava/gui/main_window.py
from pathlib import Path
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QApplication
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent

from src.ava.core.event_bus import EventBus
from src.ava.gui.chat_interface import ChatInterface
from src.ava.gui.enhanced_sidebar import EnhancedSidebar
from src.ava.gui.status_bar import StatusBar


class MainWindow(QMainWindow):
    """
    Main window of the application, holding the sidebar and chat interface.
    """

    def __init__(self, event_bus: EventBus, project_root: Path):
        super().__init__()
        self.event_bus = event_bus
        self.project_root = project_root
        self._closing = False

        self.setWindowTitle("Aurakin")
        self.resize(1400, 900)
        self.setMinimumSize(800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = EnhancedSidebar(event_bus)
        self.chat_interface = ChatInterface(event_bus, self.project_root)

        main_layout.addWidget(self.sidebar, 1)
        main_layout.addWidget(self.chat_interface, 3)

        self.status_bar = StatusBar(self.event_bus)
        self.setStatusBar(self.status_bar)

    def closeEvent(self, event: QCloseEvent):
        """
        Handles the window close event. Instead of quitting directly,
        it emits a shutdown request and ignores the event, allowing the
        Application class to perform a graceful async shutdown.
        """
        if not self._closing:
            self._closing = True
            print("[MainWindow] Close event triggered. Emitting 'application_shutdown_requested'.")
            # Emit the signal for the Application to start its async shutdown.
            self.event_bus.emit("application_shutdown_requested")
            # Tell Qt to IGNORE this close event. The application will be closed
            # programmatically after the async cleanup is finished.
            event.ignore()
        else:
            # If shutdown is already in progress, just accept the event.
            event.accept()