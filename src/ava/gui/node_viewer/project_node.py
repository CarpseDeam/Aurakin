# src/ava/gui/node_viewer/project_node.py
"""
Defines the graphical node item used in the Project Visualizer.
"""
import logging
from typing import List, Any, Optional, TYPE_CHECKING

from PySide6.QtWidgets import QGraphicsObject, QGraphicsItem, QStyleOptionGraphicsItem, QWidget
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QBrush, QPen

from src.ava.gui.components import Colors, Typography

if TYPE_CHECKING:
    from .project_visualizer_window import ConnectionItem

logger = logging.getLogger(__name__)


class ProjectNode(QGraphicsObject):
    """
    Represents a single node (file, folder, or root) in the project visualizer graph.
    This is a QGraphicsObject that can be moved, selected, and connected with lines.
    """

    def __init__(self, name: str, node_type: str = "file", parent: Optional[QGraphicsItem] = None):
        """
        Initializes the ProjectNode.

        Args:
            name: The display name of the node (e.g., filename or folder name).
            node_type: The type of the node ('file', 'folder', 'root').
            parent: The parent QGraphicsItem in the scene.
        """
        super().__init__(parent)
        self.name = name
        self.node_type = node_type
        self.incoming_connections: List['ConnectionItem'] = []
        self.outgoing_connections: List['ConnectionItem'] = []

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounds of the node item.

        Returns:
            The bounding rectangle of the node.
        """
        return QRectF(0, 0, 150, 50)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        """
        Paints the node with a specific style based on its type.

        Args:
            painter: The QPainter to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        rect = self.boundingRect()

        if self.node_type == "folder":
            brush_color = Colors.ACCENT_BLUE
        elif self.node_type == "root":
            brush_color = Colors.ACCENT_PURPLE
        else:  # file
            brush_color = Colors.ELEVATED_BG

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(brush_color))
        painter.setPen(QPen(Colors.BORDER_DEFAULT, 2))
        painter.drawRoundedRect(rect, 10.0, 10.0)

        painter.setPen(QPen(Colors.TEXT_PRIMARY))
        painter.setFont(Typography.body())
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.name)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        """
        Handles changes to the item's state, such as its position.
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