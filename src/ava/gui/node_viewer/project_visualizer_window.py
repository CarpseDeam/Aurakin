# src/ava/gui/node_viewer/project_visualizer_window.py
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict
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
    QCloseEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QMenu,
)

from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager
from src.ava.gui.components import Colors
from src.ava.gui.node_viewer.project_node import ProjectNode
from src.ava.gui.node_viewer.animated_connection import AnimatedConnection
from src.ava.services.code_structure_service import CodeStructureService

logger = logging.getLogger(__name__)

COLUMN_WIDTH = 250
ROW_HEIGHT = 70


class ZoomableView(QGraphicsView):
    """A QGraphicsView that supports zooming and right-click context menus."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def wheelEvent(self, event: QWheelEvent):
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor
        zoom_factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(zoom_factor, zoom_factor)


class ProjectVisualizerWindow(QMainWindow):
    """The main window for the project visualizer, now with deep code inspection."""

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager):
        super().__init__()
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.code_structure_service = CodeStructureService()
        self.nodes: Dict[str, ProjectNode] = {}
        self.connections: Dict[str, AnimatedConnection] = {}
        self._active_connection: Optional[AnimatedConnection] = None
        self._positions: Dict[str, QPointF] = {}

        self.setWindowTitle("Project Visualizer (Test Lab)")
        self.setGeometry(150, 150, 1200, 800)
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(Colors.PRIMARY_BG))

        self.view = ZoomableView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self.setCentralWidget(self.view)

    def _show_context_menu(self, pos):
        item = self.view.itemAt(pos)
        if isinstance(item, ProjectNode) and item.node_type == 'function':
            menu = QMenu(self.view)
            action = menu.addAction("Generate Unit Tests")
            action.triggered.connect(lambda: self._request_unit_test_generation(item))
            menu.exec(self.view.mapToGlobal(pos))

    def _request_unit_test_generation(self, node: ProjectNode):
        self.log("info", f"User requested unit tests for function: {node.name}")
        self.event_bus.emit(
            "unit_test_generation_requested",
            node.name,
            node.full_code,
            node.path
        )
        # For now, we just log it. The next step will be to hook this up to the Tester AI.
        QTimer.singleShot(100,
                          lambda: self.log("success", "Event 'unit_test_generation_requested' emitted successfully."))

    def display_scaffold(self, scaffold_files: Dict[str, str]):
        if not self.project_manager.active_project_path: return
        self._render_project_structure(scaffold_files)

    def display_existing_project(self, project_path_str: str) -> None:
        project_files = self.project_manager.get_project_files()
        self._render_project_structure(project_files)

    def _render_project_structure(self, project_files: Dict[str, str]):
        """The main rendering entry point."""
        self._clear_scene()
        root_path = self.project_manager.active_project_path
        if not root_path: return

        # Build a hierarchical tree from file paths and code structure
        tree = self._build_full_code_tree(project_files)

        # Calculate positions for all nodes in the tree
        self._positions = self._calculate_node_positions(tree, root_path)

        # Create the root node for the project directory
        root_node = ProjectNode(root_path.name, str(root_path), 'folder')
        self.nodes[str(root_path)] = root_node
        self.scene.addItem(root_node)
        root_node.setPos(self._positions[str(root_path)])

        # Recursively create and draw all child nodes and connections
        self._create_nodes_recursively(tree, root_path, root_node)
        QTimer.singleShot(50, self._fit_view_with_padding)

    def _build_full_code_tree(self, project_files: Dict[str, str]) -> Dict:
        """Builds a nested dictionary representing the project, including code structure."""
        tree = {}
        for path_str, content in project_files.items():
            parts = Path(path_str).parts
            level = tree
            for part in parts:
                level = level.setdefault(part, {})

            # If it's a Python file, parse its structure
            if path_str.endswith('.py'):
                structure = self.code_structure_service.parse_structure(content)
                level['__structure__'] = structure
        return tree

    def _calculate_node_positions(self, tree: Dict, root_path: Path) -> Dict[str, QPointF]:
        """Calculates the X, Y coordinates for every node in the hierarchy."""
        positions = {}
        y_map = defaultdict(int)

        def layout_recursively(subtree: Dict, parent_path: Path, depth: int):
            # Sort to ensure folders come before files
            sorted_items = sorted(subtree.items(),
                                  key=lambda item: not isinstance(item[1], dict) or item[0] == '__structure__')

            for name, children in sorted_items:
                if name == '__structure__': continue

                current_path = parent_path / name
                current_path_str = str(current_path)

                # Position the file/folder node
                x = depth * COLUMN_WIDTH
                y = y_map[depth] * ROW_HEIGHT
                positions[current_path_str] = QPointF(x, y)
                y_map[depth] += 1

                # If there's code structure, lay out its children
                structure = children.get('__structure__')
                if structure:
                    y_map[depth + 1] = y_map[depth] - 1  # Align first child

                    for class_name, class_info in structure.get('classes', {}).items():
                        class_path_str = f"{current_path_str}::{class_name}"
                        positions[class_path_str] = QPointF(x + COLUMN_WIDTH, y_map[depth + 1] * ROW_HEIGHT)
                        y_map[depth + 1] += 1

                        for method_name in class_info.get('methods', {}):
                            method_path_str = f"{class_path_str}::{method_name}"
                            positions[method_path_str] = QPointF(x + 2 * COLUMN_WIDTH, y_map[depth + 2] * ROW_HEIGHT)
                            y_map[depth + 2] += 1

                    y_map[depth + 2] = y_map[depth + 1]  # Reset for functions
                    for func_name in structure.get('functions', {}):
                        func_path_str = f"{current_path_str}::{func_name}"
                        positions[func_path_str] = QPointF(x + COLUMN_WIDTH, y_map[depth + 1] * ROW_HEIGHT)
                        y_map[depth + 1] += 1

                # Recurse into subdirectories
                if isinstance(children, dict) and children:
                    layout_recursively(children, current_path, depth + 1)
                    y_map[depth] = max(y_map[depth], y_map[depth + 1])

        positions[str(root_path)] = QPointF(-COLUMN_WIDTH, 0)
        layout_recursively(tree, root_path, 0)
        return positions

    def _create_nodes_recursively(self, subtree: Dict, parent_path: Path, parent_node: QGraphicsObject) -> None:
        """Creates and draws all nodes and their connections based on the calculated positions."""
        sorted_items = sorted(subtree.items(),
                              key=lambda item: not isinstance(item[1], dict) or item[0] == '__structure__')

        for name, children in sorted_items:
            if name == '__structure__': continue

            current_path = parent_path / name
            current_path_str = str(current_path)
            is_folder = isinstance(children, dict) and '__structure__' not in children

            node_type = 'folder' if is_folder else 'file'
            node = ProjectNode(name, current_path_str, node_type)
            self.nodes[current_path_str] = node
            self.scene.addItem(node)
            node.setPos(self._positions[current_path_str])
            self._draw_connection(parent_node, node, current_path_str)

            # If there's code structure, render its nodes
            structure = children.get('__structure__')
            if structure:
                file_node = node
                for class_name, class_info in structure.get('classes', {}).items():
                    class_path_str = f"{current_path_str}::{class_name}"
                    class_node = ProjectNode(class_name, current_path_str, 'class', class_info['code'])
                    self.nodes[class_path_str] = class_node
                    self.scene.addItem(class_node)
                    class_node.setPos(self._positions[class_path_str])
                    self._draw_connection(file_node, class_node, class_path_str)

                    for method_name, method_code in class_info.get('methods', {}).items():
                        method_path_str = f"{class_path_str}::{method_name}"
                        method_node = ProjectNode(method_name, current_path_str, 'function', method_code)
                        self.nodes[method_path_str] = method_node
                        self.scene.addItem(method_node)
                        method_node.setPos(self._positions[method_path_str])
                        self._draw_connection(class_node, method_node, method_path_str)

                for func_name, func_code in structure.get('functions', {}).items():
                    func_path_str = f"{current_path_str}::{func_name}"
                    func_node = ProjectNode(func_name, current_path_str, 'function', func_code)
                    self.nodes[func_path_str] = func_node
                    self.scene.addItem(func_node)
                    func_node.setPos(self._positions[func_path_str])
                    self._draw_connection(file_node, func_node, func_path_str)

            if is_folder and children:
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
        padding = 50
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
        self.log("info", f"Visualizing activity for Agent: {agent_name} on file: {Path(target_file_path).name}")
        if self._active_connection:
            self._active_connection.deactivate()

        # We now connect to the file node, not just any node
        connection = self.connections.get(target_file_path)
        if not connection:
            self.log("warning", f"Could not find a connection for file path: {target_file_path}")
            return

        color = Colors.AGENT_ARCHITECT_COLOR if agent_name.lower() == "architect" else Colors.AGENT_CODER_COLOR
        connection.activate(color)
        self._active_connection = connection

    def _deactivate_all_connections(self):
        self.log("info", "Workflow finished. Deactivating all visualizer connections.")
        if self._active_connection:
            self._active_connection.deactivate()
            self._active_connection = None

    def show(self) -> None:
        super().show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def log(self, level: str, message: str):
        self.event_bus.emit("log_message_received", "ProjectVisualizer", level, message)