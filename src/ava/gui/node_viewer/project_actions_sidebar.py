# src/ava/gui/node_viewer/project_actions_sidebar.py
# NEW FILE
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QSpacerItem, QSizePolicy
from PySide6.QtCore import Qt, Signal
import qtawesome as qta

from src.ava.gui.components import Colors, Typography, ModernButton
from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager


class ProjectActionsSidebar(QWidget):
    """
    A dedicated sidebar for the Node Viewer containing primary project actions
    like running, testing, and healing.
    """

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager, parent: QWidget = None):
        super().__init__(parent)
        self.event_bus = event_bus
        self.project_manager = project_manager

        self.setFixedWidth(250)
        self.setStyleSheet(f"background-color: {Colors.SECONDARY_BG.name()};")

        # --- Main Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(15)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # --- Title ---
        title_label = QLabel("Project Actions")
        title_label.setFont(Typography.get_font(14, 800))  # Heavier weight
        title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY.name()}; padding-bottom: 5px;")
        main_layout.addWidget(title_label)

        # --- Action Buttons ---
        self.run_program_button = ModernButton("Run Program", "primary")
        self.run_program_button.setIcon(qta.icon("fa5s.play", color=Colors.TEXT_PRIMARY.name()))
        self.run_program_button.clicked.connect(self._on_run_program)
        main_layout.addWidget(self.run_program_button)

        self.run_tests_button = ModernButton("Run Tests", "secondary")
        self.run_tests_button.setIcon(qta.icon("fa5s.vial", color=Colors.TEXT_PRIMARY.name()))
        self.run_tests_button.clicked.connect(self._on_run_tests)
        main_layout.addWidget(self.run_tests_button)

        # --- Separator ---
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet(f"border-top: 1px solid {Colors.BORDER_DEFAULT.name()};")
        main_layout.addWidget(separator)

        # --- Status Display ---
        self.status_label = QLabel("Ready")
        self.status_label.setFont(Typography.body())
        self.status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY.name()};")
        self.status_label.setWordWrap(True)
        main_layout.addWidget(self.status_label)

        # --- Heal Button (Initially Hidden) ---
        self.heal_button = ModernButton("Heal with AI", "primary")
        self.heal_button.setIcon(qta.icon("fa5s.heartbeat", color=Colors.TEXT_PRIMARY.name()))
        self.heal_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {Colors.ACCENT_RED.name()};
                color: {Colors.TEXT_PRIMARY.name()};
                border: 1px solid {Colors.BORDER_DEFAULT.name()};
                border-radius: 6px;
                padding: 5px 15px;
            }}
            QPushButton:hover {{
                background-color: {Colors.ACCENT_RED.lighter(110).name()};
            }}
        """)
        self.heal_button.clicked.connect(self._on_heal)
        self.heal_button.hide()
        main_layout.addWidget(self.heal_button)

        main_layout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # Internal state to track the last failed command
        self._last_failed_command_type: Optional[str] = None  # "run" or "test"

    def _on_run_program(self):
        self.hide_heal_button()
        self.status_label.setText("Attempting to run program...")

        entry_point = self._find_entry_point()
        if not entry_point:
            self.status_label.setText("Error: Could not find main.py or app.py.")
            return

        rel_path = entry_point.relative_to(self.project_manager.active_project_path).as_posix()
        command = f"python {rel_path}"
        self._last_failed_command_type = "run"
        self.event_bus.emit("run_program_and_heal_requested", command)

    def _on_run_tests(self):
        self.hide_heal_button()
        self.status_label.setText("Running tests...")
        self._last_failed_command_type = "test"
        self.event_bus.emit("heal_project_requested")

    def _on_heal(self):
        self.hide_heal_button()
        if self._last_failed_command_type == "test":
            self.status_label.setText("Asking Healer to fix test failures...")
            self.event_bus.emit("heal_project_requested")
        elif self._last_failed_command_type == "run":
            # The run command itself triggers the heal workflow if it fails,
            # but we can re-trigger if needed, or just let the user re-run.
            # For now, let's just re-run the original command.
            self.status_label.setText("Re-running program to trigger heal...")
            self._on_run_program()

    def _find_entry_point(self) -> Optional[Path]:
        """Finds a common entry point file like main.py or app.py."""
        if not self.project_manager.active_project_path:
            return None

        common_files = ["main.py", "app.py"]
        for file in common_files:
            path = self.project_manager.active_project_path / file
            if path.exists():
                return path
        return None

    def update_on_command_finish(self, exit_code: int):
        """Called when a command from this sidebar finishes."""
        if exit_code == 0:
            self.status_label.setText("Last action finished successfully.")
            self.hide_heal_button()
        else:
            self.status_label.setText("Last action failed. AI healing is available.")
            self.show_heal_button()

    def show_heal_button(self):
        self.heal_button.show()

    def hide_heal_button(self):
        self._last_failed_command_type = None
        self.heal_button.hide()