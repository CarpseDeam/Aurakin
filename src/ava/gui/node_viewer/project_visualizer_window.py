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
from src.ava.gui.node_viewer.animated_connection import AnimatedConnection

logger = logging.getLogger(__name__)

# --- Layout Constants ---
COLUMN_WIDTH = 300
ROW_HEIGHT = 90


class ProjectVisualizerWindow(QMainWindow):
    """The main window for the project visualizer."""

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager):
        super().__init__()
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.nodes: Dict[str, ProjectNode] = {}
        self.connections: Dict[str, AnimatedConnection] = {}  # Map path -> incoming connection
        self._active_connection: Optional[AnimatedConnection] = None
        self._positions: Dict[str, QPointF] = {}

        self.setWindowTitle("Project Visualizer")
        self.setGeometry(150, 150, 1200, 800)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(Colors.PRIMARY_BG))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setCentralWidget(self.view)

    def display_scaffold(self, scaffold_files: Dict[str, str]):
        """NEW: Renders the entire project structure from the scaffold."""
        if not self.project_manager.active_project_path: return
        self.log("info", "Visualizer received project scaffold. Drawing node structure.")

        self._clear_scene()
        root_path = self.project_manager.active_project_path
        all_filenames = list(scaffold_files.keys())

        tree = self._build_tree_from_paths(all_filenames)
        self._positions = self._calculate_node_positions(tree, root_path)

        root_node = ProjectNode(root_path.name, str(root_path), True)
        self.nodes[str(root_path)] = root_node
        self.scene.addItem(root_node)
        root_node.setPos(self._positions[str(root_path)])

        self._create_nodes_recursively(tree, root_path, root_node)
        QTimer.singleShot(50, self._fit_view_with_padding)

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
            self._draw_connection(parent_node, node, current_path_str)
            if children:
                self._create_nodes_recursively(children, current_path, node)

    def _clear_scene(self) -> None:
        self.scene.clear()
        self.nodes.clear()
        self.connections.clear()
        self._active_connection = None
        self._positions.clear()

    def _fit_view_with_padding(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isValid(): return
        padding = 150
        rect.adjust(-padding, -padding, padding, padding)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _draw_connection(self, start_node: QGraphicsObject, end_node: QGraphicsObject,
                         end_node_path: str) -> AnimatedConnection:
        connection = AnimatedConnection(start_node, end_node)
        self.scene.addItem(connection)
        start_node.add_connection(connection, is_outgoing=True)
        end_node.add_connection(connection, is_outgoing=False)
        self.connections[end_node_path] = connection
        return connection

    def _handle_agent_activity(self, agent_name: str, target_file_path: str):
        """Activates the animation for a specific connection."""
        self.log("info", f"Visualizing activity for Agent: {agent_name} on file: {Path(target_file_path).name}")

        if self._active_connection:
            self._active_connection.deactivate()
            self._active_connection = None

        connection = self.connections.get(target_file_path)
        if not connection:
            self.log("warning", f"Could not find a connection for file path: {target_file_path}")
            return

        color = Colors.AGENT_ARCHITECT_COLOR
        if agent_name.lower() == "coder":
            color = Colors.AGENT_CODER_COLOR

        connection.activate(color)
        self._active_connection = connection

    def _deactivate_all_connections(self):
        """Turns off any active animations."""
        self.log("info", "Workflow finished. Deactivating all visualizer connections.")
        if self._active_connection:
            self._active_connection.deactivate()
            self._active_connection = None


    def _build_tree_from_paths(self, paths: List[str]) -> Dict:
        tree = {}
        all_paths = set()
        for p_str in paths:
            path_obj = Path(p_str)
            all_paths.add(p_str)
            # Add all parent directories to ensure the tree is complete
            for parent in path_obj.parents:
                if str(parent) != '.':
                    all_paths.add(str(parent))

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