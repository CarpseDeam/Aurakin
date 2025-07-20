# src/ava/gui/panel_manager.py
import logging
from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

from src.ava.core.event_bus import EventBus
from src.ava.gui.flow_viewer import FlowViewer
from src.ava.gui.components import Colors, Typography

logger = logging.getLogger(__name__)


class PanelManager(QWidget):
    """
    Manages the tabbed panel area at the bottom of the Code Viewer.

    This widget contains a QTabWidget that can host various informational
    and interactive panels, such as the FlowViewer for visualizing AI
    workflows.
    """

    def __init__(self, event_bus: EventBus, parent: Optional[QWidget] = None):
        """
        Initializes the PanelManager.

        Args:
            event_bus: The application's central event bus, passed to child widgets.
            parent: The parent widget.
        """
        super().__init__(parent)
        self.event_bus = event_bus
        self.flow_viewer: Optional[FlowViewer] = None
        self.tab_widget: Optional[QTabWidget] = None

        self._setup_ui()
        logger.info("PanelManager initialized.")

    def _setup_ui(self) -> None:
        """
        Sets up the user interface for the panel manager, including the
        tab widget and its initial tabs.
        """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.tab_widget = QTabWidget()
        self.tab_widget.setFont(Typography.body())
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border-top: 1px solid {Colors.BORDER_DEFAULT.name()};
            }}
            QTabBar::tab {{
                background-color: {Colors.PRIMARY_BG.name()};
                color: {Colors.TEXT_SECONDARY.name()};
                padding: 8px 15px;
                border: 1px solid {Colors.BORDER_DEFAULT.name()};
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {Colors.SECONDARY_BG.name()};
                color: {Colors.TEXT_PRIMARY.name()};
                border-bottom: 1px solid {Colors.SECONDARY_BG.name()};
            }}
            QTabBar::tab:hover {{
                background-color: {Colors.ELEVATED_BG.name()};
            }}
        """)

        # Create and add the FlowViewer tab
        try:
            self.flow_viewer = FlowViewer(self.event_bus)
            self.tab_widget.addTab(self.flow_viewer, "Workflow Visualizer")
        except Exception as e:
            logger.error(f"Failed to initialize FlowViewer: {e}", exc_info=True)
            # In case of an error, you might want to add a placeholder
            # error_label = QLabel(f"Error loading FlowViewer: {e}")
            # self.tab_widget.addTab(error_label, "Error")

        # Future tabs (e.g., Terminal, Debug Console) can be added here.

        layout.addWidget(self.tab_widget)

    def get_flow_viewer(self) -> Optional[FlowViewer]:
        """
        Returns the instance of the FlowViewer widget.

        This allows other parts of the application, like the EventCoordinator,
        to connect directly to the FlowViewer for event handling.

        Returns:
            The FlowViewer instance if it was created successfully, otherwise None.
        """
        return self.flow_viewer