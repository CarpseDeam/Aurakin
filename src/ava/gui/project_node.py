# src/ava/gui/project_node.py

import logging
from typing import Any, List, Optional

import qtawesome as qta
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsSceneHoverEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.ava.gui.components import Colors, Typography

logger = logging.getLogger(__name__)

# --- Node Constants ---
NODE_WIDTH = 150
NODE_HEIGHT = 45
NODE_RADIUS = 8
ICON_SIZE = 20


class ProjectNode(QGraphicsObject):
    """
    A visual representation of a file or folder in the project graph.

    This QGraphicsObject represents a node in the project visualizer, displaying
    its name and an icon. It can be moved, selected, and shows different visual
    states for hover, selection, and AI activity (glow). It also tracks its
    connections to other nodes and updates them when its position changes.
    """

    def __init__(
            self,
            name: str,
            path: str,
            is_folder: bool,
            parent: Optional[QGraphicsItem] = None,
    ) -> None:
        """
        Initializes the ProjectNode.

        Args:
            name: The display name of the node (file or folder name).
            path: The full path to the file or folder.
            is_folder: True if the node represents a folder, False otherwise.
            parent: The parent QGraphicsItem, if any.
        """
        super().__init__(parent)

        self.name = name
        self.path = path
        self.is_folder = is_folder

        # UI state
        self._is_hovered = False
        self._is_active = False  # For the glow effect
        self.incoming_connections: List[Any] = []
        self.outgoing_connections: List[Any] = []

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setToolTip(self.path)

        icon_name = "fa5s.folder" if self.is_folder else "fa5s.file-alt"
        self.icon = qta.icon(icon_name, color=Colors.TEXT_SECONDARY)
        logger.debug(f"ProjectNode created for path: {self.path}")

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """
        Overrides the base itemChange method to update connections when moved.

        This is a key method for ensuring that the visual connections (arrows)
        between nodes stay attached when a node is dragged by the user.

        Args:
            change: The type of change occurring.
            value: The new value associated with the change.

        Returns:
            The result of the base class's itemChange method.
        """
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            logger.debug(f"Node '{self.name}' moved, updating connections.")
            for conn in self.incoming_connections:
                conn.update_path()
            for conn in self.outgoing_connections:
                conn.update_path()
        return super().itemChange(change, value)

    def add_connection(self, connection: Any, is_outgoing: bool) -> None:
        """
        Registers a connection (e.g., a ConnectionItem) with this node.

        Args:
            connection: The connection item to register.
            is_outgoing: True if the connection originates from this node,
                         False if it terminates at this node.
        """
        if is_outgoing:
            self.outgoing_connections.append(connection)
        else:
            self.incoming_connections.append(connection)

    def set_active(self, is_active: bool) -> None:
        """
        Toggles the active state, which controls the glow effect.

        This is typically used to indicate that an AI agent is currently
        working on or interacting with this node.

        Args:
            is_active: True to activate the glow effect, False to deactivate it.
        """
        if self._is_active != is_active:
            self._is_active = is_active
            self.update()
            logger.debug(f"Node '{self.name}' active state set to {is_active}")

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounding rectangle of the node.

        Returns:
            A QRectF representing the node's boundaries, including any effects
            like glows to prevent visual clipping.
        """
        # Add a small margin for the glow effect to prevent clipping
        glow_margin = 6
        return QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT).adjusted(-glow_margin, -glow_margin, glow_margin, glow_margin)

    def shape(self) -> QPainterPath:
        """
        Defines the precise shape of the node for collision detection.

        Returns:
            A QPainterPath representing the rounded rectangle shape.
        """
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT), NODE_RADIUS, NODE_RADIUS)
        return path

    def paint(
            self,
            painter: QPainter,
            option: QStyleOptionGraphicsItem,
            widget: Optional[QWidget] = None,
    ) -> None:
        """
        Paints the contents of the node.

        This method handles drawing the node's background, border, glow,
        icon, and text, with different styles for selected, hovered, and
        active states.

        Args:
            painter: The QPainter instance to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # The actual drawing rectangle for the node body
        node_rect = QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

        # Draw glow if active
        if self._is_active:
            glow_color = QColor(Colors.ACCENT_BLUE)
            glow_color.setAlpha(100)
            painter.setPen(QPen(glow_color, 6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(node_rect.adjusted(-2, -2, 2, 2), NODE_RADIUS, NODE_RADIUS)

        # Determine colors based on state
        if self.isSelected():
            bg_color = QColor(Colors.ACCENT_BLUE)
            border_color = QColor(Colors.ACCENT_BLUE.lighter(130))
            text_color = QColor(Colors.TEXT_PRIMARY)
        else:
            bg_color = QColor(Colors.ELEVATED_BG)
            border_color = QColor(Colors.BORDER_DEFAULT)
            text_color = QColor(Colors.TEXT_SECONDARY)

        if self._is_hovered:
            bg_color = bg_color.lighter(120)

        path = QPainterPath()
        path.addRoundedRect(node_rect, NODE_RADIUS, NODE_RADIUS)
        painter.setPen(QPen(border_color, 1.5))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        icon_rect = QRectF(8, (NODE_HEIGHT - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        self.icon.paint(painter, icon_rect.toRect())

        text_x = icon_rect.right() + 8
        text_width = NODE_WIDTH - text_x - 8
        text_rect = QRectF(text_x, 0, text_width, NODE_HEIGHT)
        painter.setPen(QPen(text_color))
        painter.setFont(Typography.body())
        metrics = QFontMetrics(painter.font())
        elided_name = metrics.elidedText(self.name, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles the mouse entering the node's area.

        Args:
            event: The hover event.
        """
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles the mouse leaving the node's area.

        Args:
            event: The hover event.
        """
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)