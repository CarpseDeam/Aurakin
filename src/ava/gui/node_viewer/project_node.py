# src/ava/gui/node_viewer/project_node.py
import logging
from typing import Any, List, Optional
import qtawesome as qta
from PySide6.QtCore import QRectF, Qt, Signal, QPointF
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPainterPath, QPen, QMouseEvent, QPalette
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget, QStyle, \
    QGraphicsSceneHoverEvent

from src.ava.gui.components import Typography
from .animated_connection import AnimatedConnection

logger = logging.getLogger(__name__)
NODE_WIDTH, NODE_HEIGHT, NODE_RADIUS, ICON_SIZE = 150, 45, 8, 20
TOGGLE_BOX_SIZE = 12


class ProjectNode(QGraphicsObject):
    """
    A graphical node representing a file, folder, class, or function.
    It handles its own drawing, state changes, and notifies connections when it moves.
    """
    toggle_requested = Signal()

    def __init__(self, name: str, path: str, node_type: str, full_code: str = "",
                 parent: Optional[QGraphicsItem] = None) -> None:
        super().__init__(parent)
        self.name = name
        self.path = path
        self.node_type = node_type  # 'folder', 'file', 'class', 'function'
        self.full_code = full_code
        self._is_hovered = False

        self.is_expanded = True
        self.child_nodes: List['ProjectNode'] = []
        self.parent_node: Optional['ProjectNode'] = None

        self.incoming_connections: List['AnimatedConnection'] = []
        self.outgoing_connections: List['AnimatedConnection'] = []

        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setToolTip(f"Type: {node_type.title()}\nPath: {self.path}")

        icon_map = {
            'folder': "fa5s.folder",
            'file': "fa5s.file-code",
            'class': "fa5s.cubes",
            'function': "fa5s.cogs"
        }
        self.icon_key = icon_map.get(self.node_type, "fa5s.question-circle")
        self.icon = qta.icon(self.icon_key, color=QColor("#8b949e"))

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.ItemPositionHasChanged:
            for conn in self.incoming_connections:
                conn.update_path()
            for conn in self.outgoing_connections:
                conn.update_path()
        return super().itemChange(change, value)

    def add_connection(self, connection: 'AnimatedConnection', is_outgoing: bool) -> None:
        if is_outgoing:
            self.outgoing_connections.append(connection)
        else:
            self.incoming_connections.append(connection)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

    def _get_toggle_rect(self) -> QRectF:
        """Defines the clickable area for the [+] / [-] icon."""
        return QRectF(5, (NODE_HEIGHT - TOGGLE_BOX_SIZE) / 2, TOGGLE_BOX_SIZE, TOGGLE_BOX_SIZE)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        node_rect = self.boundingRect()

        bg_color = QColor("#21262d")
        border_color = QColor("#30363d")
        text_color = QColor("#8b949e")

        if self.isSelected():
            bg_color = QColor("#ffa500")
            border_color = QColor("#ffa500").lighter(130)
            text_color = QColor("#0d1117") # Dark text for better contrast on orange
        elif self._is_hovered:
            bg_color = bg_color.lighter(120)

        path = QPainterPath()
        path.addRoundedRect(node_rect, NODE_RADIUS, NODE_RADIUS)
        painter.setPen(QPen(border_color, 1.5))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        if self.child_nodes:
            toggle_rect = self._get_toggle_rect()
            painter.setPen(QPen(text_color, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(toggle_rect)

            center = toggle_rect.center()
            if self.is_expanded:
                painter.drawLine(int(center.x() - 3), int(center.y()), int(center.x() + 3), int(center.y()))  # Minus
            else:
                painter.drawLine(int(center.x() - 3), int(center.y()), int(center.x() + 3),
                                 int(center.y()))  # Horizontal
                painter.drawLine(int(center.x()), int(center.y() - 3), int(center.x()), int(center.y() + 3))  # Vertical

        icon_color = text_color if self.isSelected() else QColor("#8b949e")
        icon_to_paint = qta.icon(self.icon_key, color=icon_color)

        icon_x = 22
        icon_rect = QRectF(icon_x, (NODE_HEIGHT - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        icon_to_paint.paint(painter, icon_rect.toRect())

        text_x = icon_rect.right() + 8
        text_width = NODE_WIDTH - text_x - 8
        text_rect = QRectF(text_x, 0, text_width, NODE_HEIGHT)
        painter.setPen(QPen(text_color))
        painter.setFont(Typography.body())
        elided_name = QFontMetrics(painter.font()).elidedText(self.name, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle clicks to either toggle expansion or select/move the node."""
        if self.child_nodes and self._get_toggle_rect().contains(event.pos()):
            self.toggle_requested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)