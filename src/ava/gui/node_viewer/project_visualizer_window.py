# src/ava/gui/node_viewer/project_visualizer_window.py
"""
A widget that visualizes the project structure as a node graph.

This window listens for events related to the code generation process.
It pre-calculates the positions of all file nodes based on the initial plan
and then draws each node as it is about to be generated.
"""
import logging
import math
from typing import Dict, List, Optional, Set

from PyQt6.QtCore import QPointF, Qt, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QPainter
from PyQt6.QtWidgets import QGraphicsScene, QGraphicsView, QVBoxLayout, QWidget

from src.ava.core.event_bus import EventBus
from src.ava.gui.node_viewer.project_node import ProjectNode

logger = logging.getLogger(__name__)


class ProjectVisualizerWindow(QWidget):
    """
    A widget that visualizes the project structure as a node graph.

    This window listens for events related to the code generation process.
    It pre-calculates the positions of all file nodes based on the initial plan
    and then draws each node as it is about to be generated.
    """

    def __init__(self, event_bus: EventBus, parent: Optional[QWidget] = None):
        """
        Initializes the ProjectVisualizerWindow.

        Args:
            event_bus: The application's event bus for communication.
            parent: The parent widget, if any.
        """
        super().__init__(parent)
        self.event_bus = event_bus
        self.nodes: Dict[str, ProjectNode] = {}
        self.positions: Dict[str, QPointF] = {}

        self._init_ui()
        self._connect_events()

    def _init_ui(self) -> None:
        """Sets up the user interface components of the widget."""
        self.setWindowTitle("Project Visualizer")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QBrush(QColor("#2c313c")))

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        layout.addWidget(self.view)

    def _connect_events(self) -> None:
        """Connects widget slots to events from the event bus."""
        self.event_bus.subscribe("architect_plan_updated", self.prepare_visualization)
        self.event_bus.subscribe("file_generation_starting", self.draw_node)
        self.event_bus.subscribe("generation_session_started", self.clear_visualization)

    @pyqtSlot()
    def clear_visualization(self) -> None:
        """
        Clears the entire visualization, removing all nodes and resetting state.
        """
        logger.info("Clearing project visualization.")
        self.scene.clear()
        self.nodes.clear()
        self.positions.clear()

    @pyqtSlot(dict)
    def prepare_visualization(self, plan: Dict) -> None:
        """
        Pre-calculates node positions based on the architect's plan.

        This method is triggered when a new plan is available. It extracts all
        unique filenames from the plan tasks and calculates a layout for them
        without drawing them yet.

        Args:
            plan: The architect's plan dictionary.
        """
        self.clear_visualization()
        logger.info("Preparing visualization from new architect plan.")

        tasks = plan.get("tasks", [])
        if not tasks:
            logger.warning("Plan received with no tasks. Nothing to visualize.")
            return

        filenames: Set[str] = {
            task["filename"] for task in tasks if "filename" in task
        }
        if not filenames:
            logger.warning("No filenames found in plan tasks. Nothing to visualize.")
            return

        self.positions = self._calculate_node_positions(list(filenames))
        logger.info(f"Pre-calculated positions for {len(self.positions)} nodes.")
        # Center the view on the calculated layout
        self.view.fitInView(
            self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio
        )

    def _calculate_node_positions(
        self, filenames: List[str]
    ) -> Dict[str, QPointF]:
        """
        Calculates positions for a list of nodes in a circular layout.

        Args:
            filenames: A list of unique filenames to be placed.

        Returns:
            A dictionary mapping each filename to its calculated QPointF position.
        """
        positions: Dict[str, QPointF] = {}
        count = len(filenames)
        if count == 0:
            return {}
        if count == 1:
            return {filenames[0]: QPointF(0, 0)}

        # Dynamic radius to give more space for more nodes
        radius = max(200.0, count * 30.0)

        for i, filename in enumerate(filenames):
            angle = (2 * math.pi * i) / count
            x = radius * math.cos(angle)
            y = radius * math.sin(angle)
            positions[filename] = QPointF(x, y)

        return positions

    @pyqtSlot(dict)
    def draw_node(self, event_data: Dict) -> None:
        """
        Draws a single pre-calculated node on the scene.

        This slot is triggered by the 'file_generation_starting' event. It finds
        the pre-calculated position for the given filename and adds the
        corresponding node to the scene.

        Args:
            event_data: The event payload, expected to contain a 'filename' key.
        """
        filename = event_data.get("filename")
        if not filename:
            logger.warning(
                "Received 'file_generation_starting' event with no filename."
            )
            return

        if filename in self.nodes:
            logger.debug(f"Node for {filename} already drawn. Skipping.")
            return

        if filename in self.positions:
            logger.info(f"Drawing node for: {filename}")
            position = self.positions[filename]
            node = ProjectNode(filename)
            node.setPos(position)
            self.scene.addItem(node)
            self.nodes[filename] = node

            # Recenter view if it's the first node
            if len(self.nodes) == 1:
                self.view.centerOn(node)
        else:
            logger.warning(
                f"No pre-calculated position found for {filename}. Cannot draw node."
            )