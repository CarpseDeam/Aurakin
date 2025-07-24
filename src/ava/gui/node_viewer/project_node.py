# src/ava/gui/node_viewer/project_node.py
import logging
from typing import Any, List, Optional
import qtawesome as qta
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget, QGraphicsSceneHoverEvent

from src.ava.gui.components import Colors, Typography

logger = logging.getLogger(__name__)
NODE_WIDTH, NODE_HEIGHT, NODE_RADIUS, ICON_SIZE = 150, 45, 8, 20

class ProjectNode(QGraphicsObject):
    """
    A graphical node representing a file, folder, class, or function.
    It handles its own drawing, state changes, and notifies connections when it moves.
    """
    def __init__(self, name: str, path: str, node_type: str, full_code: str = "", parent: Optional[QGraphicsItem] = None) -> None:
        super().__init__(parent)
        self.name = name
        self.path = path
        self.node_type = node_type  # 'folder', 'file', 'class', 'function'
        self.full_code = full_code
        self._is_hovered = False
        self.incoming_connections: List[Any] = []
        self.outgoing_connections: List[Any] = []

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setToolTip(f"Type: {node_type.title()}\nPath: {self.path}")

        # Define icons for each node type
        icon_map = {
            'folder': "fa5s.folder",
            'file': "fa5b.python",
            'class': "fa5s.cubes",
            'function': "fa5s.cogs"
        }
        icon_name = icon_map.get(self.node_type, "fa5s.question-circle")
        self.icon = qta.icon(icon_name, color=Colors.TEXT_SECONDARY)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """
        Overrides the base method to update connection lines when the node is moved.
        This is the core of the "dynamic connections" feature.
        """
        if change == QGraphicsItem.ItemPositionHasChanged:
            for conn in self.incoming_connections:
                conn.update_path()
            for conn in self.outgoing_connections:
                conn.update_path()
        return super().itemChange(change, value)

    def add_connection(self, connection: Any, is_outgoing: bool) -> None:
        """Registers a connection line with this node."""
        if is_outgoing:
            self.outgoing_connections.append(connection)
        else:
            self.incoming_connections.append(connection)

    def boundingRect(self) -> QRectF:
        """Defines the node's total area for painting and interaction."""
        return QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        """Draws the node, including its background, icon, and text."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        node_rect = self.boundingRect()

        # Determine colors based on the node's current state
        bg_color = QColor(Colors.ELEVATED_BG)
        border_color = QColor(Colors.BORDER_DEFAULT)
        text_color = QColor(Colors.TEXT_SECONDARY)

        if self.isSelected():
            bg_color = QColor(Colors.ACCENT_BLUE)
            border_color = QColor(Colors.ACCENT_BLUE.lighter(130))
            text_color = QColor(Colors.TEXT_PRIMARY)
        elif self._is_hovered:
            bg_color = bg_color.lighter(120)

        # Draw the node body
        path = QPainterPath()
        path.addRoundedRect(node_rect, NODE_RADIUS, NODE_RADIUS)
        painter.setPen(QPen(border_color, 1.5))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        # Draw the icon
        icon_rect = QRectF(8, (NODE_HEIGHT - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        self.icon.paint(painter, icon_rect.toRect())

        # Draw the text
        text_x = icon_rect.right() + 8
        text_width = NODE_WIDTH - text_x - 8
        text_rect = QRectF(text_x, 0, text_width, NODE_HEIGHT)
        painter.setPen(QPen(text_color))
        painter.setFont(Typography.body())
        elided_name = QFontMetrics(painter.font()).elidedText(self.name, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """Changes the hover state and triggers a repaint."""
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """Resets the hover state and triggers a repaint."""
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)