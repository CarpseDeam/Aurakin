# src/ava/gui/node_viewer/project_visualizer_window.py
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Any
from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
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
ROW_HEIGHT = 90


class ConnectionItem(QGraphicsPathItem):
    """A directed connection line with an arrowhead, linking two nodes."""

    def __init__(self, start_node: QGraphicsObject, end_node: QGraphicsObject):
        super().__init__()
        self.start_node = start_node
        self.end_node = end_node
        self.arrow_head = QPolygonF()
        pen = QPen(QColor("#555"), 2.0, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self.setPen(pen)
        self.setZValue(-1)
        self.update_path()

    def update_path(self) -> None:
        start_pos = self.start_node.pos() + QPointF(self.start_node.boundingRect().width(),
                                                    self.start_node.boundingRect().height() / 2)
        end_pos = self.end_node.pos() + QPointF(0, self.end_node.boundingRect().height() / 2)

        path = QPainterPath(start_pos)
        offset = (end_pos.x() - start_pos.x()) * 0.5
        c1 = QPointF(start_pos.x() + offset, start_pos.y())
        c2 = QPointF(end_pos.x() - offset, end_pos.y())
        path.cubicTo(c1, c2, end_pos)

        self.setPath(path)
        self._update_arrowhead(path, end_pos)

    def _update_arrowhead(self, path: QPainterPath, end_point: QPointF) -> None:
        angle_rad = math.radians(180 - path.angleAtPercent(1.0))
        arrow_size = 10.0
        arrow_p1 = end_point + QPointF(math.cos(angle_rad - math.pi / 6) * arrow_size,
                                       math.sin(angle_rad - math.pi / 6) * arrow_size)
        arrow_p2 = end_point + QPointF(math.cos(angle_rad + math.pi / 6) * arrow_size,
                                       math.sin(angle_rad + math.pi / 6) * arrow_size)
        self.arrow_head.clear()
        self.arrow_head.append(end_point)
        self.arrow_head.append(arrow_p1)
        self.arrow_head.append(arrow_p2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: Optional[QWidget] = None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        super().paint(painter, option, widget)
        painter.setBrush(QBrush(QColor("#555")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(self.arrow_head)


class ProjectVisualizerWindow(QMainWindow):
    """The main window for the project visualizer."""

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager):
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

        self.event_bus.subscribe("project_plan_generated", self.handle_project_plan_generated)
        self.event_bus.subscribe("project_root_selected", self.display_existing_project)
        self.event_bus.subscribe("workflow_finalized", lambda final_code: self.display_existing_project(
            self.project_manager.active_project_path))
        self.event_bus.subscribe("file_generation_starting", self._handle_file_generation_starting)

    def handle_project_plan_generated(self, plan: Dict[str, Any]) -> None:
        if not self.project_manager.active_project_path: return
        self.log("info", "Visualizer received project plan. Calculating node layout.")

        root_path = self.project_manager.active_project_path
        self._clear_scene()

        root_node = ProjectNode(root_path.name, str(root_path), True)
        self.nodes[str(root_path)] = root_node
        self.scene.addItem(root_node)

        all_filenames = [t['filename'] for t in plan.get("tasks", []) if 'filename' in t]
        tree = self._build_tree_from_paths(all_filenames)

        self._positions = self._calculate_node_positions(tree, root_path)
        root_node.setPos(self._positions[str(root_path)])
        self.log("info", f"Calculated positions for {len(self._positions)} nodes.")
        QTimer.singleShot(50, self._fit_view_with_padding)

    def _handle_file_generation_starting(self, filename: str) -> None:
        self.log("info", f"Visualizer drawing node: {filename}")
        if not self.project_manager.active_project_path: return

        full_path = self.project_manager.active_project_path / filename
        current_parent_node = self.nodes.get(str(self.project_manager.active_project_path))
        if not current_parent_node:
            self.log("error", "Root project node is missing.")
            return

        path_accumulator = self.project_manager.active_project_path
        for part in Path(filename).parent.parts:
            path_accumulator /= part
            path_acc_str = str(path_accumulator)

            if path_acc_str not in self.nodes:
                folder_node = ProjectNode(part, path_acc_str, True)
                self.nodes[path_acc_str] = folder_node
                self.scene.addItem(folder_node)
                if path_acc_str in self._positions:
                    folder_node.setPos(self._positions[path_acc_str])
                self._draw_connection(current_parent_node, folder_node)
                current_parent_node = folder_node
            else:
                current_parent_node = self.nodes[path_acc_str]

        full_path_str = str(full_path)
        if full_path_str not in self.nodes:
            is_folder = any(p.startswith(full_path_str + '/') for p in self._positions.keys())
            node = ProjectNode(full_path.name, full_path_str, is_folder)
            self.nodes[full_path_str] = node
            self.scene.addItem(node)
            if full_path_str in self._positions:
                node.setPos(self._positions[full_path_str])
            else:
                self.log("error", f"No position calculated for {filename}!")
                node.setPos(current_parent_node.pos() + QPointF(50, 50))
            self._draw_connection(current_parent_node, node)
            self._fit_view_with_padding()

    def display_existing_project(self, project_path_str: str) -> None:
        root_path = Path(project_path_str)
        if not root_path.is_dir(): return

        self._clear_scene()
        tree = self._scan_directory_for_tree(root_path)
        self._positions = self._calculate_node_positions(tree, root_path)

        root_node = ProjectNode(root_path.name, str(root_path), True)
        self.nodes[str(root_path)] = root_node
        self.scene.addItem(root_node)
        root_node.setPos(self._positions[str(root_path)])

        self._create_nodes_recursively(tree, root_path, root_node)
        QTimer.singleShot(50, self._fit_view_with_padding)

    def _create_nodes_recursively(self, subtree: Dict, parent_path: Path, parent_node: QGraphicsObject) -> None:
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
        self.scene.clear()
        self.nodes.clear()
        self._positions.clear()

    def _fit_view_with_padding(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isValid(): return
        padding = 150
        rect.adjust(-padding, -padding, padding, padding)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_connection(self, start_node: QGraphicsObject, end_node: QGraphicsObject) -> ConnectionItem:
        connection = ConnectionItem(start_node, end_node)
        self.scene.addItem(connection)
        start_node.add_connection(connection, is_outgoing=True)
        end_node.add_connection(connection, is_outgoing=False)
        return connection

    def _build_tree_from_paths(self, paths: List[str]) -> Dict:
        tree = {}
        all_paths = set(p for p_str in paths for p in [str(parent) for parent in Path(p_str).parents if str(parent) != '.'] + [p_str])
        for p in sorted(list(all_paths)):
            level = tree
            for part in Path(p).parts:
                level = level.setdefault(part, {})
        return tree

    def _scan_directory_for_tree(self, root_path: Path) -> Dict:
        tree = {}
        ignore_dirs = {'.git', '__pycache__', '.venv', 'venv', 'rag_db', '.ava_sessions'}
        try:
            for item in sorted(root_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
                if item.name in ignore_dirs: continue
                if item.is_dir():
                    tree[item.name] = self._scan_directory_for_tree(item)
                else:
                    tree[item.name] = {}
        except FileNotFoundError:
            return {}
        return tree

    def _calculate_node_positions(self, tree: Dict, root_path: Path) -> Dict[str, QPointF]:
        positions = {}

        def get_subtree_leaf_count(subtree: Dict) -> int:
            if not subtree: return 1
            return sum(get_subtree_leaf_count(children) for children in subtree.values())

        def layout_recursively(subtree: Dict, parent_path: Path, parent_center_y: float, depth: int):
            sorted_children = sorted(subtree.items(), key=lambda item: not bool(item[1]))
            total_height = sum(get_subtree_leaf_count(children) * ROW_HEIGHT for _, children in sorted_children)
            current_y = parent_center_y - total_height / 2
            for name, children in sorted_children:
                item_path = parent_path / name
                leaf_count = get_subtree_leaf_count(children)
                node_height = leaf_count * ROW_HEIGHT
                child_center_y = current_y + node_height / 2
                positions[str(item_path)] = QPointF(depth * COLUMN_WIDTH, child_center_y)
                if children:
                    layout_recursively(children, item_path, child_center_y, depth + 1)
                current_y += node_height

        root_pos = QPointF(-COLUMN_WIDTH / 2, 0)
        positions[str(root_path)] = root_pos
        layout_recursively(tree, root_path, root_pos.y(), 1)
        return positions

    def show(self) -> None:
        super().show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def log(self, level: str, message: str):
        self.event_bus.emit("log_message_received", "ProjectVisualizer", level, message)