# src/ava/gui/node_viewer/project_node.py
"""
Defines the graphical node item used in the Project Visualizer.
"""
import logging
from typing import List, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import (
    QGraphicsObject, QGraphicsItem, QStyleOptionGraphicsItem, QWidget, QGraphicsSceneHoverEvent
)
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QBrush, QPen
import qtawesome as qta

from src.ava.gui.components import Colors, Typography

if TYPE_CHECKING:
    from .project_visualizer_window import ConnectionItem

logger = logging.getLogger(__name__)


class ProjectNode(QGraphicsObject):
    """
    Represents a single node (file, folder, or root) in the project visualizer graph.
    This is a QGraphicsObject that can be moved, selected, and connected with lines.
    """

    def __init__(self, name: str, path: Optional[str] = None, node_type: str = "file",
                 parent: Optional[QGraphicsItem] = None):
        """
        Initializes the ProjectNode.

        Args:
            name: The display name of the node (e.g., filename or folder name).
            path: The full relative path of the node within the project.
            node_type: The type of the node ('file', 'folder', 'root').
            parent: The parent QGraphicsItem in the scene.
        """
        super().__init__(parent)
        self.name = name
        self.path = path
        self.node_type = node_type
        self.incoming_connections: List['ConnectionItem'] = []
        self.outgoing_connections: List['ConnectionItem'] = []
        self._is_hovered = False

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles mouse hover enter event to provide visual feedback.

        Args:
            event: The hover event.
        """
        self._is_hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event: QGraphicsSceneHoverEvent) -> None:
        """
        Handles mouse hover leave event to remove visual feedback.

        Args:
            event: The hover event.
        """
        self._is_hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounds of the node item.

        Returns:
            The bounding rectangle of the node.
        """
        return QRectF(0, 0, 150, 50)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        """
        Paints the node with a specific style based on its type and state.

        Args:
            painter: The QPainter to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        rect = self.boundingRect()

        # Determine background color
        if self.node_type == "folder":
            brush_color = Colors.ACCENT_BLUE
        elif self.node_type == "root":
            brush_color = Colors.ACCENT_PURPLE
        else:  # file
            brush_color = Colors.ELEVATED_BG

        # Determine border color based on state
        if self.isSelected():
            pen_color = Colors.ACCENT_BLUE.lighter(130)
            pen_width = 3
        elif self._is_hovered:
            pen_color = Colors.ACCENT_BLUE
            pen_width = 2
        else:
            pen_color = Colors.BORDER_DEFAULT
            pen_width = 2

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(brush_color))
        painter.setPen(QPen(pen_color, pen_width))
        painter.drawRoundedRect(rect, 10.0, 10.0)

        # --- Icon Drawing ---
        icon_size = 24
        icon_margin = 10
        icon_rect = QRectF(icon_margin, (rect.height() - icon_size) / 2, icon_size, icon_size)

        icon = None
        icon_color = Colors.TEXT_PRIMARY
        if self.node_type == "folder":
            icon = qta.icon("fa5s.folder", color=icon_color)
        elif self.node_type == "root":
            icon = qta.icon("fa5s.brain", color=icon_color)
        else:  # file
            icon = qta.icon("fa5s.file-code", color=icon_color)

        if icon:
            icon.paint(painter, icon_rect.toRect())

        # --- Text Drawing ---
        text_margin = 5
        text_rect = rect.adjusted(icon_rect.right() + text_margin, 0, -text_margin, 0)
        painter.setPen(QPen(Colors.TEXT_PRIMARY))
        painter.setFont(Typography.body())

        font_metrics = painter.fontMetrics()
        elided_name = font_metrics.elidedText(self.name, Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_name)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """
        Handles changes to the item's state, such as its position or selection.
        When the node moves, it updates its connections.

        Args:
            change: The parameter of the item that is changing.
            value: The new value.

        Returns:
            The result of the base class's itemChange method.
        """
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for connection in self.incoming_connections:
                connection.update_path()
            for connection in self.outgoing_connections:
                connection.update_path()
        # Update appearance on selection change
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def add_incoming_connection(self, connection: 'ConnectionItem') -> None:
        """
        Adds an incoming connection line to this node.

        Args:
            connection: The ConnectionItem to add.
        """
        self.incoming_connections.append(connection)

    def add_outgoing_connection(self, connection: 'ConnectionItem') -> None:
        """
        Adds an outgoing connection line from this node.

        Args:
            connection: The ConnectionItem to add.
        """
        self.outgoing_connections.append(connection)