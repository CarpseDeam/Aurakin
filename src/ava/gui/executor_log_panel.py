# src/ava/gui/executor_log_panel.py
# NEW FILE
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTextEdit
from PySide6.QtCore import Qt

from src.ava.gui.components import Colors, Typography

class ExecutorLogPanel(QWidget):
    """
    A read-only text panel that displays live output from the ExecutionService,
    simulating a terminal view.
    """

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("ExecutorLogPanel")

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(Typography.get_font(10, family="JetBrains Mono"))
        self.log_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: {Colors.PRIMARY_BG.name()};
                color: {Colors.TEXT_PRIMARY.name()};
                border: none;
                padding: 10px;
            }}
        """)
        # Ensure scrollbar is always at the bottom when new text is added
        self.log_view.textChanged.connect(self._scroll_to_bottom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.log_view)
        self.setLayout(layout)

    def append_output(self, line: str):
        """Appends a new line of text to the log view."""
        self.log_view.append(line)

    def clear_output(self):
        """Clears all text from the log view."""
        self.log_view.clear()

    def _scroll_to_bottom(self):
        """Automatically scrolls the view to the last line."""
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())