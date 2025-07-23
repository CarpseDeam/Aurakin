# src/ava/gui/node_viewer/animated_connection.py
import math
from typing import Optional

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsObject,
    QGraphicsPathItem,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.ava.gui.components import Colors


class AnimatedConnection(QGraphicsPathItem):
    """
    A directed connection line that can animate with a glowing pulse
    to indicate AI agent activity.
    """

    def __init__(self, start_node: QGraphicsObject, end_node: QGraphicsObject):
        super().__init__()
        self.start_node = start_node
        self.end_node = end_node

        # --- State ---
        self._is_active = False
        self._base_color = QColor(Colors.BORDER_DEFAULT)
        self._glow_color = self._base_color
        self._current_pen_width = 2.0
        self._pulse_direction = 1  # 1 for increasing, -1 for decreasing

        self.arrow_head = QPolygonF()
        self.setZValue(-1)  # Draw behind nodes

        # --- Animation Timer ---
        self.animation_timer = QTimer()
        self.animation_timer.setInterval(50)  # ~20 FPS is fine for a pulse
        self.animation_timer.timeout.connect(self._update_pulse)

        # Initial setup
        self.deactivate()
        self.update_path()

    def activate(self, color: QColor):
        """Activates the pulsing animation with a specific color."""
        if self._is_active:
            return
        self._is_active = True
        self._glow_color = color
        self._pulse_direction = 1
        self.animation_timer.start()

    def deactivate(self):
        """Stops the animation and returns the line to its default state."""
        self._is_active = False
        self.animation_timer.stop()
        self._current_pen_width = 2.0
        # Update pen to the inactive state
        pen = QPen(self._base_color, self._current_pen_width, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.update()

    def _update_pulse(self):
        """The core animation loop called by the QTimer."""
        if not self._is_active:
            return

        # Animate pen width for a "breathing" effect
        pulse_speed = 0.2
        if self._pulse_direction == 1:
            self._current_pen_width += pulse_speed
            if self._current_pen_width >= 4.0:
                self._current_pen_width = 4.0
                self._pulse_direction = -1
        else:
            self._current_pen_width -= pulse_speed
            if self._current_pen_width <= 2.0:
                self._current_pen_width = 2.0
                self._pulse_direction = 1

        # Blend the color towards the glow color based on width
        # This gives a nice effect where it gets brighter as it gets thicker
        width_ratio = (self._current_pen_width - 2.0) / 2.0  # a value from 0.0 to 1.0

        r = int(self._base_color.red() * (1 - width_ratio) + self._glow_color.red() * width_ratio)
        g = int(self._base_color.green() * (1 - width_ratio) + self._glow_color.green() * width_ratio)
        b = int(self._base_color.blue() * (1 - width_ratio) + self._glow_color.blue() * width_ratio)

        pulse_color = QColor(r, g, b)

        pen = QPen(pulse_color, self._current_pen_width, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)

        # This will trigger a repaint of the item
        self.update()

    def update_path(self) -> None:
        """Recalculates the curve of the line when a connected node moves."""
        # Get connection points from the middle-right of the start node
        # and middle-left of the end node.
        start_pos = self.start_node.pos() + QPointF(self.start_node.boundingRect().width(),
                                                    self.start_node.boundingRect().height() / 2)
        end_pos = self.end_node.pos() + QPointF(0, self.end_node.boundingRect().height() / 2)

        # Create a nice Bezier curve for the path
        path = QPainterPath(start_pos)
        offset = (end_pos.x() - start_pos.x()) * 0.5
        c1 = QPointF(start_pos.x() + offset, start_pos.y())
        c2 = QPointF(end_pos.x() - offset, end_pos.y())
        path.cubicTo(c1, c2, end_pos)

        self.setPath(path)
        self._update_arrowhead(path, end_pos)

    def _update_arrowhead(self, path: QPainterPath, end_point: QPointF) -> None:
        """Calculates the shape of the arrowhead."""
        # We want the arrow to point in the direction of the line's end
        angle_rad = math.radians(180 - path.angleAtPercent(1.0))
        arrow_size = 10.0

        # Calculate the two points of the arrowhead based on the angle and size
        arrow_p1 = end_point + QPointF(math.cos(angle_rad - math.pi / 6) * arrow_size,
                                       math.sin(angle_rad - math.pi / 6) * arrow_size)
        arrow_p2 = end_point + QPointF(math.cos(angle_rad + math.pi / 6) * arrow_size,
                                       math.sin(angle_rad + math.pi / 6) * arrow_size)

        self.arrow_head.clear()
        self.arrow_head.append(end_point)
        self.arrow_head.append(arrow_p1)
        self.arrow_head.append(arrow_p2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        """Draws the line and the arrowhead."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # The parent class draws the line itself
        super().paint(painter, option, widget)

        # We manually draw the arrowhead
        painter.setBrush(QBrush(self.pen().color()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(self.arrow_head)