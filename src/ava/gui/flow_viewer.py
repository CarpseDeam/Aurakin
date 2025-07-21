import logging
from typing import Dict, List, Optional

from PySide6.QtCore import (
    Qt,
    QPointF,
    QPropertyAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
)
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QResizeEvent
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPathItem,
    QWidget,
)

from src.ava.core.event_bus import EventBus
from src.ava.gui.components import Colors
from src.ava.gui.flow_node import FlowNode

logger = logging.getLogger(__name__)

# Constants for layout
NODE_WIDTH = 150
NODE_HEIGHT = 60
HORIZONTAL_SPACING = 80
VERTICAL_PADDING = 20


class FlowViewer(QGraphicsView):
    """
    A QGraphicsView/Scene that visualizes the AI agent workflow.

    This widget listens to EventBus events to dynamically create, update,
    and animate a graph of FlowNode items, showing the progression of
    an AI task from one agent to the next.
    """

    def __init__(self, event_bus: EventBus, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the FlowViewer.

        Args:
            event_bus: The application's central event bus.
            parent: The parent widget.
        """
        super().__init__(parent)
        self.event_bus = event_bus
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.nodes: Dict[str, FlowNode] = {}
        self.connections: List[QGraphicsPathItem] = []
        self.node_order: List[str] = []

        self._setup_view()
        self._connect_events()

    def _setup_view(self) -> None:
        """
        Configures the appearance and behavior of the QGraphicsView.
        """
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(Colors.PRIMARY_BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

    def _connect_events(self) -> None:
        """
        Subscribes to relevant events on the EventBus.
        """
        # Note: _on_agent_status_changed is connected by EventCoordinator
        self.event_bus.subscribe("ai_workflow_finished", self._on_workflow_finished)
        self.event_bus.subscribe("new_session_requested", self._clear_flow)
        self.event_bus.subscribe("chat_cleared", self._clear_flow)

    def _clear_flow(self, *args, **kwargs) -> None:
        """
        Resets the view to a clean state, removing all nodes and connections.
        """
        self.nodes.clear()
        self.connections.clear()
        self.node_order.clear()
        self.scene.clear()
        logger.info("FlowViewer cleared for new session.")

    def _on_agent_status_changed(self, agent_name: str, status_text: str, icon_name: str) -> None:
        """
        Handles an agent status update from the EventBus.

        This method creates a new node if the agent is seen for the first time
        in the current workflow, updates the states of all nodes, and triggers
        a relayout.

        Args:
            agent_name: The name of the agent reporting the status.
            status_text: The new status message.
            icon_name: The icon associated with the agent/status.
        """
        if agent_name not in self.nodes:
            # This is a new step in the workflow
            node = FlowNode(agent_name, status_text, icon_name)
            self.nodes[agent_name] = node
            self.node_order.append(agent_name)
            self.scene.addItem(node)
            self._relayout_and_connect_nodes()
        else:
            # Update existing node (might be a sub-status)
            self.nodes[agent_name].update_content(status_text, icon_name)

        # Update states for all nodes: set current to active, previous to completed
        for i, name in enumerate(self.node_order):
            node = self.nodes[name]
            is_current_agent = (name == agent_name)
            is_past_agent = (i < self.node_order.index(agent_name))

            node.set_active_state(is_current_agent)
            if is_past_agent:
                node.set_completed_state(True)

    def _on_workflow_finished(self) -> None:
        """
        Handles the completion of an AI workflow.

        Marks all nodes in the sequence as successful.
        """
        for node in self.nodes.values():
            node.set_active_state(False)
            node.set_completed_state(True, success=True)
        logger.info("Workflow finished. Marked all nodes as success.")

    def _relayout_and_connect_nodes(self) -> None:
        """
        Calculates new positions for all nodes and sets them directly.
        It also redraws the connections between nodes.
        """
        # Clear old connections
        for conn in self.connections:
            self.scene.removeItem(conn)
        self.connections.clear()

        total_width = (len(self.nodes) * NODE_WIDTH) + (max(0, len(self.nodes) - 1) * HORIZONTAL_SPACING)
        start_x = -total_width / 2.0

        for i, agent_name in enumerate(self.node_order):
            node = self.nodes[agent_name]
            new_x = start_x + i * (NODE_WIDTH + HORIZONTAL_SPACING)
            new_y = -(NODE_HEIGHT / 2)  # Center vertically

            # Set position directly instead of animating
            node.setPos(new_x, new_y)

            # Add connection to previous node
            if i > 0:
                prev_node = self.nodes[self.node_order[i - 1]]
                connection = self._create_connection(prev_node, node)
                self.scene.addItem(connection)
                self.connections.append(connection)

        self._center_view()

    def _create_connection(self, start_node: FlowNode, end_node: FlowNode) -> QGraphicsPathItem:
        """
        Creates a QGraphicsPathItem representing an arrow between two nodes.

        Args:
            start_node: The node where the connection originates.
            end_node: The node where the connection terminates.

        Returns:
            A QGraphicsPathItem styled as a connecting arrow.
        """
        start_point = start_node.pos() + QPointF(NODE_WIDTH, NODE_HEIGHT / 2)
        end_point = end_node.pos() + QPointF(0, NODE_HEIGHT / 2)

        path = QPainterPath()
        path.moveTo(start_point)

        # Create a gentle curve for the connection
        control_x1 = start_point.x() + HORIZONTAL_SPACING / 2
        control_y1 = start_point.y()
        control_x2 = end_point.x() - HORIZONTAL_SPACING / 2
        control_y2 = end_point.y()
        path.cubicTo(control_x1, control_y1, control_x2, control_y2, end_point.x(), end_point.y())

        pen = QPen(QColor(Colors.BORDER_DEFAULT), 2, Qt.PenStyle.SolidLine)
        connection_item = QGraphicsPathItem(path)
        connection_item.setPen(pen)
        connection_item.setZValue(-1)  # Draw behind nodes
        return connection_item

    def _center_view(self) -> None:
        """
        Adjusts the view to ensure all nodes are visible and centered.
        """
        if self.scene.items():
            items_rect = self.scene.itemsBoundingRect()
            padded_rect = items_rect.adjusted(-50, -VERTICAL_PADDING, 50, VERTICAL_PADDING)
            self.fitInView(padded_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """
        Overrides the resize event to re-center the view.

        Args:
            event: The QResizeEvent.
        """
        super().resizeEvent(event)
        self._center_view()
