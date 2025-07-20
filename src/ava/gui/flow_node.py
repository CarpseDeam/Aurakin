# src/ava/gui/flow_node.py
import logging
from typing import Optional

import qtawesome as qta
from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.ava.gui.components import Colors, Typography

logger = logging.getLogger(__name__)

# Constants for layout, matching flow_viewer.py
NODE_WIDTH = 150
NODE_HEIGHT = 60
ICON_SIZE = 24


class FlowNode(QGraphicsObject):
    """
    A custom QGraphicsObject representing a single agent or step in the AI workflow.

    This item is responsible for its own appearance, including its state
    (inactive, active, completed, success) and the information it displays
    (agent name, status, icon). It supports animations for opacity.
    """

    def __init__(
        self,
        agent_name: str,
        status_text: str,
        icon_name: str,
        parent: Optional[QGraphicsItem] = None,
    ) -> None:
        """
        Initializes the FlowNode.

        Args:
            agent_name: The name of the agent (e.g., "Architect").
            status_text: The initial status message to display.
            icon_name: The name of the qtawesome icon to use.
            parent: The parent QGraphicsItem, if any.
        """
        super().__init__(parent)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

        # Content properties
        self._agent_name: str = agent_name
        self._status_text: str = status_text
        self._icon_name: str = icon_name
        self._icon = qta.icon(self._icon_name, color=Colors.TEXT_PRIMARY)

        # State properties
        self._is_active: bool = False
        self._is_completed: bool = False
        self._is_success: bool = False
        self._opacity: float = 0.0

        # Animation for fade-in
        self._fade_in_animation = QPropertyAnimation(self, b"opacity")
        self._fade_in_animation.setDuration(300)
        self._fade_in_animation.setStartValue(0.0)
        self._fade_in_animation.setEndValue(1.0)
        self._fade_in_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade_in_animation.start()

    @Property(float)
    def opacity(self) -> float:
        """
        Gets the current opacity of the node.

        Returns:
            The opacity value (0.0 to 1.0).
        """
        return self._opacity

    @opacity.setter
    def opacity(self, value: float) -> None:
        """
        Sets the opacity of the node and triggers a repaint.

        Args:
            value: The new opacity value (0.0 to 1.0).
        """
        self._opacity = value
        self.update()

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounds of the item.

        Returns:
            A QRectF representing the node's bounding box.
        """
        return QRectF(0, 0, NODE_WIDTH, NODE_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: Optional[QWidget] = None,
    ) -> None:
        """
        Paints the contents of the node.

        This method is called by the QGraphicsScene to draw the item. It handles
        drawing the background, border, icon, and text based on the node's
        current state.

        Args:
            painter: The QPainter to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        painter.setOpacity(self._opacity)

        # Determine colors based on state
        if self._is_active:
            bg_color = Colors.ACCENT_BLUE
            border_color = Colors.ACCENT_BLUE.lighter(120)
            text_color = Colors.TEXT_PRIMARY
        elif self._is_success:
            bg_color = Colors.ACCENT_GREEN
            border_color = Colors.ACCENT_GREEN.lighter(120)
            text_color = Colors.TEXT_PRIMARY
        elif self._is_completed:
            bg_color = Colors.ELEVATED_BG
            border_color = Colors.BORDER_DEFAULT
            text_color = Colors.TEXT_SECONDARY
        else:
            bg_color = Colors.SECONDARY_BG
            border_color = Colors.BORDER_DEFAULT
            text_color = Colors.TEXT_SECONDARY

        # Draw background and border
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), 8, 8)
        painter.setPen(QPen(border_color, 2))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        # Draw Icon
        icon_rect = QRectF(10, (NODE_HEIGHT - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        self._icon.paint(painter, icon_rect.toRect())

        # Draw Text
        text_x = icon_rect.right() + 10
        text_width = NODE_WIDTH - text_x - 10

        # Agent Name (Title)
        painter.setPen(QPen(text_color))
        painter.setFont(Typography.heading_small())
        title_rect = QRectF(text_x, 8, text_width, 20)
        painter.drawText(
            title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._agent_name
        )

        # Status Text (Subtitle)
        painter.setFont(Typography.body())
        status_rect = QRectF(text_x, title_rect.bottom(), text_width, 25)
        painter.drawText(
            status_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self._status_text,
        )

    def update_content(self, status_text: str, icon_name: str) -> None:
        """
        Updates the status text and icon of the node.

        Args:
            status_text: The new status message.
            icon_name: The new qtawesome icon name.
        """
        self._status_text = status_text
        if self._icon_name != icon_name:
            self._icon_name = icon_name
            self._icon = qta.icon(self._icon_name, color=Colors.TEXT_PRIMARY)
        self.update()

    def set_active_state(self, active: bool) -> None:
        """
        Sets the node's active state.

        Args:
            active: True to set the node as active, False otherwise.
        """
        if self._is_active != active:
            self._is_active = active
            self.update()

    def set_completed_state(self, completed: bool, success: bool = False) -> None:
        """
        Sets the node's completed state.

        Args:
            completed: True to mark the node as completed.
            success: If completed, True to mark it as a successful completion.
        """
        if self._is_completed != completed or self._is_success != success:
            self._is_completed = completed
            self._is_success = success if completed else False
            self.update()