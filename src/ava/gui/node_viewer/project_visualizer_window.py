# src/ava/gui/node_viewer/project_visualizer_window.py
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Any
from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QPropertyAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QCloseEvent,
)
from PySide6.QtWidgets import (
    QGraphicsObject,
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QStyleOptionGraphicsItem,
    QWidget,
)

from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager
from src.ava.gui.components import Colors
from src.ava.gui.node_viewer.project_node import ProjectNode

logger = logging.getLogger(__name__)

# --- Layout Constants ---
COLUMN_WIDTH = 300
ROW_HEIGHT = 80


class ConnectionItem(QGraphicsPathItem):
    """A directed connection line with an arrowhead, linking two nodes."""

    def __init__(self, start_node: QGraphicsObject, end_node: QGraphicsObject):
        """
        Initializes the connection item.

        Args:
            start_node: The QGraphicsObject where the connection starts.
            end_node: The QGraphicsObject where the connection ends.
        """
        super().__init__()
        self.start_node = start_node
        self.end_node = end_node
        self.arrow_head = QPolygonF()
        pen = QPen(Colors.BORDER_DEFAULT, 1.0, Qt.PenStyle.DotLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(-1)
        self.update_path()

    def update_path(self) -> None:
        """
        Updates the path of the connection to a smooth S-shaped Bezier curve.
        """
        start_pos = self.start_node.pos() + QPointF(self.start_node.boundingRect().width(),
                                                    self.start_node.boundingRect().height() / 2)
        end_pos = self.end_node.pos() + QPointF(0, self.end_node.boundingRect().height() / 2)

        path = QPainterPath(start_pos)
        dx = abs(end_pos.x() - start_pos.x()) * 0.5
        c1 = QPointF(start_pos.x() + dx, start_pos.y())
        c2 = QPointF(end_pos.x() - dx, end_pos.y())
        path.cubicTo(c1, c2, end_pos)

        self.setPath(path)
        self._update_arrowhead(c2, end_pos)

    def _update_arrowhead(self, control_point: QPointF, end_point: QPointF) -> None:
        """
        Calculates the arrowhead polygon, aligning it with the curve's tangent.

        Args:
            control_point: The second control point of the Bezier curve (c2).
            end_point: The end point of the Bezier curve.
        """
        angle = math.atan2(end_point.y() - control_point.y(), end_point.x() - control_point.x())
        arrow_size = 8.0
        arrow_p1 = end_point - QPointF(math.cos(angle + math.pi / 6) * arrow_size,
                                       math.sin(angle + math.pi / 6) * arrow_size)
        arrow_p2 = end_point - QPointF(math.cos(angle - math.pi / 6) * arrow_size,
                                       math.sin(angle - math.pi / 6) * arrow_size)
        self.arrow_head.clear()
        self.arrow_head.append(end_point)
        self.arrow_head.append(arrow_p1)
        self.arrow_head.append(arrow_p2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        """
        Paints the connection line and its arrowhead.

        Args:
            painter: The QPainter to use for drawing.
            option: The style options for the item.
            widget: The widget being painted on, if any.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)
        painter.setBrush(QBrush(Colors.BORDER_DEFAULT))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(self.arrow_head)


class ProjectVisualizerWindow(QMainWindow):
    """The main window for the project visualizer."""

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager):
        """
        Initializes the ProjectVisualizerWindow.

        Args:
            event_bus: The application's event bus.
            project_manager: The application's project manager.
        """
        super().__init__()
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.nodes: Dict[str, ProjectNode] = {}
        self._positions: Dict[str, QPointF] = {}

        self.setWindowTitle("Project Visualizer")
        self.setGeometry(150, 150, 1200, 800)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(Colors.PRIMARY_BG))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCentralWidget(self.view)

    def handle_project_plan_generated(self, plan: Dict[str, Any]) -> None:
        """
        Animates the generation of a new project tree based on an AI plan.

        Args:
            plan: The project plan dictionary from the architect.
        """
        if not self.project_manager.active_project_path: return

        root_path = self.project_manager.active_project_path
        all_filenames = [t['filename'] for t in plan.get("tasks", []) if 'filename' in t]
        tree = self._build_tree_from_paths(all_filenames)

        # Calculate final positions for all nodes in the plan
        self._positions = self._calculate_node_positions(tree, root_path)

        animations = QParallelAnimationGroup()

        # This recursive call finds new nodes and creates their animations
        self._animate_nodes_recursively(tree, root_path, self.nodes[str(root_path)], animations)

        if animations.animationCount() > 0:
            animations.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        QTimer.singleShot(600, self._fit_view_with_padding)

    def display_existing_project(self, project_path_str: str) -> None:
        """
        Displays the static file tree of a new or loaded project.

        Args:
            project_path_str: The string path to the project root.
        """
        root_path = Path(project_path_str)
        if not root_path.is_dir(): return

        self._clear_scene()
        tree = self._scan_directory_for_tree(root_path)
        self._positions = self._calculate_node_positions(tree, root_path)

        # Create and position the root node
        root_node = ProjectNode(root_path.name, str(root_path), True)
        self.nodes[str(root_path)] = root_node
        self.scene.addItem(root_node)
        root_node.setPos(self._positions[str(root_path)])

        # Create all child nodes statically
        self._create_nodes_recursively(tree, root_path, root_node)

        QTimer.singleShot(50, self._fit_view_with_padding)

    def _animate_nodes_recursively(self, subtree: Dict, parent_path: Path, parent_node: QGraphicsObject,
                                   anim_group: QParallelAnimationGroup) -> None:
        """
        Recursively finds new nodes in a plan and creates animations for them.

        Args:
            subtree: The current branch of the file tree dictionary.
            parent_path: The Path object of the parent node.
            parent_node: The QGraphicsObject of the parent node.
            anim_group: The animation group to add new animations to.
        """
        sorted_children = sorted(subtree.items(), key=lambda item: not bool(item[1]))

        for name, children in sorted_children:
            current_path = parent_path / name
            current_path_str = str(current_path)

            # If node doesn't exist, it's new and needs animation
            if current_path_str not in self.nodes:
                is_folder = bool(children)
                node = ProjectNode(name, current_path_str, is_folder)
                self.nodes[current_path_str] = node
                self.scene.addItem(node)

                connection = self._draw_connection(parent_node, node)

                # Start node at parent's position and fade it in
                node.setPos(parent_node.pos())
                node.setOpacity(0)
                connection.setVisible(False)

                move_anim = QPropertyAnimation(node, b"pos")
                move_anim.setDuration(500)
                move_anim.setEndValue(self._positions[current_path_str])
                move_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                anim_group.addAnimation(move_anim)

                fade_in = QPropertyAnimation(node, b"opacity")
                fade_in.setDuration(300)
                fade_in.setEndValue(1)
                anim_group.addAnimation(fade_in)

                # Make connection visible after animation
                anim_group.finished.connect(lambda c=connection: c.setVisible(True))

            # Recurse into children
            if children:
                self._animate_nodes_recursively(children, current_path, self.nodes[current_path_str], anim_group)

    def _create_nodes_recursively(self, subtree: Dict, parent_path: Path, parent_node: QGraphicsObject) -> None:
        """
        Recursively creates nodes and connections for a static display.

        Args:
            subtree: The current branch of the file tree dictionary.
            parent_path: The Path object of the parent node.
            parent_node: The QGraphicsObject of the parent node.
        """
        sorted_children = sorted(subtree.items(), key=lambda item: not bool(item[1]))
        for name, children in sorted_children:
            current_path = parent_path / name
            current_path_str = str(current_path)
            is_folder = bool(children)

            node = ProjectNode(name, current_path_str, is_folder)
            self.nodes[current_path_str] = node
            self.scene.addItem(node)
            node.setPos(self._positions[current_path_str])
            self._draw_connection(parent_node, node)

            if children:
                self._create_nodes_recursively(children, current_path, node)

    def _clear_scene(self) -> None:
        """Clears all items from the scene and resets internal state."""
        self.scene.clear()
        self.nodes.clear()
        self._positions.clear()

    def _fit_view_with_padding(self) -> None:
        """Fits the view to the scene content with some padding."""
        rect = self.scene.itemsBoundingRect()
        padding = 150
        rect.adjust(-padding, -padding, padding, padding)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_connection(self, start_node: QGraphicsObject, end_node: QGraphicsObject) -> ConnectionItem:
        """
        Draws a connection between two nodes and registers it with them.

        Args:
            start_node: The starting node.
            end_node: The ending node.

        Returns:
            The created ConnectionItem.
        """
        connection = ConnectionItem(start_node, end_node)
        self.scene.addItem(connection)
        start_node.add_connection(connection, is_outgoing=True)
        end_node.add_connection(connection, is_outgoing=False)
        return connection

    def _build_tree_from_paths(self, paths: List[str]) -> Dict:
        """
        Builds a nested dictionary representing a file tree from a flat list of paths.

        Args:
            paths: A list of file path strings.

        Returns:
            A dictionary representing the file tree.
        """
        tree = {}
        for p in paths:
            parts = Path(p).parts
            if not parts: continue
            level = tree
            for part in parts:
                if part not in level: level[part] = {}
                level = level[part]
        return tree

    def _scan_directory_for_tree(self, root_path: Path) -> Dict:
        """
        Recursively scans a directory to build a file tree dictionary.

        Args:
            root_path: The root directory to scan.

        Returns:
            A dictionary representing the file tree.
        """
        tree = {}
        ignore_dirs = {'.git', '__pycache__', '.venv', 'venv', 'rag_db', '.ava_sessions'}
        for item in sorted(root_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if item.name in ignore_dirs:
                continue
            if item.is_dir():
                tree[item.name] = self._scan_directory_for_tree(item)
            else:
                tree[item.name] = {}
        return tree

    def _calculate_node_positions(self, tree: Dict, root_path: Path) -> Dict[str, QPointF]:
        """
        Calculates the layout positions for all nodes in a tree.

        Args:
            tree: The file tree dictionary.
            root_path: The Path object for the root of the tree.

        Returns:
            A dictionary mapping string paths to QPointF positions.
        """
        positions = {}

        def get_subtree_leaf_count(subtree: Dict) -> int:
            if not subtree: return 1
            return sum(get_subtree_leaf_count(children) for children in subtree.values())

        def layout_recursively(subtree: Dict, parent_path: Path, parent_center_y: float, depth: int):
            total_height = sum(get_subtree_leaf_count(children) * ROW_HEIGHT for children in subtree.values())
            current_y = parent_center_y - total_height / 2

            sorted_children = sorted(subtree.items(), key=lambda item: not bool(item[1]))
            for name, children in sorted_children:
                item_path = parent_path / name
                leaf_count = get_subtree_leaf_count(children)
                node_height = leaf_count * ROW_HEIGHT
                child_center_y = current_y + node_height / 2
                positions[str(item_path)] = QPointF(depth * COLUMN_WIDTH, child_center_y)
                if children:
                    layout_recursively(children, item_path, child_center_y, depth + 1)
                current_y += node_height

        root_pos = QPointF(0, 0)
        positions[str(root_path)] = root_pos
        layout_recursively(tree, root_path, root_pos.y(), 1)
        return positions

    def show(self) -> None:
        """Shows the window and brings it to the front."""
        super().show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Overrides the close event to hide the window instead of closing it.

        Args:
            event: The close event.
        """
        event.ignore()
        self.hide()