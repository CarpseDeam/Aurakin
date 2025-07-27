# src/ava/gui/node_viewer/agent_node.py
import qtawesome as qta
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsObject, QStyleOptionGraphicsItem, QWidget
from typing import Optional, Any, List

from src.ava.gui.components import Typography
from .animated_connection import AnimatedConnection

AGENT_NODE_WIDTH, AGENT_NODE_HEIGHT, AGENT_NODE_RADIUS, AGENT_ICON_SIZE = 150, 45, 22, 24


class AgentNode(QGraphicsObject):
    """A graphical node representing an AI agent on the canvas."""

    def __init__(self, agent_name: str, parent: Optional[QGraphicsObject] = None):
        super().__init__(parent)
        self.agent_name = agent_name
        self.outgoing_connections: List['AnimatedConnection'] = []

        self.setFlags(QGraphicsObject.GraphicsItemFlag.ItemIsMovable)
        self.setCacheMode(QGraphicsObject.CacheMode.DeviceCoordinateCache)
        self.setToolTip(f"Agent: {self.agent_name}")

        icon_map = {
            "Architect": "fa5s.drafting-compass",
            "Coder": "fa5s.code",
            "Rewriter": "fa5s.edit",
            "Healer": "fa5s.heartbeat",
            "Tester": "fa5s.vial",
        }
        self.icon_key = icon_map.get(agent_name, "fa5s.robot")

    def add_connection(self, connection: 'AnimatedConnection') -> None:
        """Adds an outgoing connection to this agent node for tracking."""
        self.outgoing_connections.append(connection)

    def itemChange(self, change: QGraphicsObject.GraphicsItemChange, value: Any) -> Any:
        """Updates connections when the agent node is moved."""
        if change == QGraphicsObject.GraphicsItemChange.ItemPositionHasChanged:
            for conn in self.outgoing_connections:
                conn.update_path()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, AGENT_NODE_WIDTH, AGENT_NODE_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        node_rect = self.boundingRect()

        # A circular or pill-shaped node for agents
        bg_color = QColor("#21262d").lighter(110)
        border_color = QColor("#30363d")

        path = QPainterPath()
        path.addRoundedRect(node_rect, AGENT_NODE_RADIUS, AGENT_NODE_RADIUS)
        painter.setPen(QPen(border_color, 1.5))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        # Draw Icon
        icon_to_paint = qta.icon(self.icon_key, color="#8b949e")
        icon_x = 12
        icon_rect = QRectF(icon_x, (AGENT_NODE_HEIGHT - AGENT_ICON_SIZE) / 2, AGENT_ICON_SIZE, AGENT_ICON_SIZE)
        icon_to_paint.paint(painter, icon_rect.toRect())

        # Draw Text
        text_x = icon_rect.right() + 8
        text_width = AGENT_NODE_WIDTH - text_x - 8
        text_rect = QRectF(text_x, 0, text_width, AGENT_NODE_HEIGHT)
        painter.setPen(QPen("#f0f6fc"))
        painter.setFont(Typography.heading_small())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.agent_name)