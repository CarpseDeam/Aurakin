# src/ava/gui/drone_item.py

import logging
import math
from typing import Optional

from PySide6.QtCore import Property, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath
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
    It supports both a path-following flight animation and a continuous orbital animation.
    """

    def __init__(self, parent: Optional[QGraphicsItem] = None) -> None:
        """
        Initializes the DroneItem.

        Args:
            parent: The parent QGraphicsItem, if any.
        """
        super().__init__(parent)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setZValue(10)

        # --- State for Animations ---
        self._orbit_center: Optional[QPointF] = None
        self._orbit_radius: float = 0.0
        self._orbit_angle: float = 0.0
        self._path: Optional[QPainterPath] = None
        self._path_progress: float = 0.0

    @Property(float)
    def orbitAngle(self) -> float:
        """
        Gets the current angle of the drone in its orbit.

        Returns:
            The current orbital angle in degrees.
        """
        return self._orbit_angle

    @orbitAngle.setter
    def orbitAngle(self, angle: float) -> None:
        """
        Sets the orbital angle and updates the drone's position accordingly.

        Args:
            angle: The new orbital angle in degrees.
        """
        if self._orbit_angle == angle:
            return
        self._orbit_angle = angle
        if self._orbit_center:
            rad_angle = math.radians(self._orbit_angle)
            dx = self._orbit_radius * math.cos(rad_angle)
            dy = self._orbit_radius * math.sin(rad_angle)
            new_pos = self._orbit_center + QPointF(dx, dy)
            self.setPos(new_pos)

    @Property(float)
    def pathProgress(self) -> float:
        """
        Gets the current progress of the drone along its flight path.

        Returns:
            The current progress as a float between 0.0 and 1.0.
        """
        return self._path_progress

    @pathProgress.setter
    def pathProgress(self, progress: float) -> None:
        """
        Sets the path progress and updates the drone's position along the path.

        Args:
            progress: The new progress as a float between 0.0 and 1.0.
        """
        if self._path_progress == progress:
            return
        self._path_progress = progress
        if self._path:
            new_pos = self._path.pointAtPercent(progress)
            self.setPos(new_pos)

    def set_orbit_parameters(self, center: QPointF, radius: float) -> None:
        """
        Sets the center and radius for the drone's orbital animation.

        Args:
            center: The center point of the orbit.
            radius: The radius of the orbit.
        """
        self._orbit_center = center
        self._orbit_radius = radius

    def set_follow_path(self, path: QPainterPath) -> None:
        """
        Sets the QPainterPath for the drone to follow during its flight animation.

        Args:
            path: The QPainterPath defining the flight trajectory.
        """
        self._path = path

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounding rectangle of the drone.

        Returns:
            A QRectF representing the drone's boundaries, including a margin
            for the glow effect to prevent visual clipping.
        """
        return QRectF(-6, -6, 12, 12)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: Optional[QWidget] = None,
    ) -> None:
        """
        Paints the drone's visual representation, consisting of a glowing orb.

        Args:
            painter: The QPainter instance to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        glow_color = QColor(Colors.ACCENT_BLUE)
        glow_color.setAlphaF(0.4)
        painter.setBrush(QBrush(glow_color))
        painter.drawEllipse(self.boundingRect())

        core_color = QColor(Colors.ACCENT_BLUE.lighter(150))
        painter.setBrush(QBrush(core_color))
        painter.drawEllipse(QRectF(-3, -3, 6, 6))