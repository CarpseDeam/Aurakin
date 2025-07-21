# src/ava/gui/project_node.py

import logging
from typing import Any, Optional

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
NODE_WIDTH = 120
NODE_HEIGHT = 40
NODE_RADIUS = 8
ICON_SIZE = 20


class ProjectNode(QGraphicsObject):
    """
    A visual representation of a file or folder in the project graph.

    This QGraphicsObject is responsible for its own appearance, including its
    icon, name, and state-based styling (e.g., hover, selection). It also
    maintains physics properties like velocity for use in a force-directed
    layout.
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
            name: The display name of the file or folder.
            path: The unique, full path to the item, used as an ID.
            is_folder: True if the node represents a folder, False for a file.
            parent: The parent QGraphicsItem, if any.
        """
        super().__init__(parent)

        self.name = name
        self.path = path
        self.is_folder = is_folder

        # Physics properties for force-directed layout
        self.velocity = QPointF(0, 0)

        # UI state
        self._is_hovered = False

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setToolTip(self.path)

        # Set icon based on type
        icon_name = "fa5s.folder" if self.is_folder else "fa5s.file-alt"
        self.icon = qta.icon(icon_name, color=Colors.TEXT_SECONDARY)

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounds of the item for painting and interaction.

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
        current state (selected, hovered).

        Args:
            painter: The QPainter to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Determine colors based on state
        if self.isSelected():
            bg_color = QColor(Colors.ACCENT_BLUE)
            border_color = QColor(Colors.ACCENT_BLUE.lighter(130))
            text_color = QColor(Colors.TEXT_PRIMARY)
        elif self._is_hovered:
            bg_color = QColor(Colors.ELEVATED_BG.lighter(120))
            border_color = QColor(Colors.BORDER_DEFAULT.lighter(150))
            text_color = QColor(Colors.TEXT_PRIMARY)
        else:
            bg_color = QColor(Colors.ELEVATED_BG)
            border_color = QColor(Colors.BORDER_DEFAULT)
            text_color = QColor(Colors.TEXT_SECONDARY)

        # Draw background and border
        path = QPainterPath()
        path.addRoundedRect(self.boundingRect(), NODE_RADIUS, NODE_RADIUS)
        painter.setPen(QPen(border_color, 1.5))
        painter.fillPath(path, QBrush(bg_color))
        painter.drawPath(path)

        # Draw Icon
        icon_rect = QRectF(8, (NODE_HEIGHT - ICON_SIZE) / 2, ICON_SIZE, ICON_SIZE)
        self.icon.paint(painter, icon_rect.toRect())

        # Draw Text
        text_x = icon_rect.right() + 8
        text_width = NODE_WIDTH - text_x - 8
        text_rect = QRectF(text_x, 0, text_width, NODE_HEIGHT)

        painter.setPen(QPen(text_color))
        painter.setFont(Typography.body())

        # Elide text if it's too long to fit
        metrics = QFontMetrics(painter.font())
        elided_name = metrics.elidedText(
            self.name, Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided_name
        )

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles the mouse entering the node's bounding area.

        Args:
            event: The hover event.
        """
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles the mouse leaving the node's bounding area.

        Args:
            event: The hover event.
        """
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        """
        Handles the mouse release event over the node.

        Resets the node's velocity to prevent it from "slingshotting" away
        after being dragged by the user, allowing the physics simulation to
        take over smoothly.

        Args:
            event: The mouse event.
        """
        self.velocity = QPointF(0, 0)
        super().mouseReleaseEvent(event)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """
        Handles changes to the item's state, such as its position.

        When the user stops dragging the node, this resets its velocity.

        Args:
            change: The type of change occurring.
            value: The new value for the changed attribute.

        Returns:
            The processed value.
        """
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # This is called continuously during a drag. The visualizer's
            # physics loop will handle updating connections.
            pass
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            # When selection changes, force a repaint to update colors
            self.update()

        return super().itemChange(change, value)