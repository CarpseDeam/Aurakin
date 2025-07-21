# src/ava/gui/drone_item.py

import logging
from typing import Optional

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsObject,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.ava.gui.components import Colors

logger = logging.getLogger(__name__)


class DroneItem(QGraphicsObject):
    """
    A visual representation of an AI agent's activity, animated as a 'drone'.

    This QGraphicsObject is a simple, glowing orb designed to be moved across
    the ProjectVisualizer scene to indicate that an AI agent is "visiting" or
    interacting with a file or folder node.
    """

    def __init__(self, parent: Optional[QGraphicsItem] = None) -> None:
        """
        Initializes the DroneItem.

        Args:
            parent: The parent QGraphicsItem, if any.
        """
        super().__init__(parent)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        # Drones are not user-interactive; they are purely for animation.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounds of the item for painting and interaction.

        The bounding rectangle is centered on (0,0) to simplify positioning.

        Returns:
            A QRectF representing the drone's bounding box.
        """
        return QRectF(-6, -6, 12, 12)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: Optional[QWidget] = None,
    ) -> None:
        """
        Paints the contents of the drone.

        This method draws a two-layered circle to create a glowing orb effect.

        Args:
            painter: The QPainter to use for drawing.
            option: Provides style options for the item (unused).
            widget: The widget that is being painted on (unused).
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        # Outer glow
        glow_color = QColor(Colors.ACCENT_BLUE)
        glow_color.setAlphaF(0.4)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(self.boundingRect())

        # Inner core
        core_color = QColor(Colors.ACCENT_BLUE.lighter(150))
        painter.setBrush(QBrush(core_color))
        painter.drawEllipse(QRectF(-3, -3, 6, 6))