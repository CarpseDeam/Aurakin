# src/ava/gui/node_viewer/project_visualizer_window.py
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import defaultdict
import qasync
import os

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
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
    QWidget,
    QHBoxLayout,
)

from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager
from src.ava.gui.components import Colors
from src.ava.gui.node_viewer.project_node import ProjectNode
from src.ava.gui.node_viewer.animated_connection import AnimatedConnection
from src.ava.services.code_structure_service import CodeStructureService
from src.ava.gui.node_viewer.project_actions_sidebar import ProjectActionsSidebar

logger = logging.getLogger(__name__)

# Constants for layout
COLUMN_WIDTH = 250
ROW_HEIGHT = 65


def _normalize_path_key(path_str: str) -> str:
    """A single, authoritative function to normalize a path for use as a dictionary key."""
    return os.path.normcase(os.path.abspath(path_str))


class ZoomableView(QGraphicsView):
    """A QGraphicsView that supports zooming and panning."""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def wheelEvent(self, event: QWheelEvent):
        """Zoom in and out with the mouse wheel."""
        zoom_in_factor = 1.15
        zoom_out_factor = 1 / zoom_in_factor
        zoom_factor = zoom_in_factor if event.angleDelta().y() > 0 else zoom_out_factor
        self.scale(zoom_factor, zoom_factor)


class ProjectVisualizerWindow(QMainWindow):
    """The main window for the project visualizer, now with deep code inspection and collapsible nodes."""

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager):
        super().__init__()
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.code_structure_service = CodeStructureService()
        self.nodes: Dict[str, ProjectNode] = {}
        self.connections: List[AnimatedConnection] = []
        self._active_connections: List[AnimatedConnection] = []
        self._animation_group = QParallelAnimationGroup()

        self.setWindowTitle("Project Visualizer & Test Lab")
        self.setGeometry(150, 150, 1400, 800)  # Made wider for the sidebar
        self.scene = QGraphicsScene()
        self.scene.setBackgroundBrush(QColor(Colors.PRIMARY_BG))

        # --- Main Layout with Sidebar ---
        central_widget = QWidget()
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.view = ZoomableView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self.view, 1)  # Graphics view takes up expanding space

        self.sidebar = ProjectActionsSidebar(event_bus, project_manager)
        main_layout.addWidget(self.sidebar)

        self.setCentralWidget(central_widget)

        # Connect event to update sidebar
        self.event_bus.subscribe("command_execution_finished", self.sidebar.update_on_command_finish)

    def _is_root_node(self, item: ProjectNode) -> bool:
        """Checks if the given node is the root project node."""
        if not self.project_manager.active_project_path:
            return False
        return _normalize_path_key(item.path) == _normalize_path_key(str(self.project_manager.active_project_path))

    def _show_context_menu(self, pos):
        """Show context menu for running programs, generating tests, and healing."""
        item = self.view.itemAt(pos)
        if not isinstance(item, ProjectNode) or not self.project_manager.active_project_path:
            return

        menu = QMenu(self.view)
        rel_path = Path(item.path).relative_to(self.project_manager.active_project_path).as_posix()

        # Action: Run Program (Individual File)
        if item.node_type == 'file' and item.name.endswith('.py'):
            command_to_run = f"python {rel_path}"
            action = menu.addAction(f"▶️ Run {item.name}")
            action.triggered.connect(
                lambda checked=False, cmd=command_to_run: self.event_bus.emit("run_program_and_heal_requested", cmd)
            )

        # Action: Generate Tests for Entire File
        if item.node_type == 'file' and item.name.endswith('.py'):
            action = menu.addAction(f"Generate Tests for {item.name}")
            action.triggered.connect(
                lambda checked=False, path=rel_path: self.event_bus.emit("test_file_generation_requested", path)
            )

        # Action: Generate Unit Tests for a single function
        if item.node_type == 'function':
            action = menu.addAction(f"Generate Tests for {item.name}()")
            action.triggered.connect(lambda: self._request_unit_test_generation(item))

        # Action: Run Tests & Heal (from root)
        if self._is_root_node(item):
            menu.addSeparator()
            heal_action = menu.addAction("🧪 Run Tests & Heal")
            heal_action.triggered.connect(
                lambda: self.event_bus.emit("heal_project_requested")
            )

        if not menu.isEmpty():
            if menu.actions() and menu.actions()[-1].isSeparator():
                menu.removeAction(menu.actions()[-1])
            menu.exec(self.view.mapToGlobal(pos))

    def _request_unit_test_generation(self, node: ProjectNode):
        """Emit event to request unit test generation for a function."""
        self.log("info", f"User requested unit tests for function: {node.name}")
        self.event_bus.emit(
            "unit_test_generation_requested",
            node.name,
            node.path
        )

    @qasync.Slot(dict)
    def display_scaffold(self, scaffold_files: Dict[str, str]):
        if not self.project_manager.active_project_path: return
        self._render_project_structure(scaffold_files)

    @qasync.Slot(str)
    def display_existing_project(self, project_path_str: str) -> None:
        project_files = self.project_manager.get_project_files()
        if not project_files:
            self.log("warning", f"No readable files found in project: {project_path_str}")
            self._clear_scene()
            return
        self._render_project_structure(project_files)
        # When a project is loaded, ensure the sidebar is ready
        self.sidebar.hide_heal_button()
        self.sidebar.status_label.setText("Ready")

    def _render_project_structure(self, project_files: Dict[str, str]):
        self._clear_scene()
        root_path = self.project_manager.active_project_path
        if not root_path: return

        tree = self._build_full_code_tree(project_files)

        root_node = ProjectNode(root_path.name, str(root_path), 'folder')
        root_key = _normalize_path_key(str(root_path))
        self.nodes[root_key] = root_node
        self.scene.addItem(root_node)

        self._create_nodes_recursively(tree, root_path, root_node)

        for node in self.nodes.values():
            if node.parent_node and node.parent_node.parent_node:
                node.is_expanded = False

        self._set_children_visibility(root_node, root_node.is_expanded)
        self._relayout_and_animate(fit_view=True)

    def _build_full_code_tree(self, project_files: Dict[str, str]) -> Dict:
        tree = {}
        for path_str, content in project_files.items():
            parts = Path(path_str).parts
            level = tree
            for part in parts:
                level = level.setdefault(part, {})
            structure = self.code_structure_service.parse_structure(content)
            level['__structure__'] = structure
        return tree

    def _create_nodes_recursively(self, subtree: Dict, parent_path: Path, parent_node: ProjectNode) -> None:
        sorted_items = sorted(subtree.items(), key=lambda item: (
            '__structure__' in item[1],
            item[0]
        ))

        for name, children in sorted_items:
            if name == '__structure__': continue

            current_path = parent_path / name
            current_path_str = str(current_path)
            is_folder = isinstance(children, dict) and '__structure__' not in children
            node_type = 'folder' if is_folder else 'file'

            node = ProjectNode(name, current_path_str, node_type)
            node_key = _normalize_path_key(current_path_str) if node_type in ['file',
                                                                              'folder'] else f"{_normalize_path_key(current_path_str)}::{name}"
            self._setup_new_node(node, parent_node, node_key)

            structure = children.get('__structure__')
            if structure:
                self._create_structure_nodes(structure, current_path_str, node)

            if is_folder and children:
                self._create_nodes_recursively(children, current_path, node)

    def _create_structure_nodes(self, structure: Dict, file_path_str: str, file_node: ProjectNode):
        for class_name in structure.get('classes', {}):
            class_path_key = f"{_normalize_path_key(file_path_str)}::{class_name}"
            class_node = ProjectNode(class_name, file_path_str, 'class')
            self._setup_new_node(class_node, file_node, class_path_key)

        for func_name in structure.get('functions', {}):
            func_path_key = f"{_normalize_path_key(file_path_str)}::{func_name}"
            func_node = ProjectNode(func_name, file_path_str, 'function')
            self._setup_new_node(func_node, file_node, func_path_key)

    def _setup_new_node(self, child_node: ProjectNode, parent_node: ProjectNode, node_key: str):
        self.nodes[node_key] = child_node
        self.scene.addItem(child_node)
        child_node.parent_node = parent_node
        parent_node.child_nodes.append(child_node)
        child_node.toggle_requested.connect(lambda n=child_node: self._handle_node_toggle(n))
        self._create_connection(parent_node, child_node)

    def _create_connection(self, start_node: ProjectNode, end_node: ProjectNode) -> AnimatedConnection:
        connection = AnimatedConnection(start_node, end_node)
        self.scene.addItem(connection)
        start_node.add_connection(connection, is_outgoing=True)
        end_node.add_connection(connection, is_outgoing=False)
        self.connections.append(connection)
        return connection

    def _handle_node_toggle(self, node: ProjectNode):
        node.is_expanded = not node.is_expanded
        self.log("info", f"Node '{node.name}' {'expanded' if node.is_expanded else 'collapsed'}.")
        self._set_children_visibility(node, node.is_expanded)
        self._relayout_and_animate()

    def _set_children_visibility(self, parent_node: ProjectNode, is_visible: bool):
        for child in parent_node.child_nodes:
            child.setVisible(is_visible)
            if child.incoming_connection:
                child.incoming_connection.setVisible(is_visible)

            if child.is_expanded and is_visible:
                self._set_children_visibility(child, True)
            else:
                self._set_children_visibility(child, False)

    def _calculate_node_positions(self) -> Dict[str, QPointF]:
        positions = {}
        y_map = defaultdict(int)

        root_path = str(self.project_manager.active_project_path) if self.project_manager.active_project_path else None
        if not root_path: return {}

        root_key = _normalize_path_key(root_path)
        root_node = self.nodes.get(root_key)
        if not root_node: return {}

        def layout_recursively(node: ProjectNode, depth: int):
            node_key = _normalize_path_key(node.path) if node.node_type in ['file',
                                                                            'folder'] else f"{_normalize_path_key(node.path)}::{node.name}"

            x = depth * COLUMN_WIDTH
            y = y_map[depth] * ROW_HEIGHT
            positions[node_key] = QPointF(x, y)
            y_map[depth] += 1

            if node.is_expanded:
                sorted_children = sorted(node.child_nodes, key=lambda n: (n.node_type != 'folder', n.name))
                for child in sorted_children:
                    if child.isVisible():
                        layout_recursively(child, depth + 1)

            if depth + 1 in y_map:
                y_map[depth] = max(y_map[depth], y_map[depth + 1])

        layout_recursively(root_node, 0)
        return positions

    def _relayout_and_animate(self, fit_view: bool = False):
        self.log("info", "Relaying out and animating nodes...")
        new_positions = self._calculate_node_positions()

        self._animation_group.stop()
        self._animation_group = QParallelAnimationGroup()

        for node_key, node in self.nodes.items():
            if node.isVisible() and node_key in new_positions:
                target_pos = new_positions[node_key]
                if node.pos() != target_pos:
                    anim = QPropertyAnimation(node, b"pos")
                    anim.setEndValue(target_pos)
                    anim.setDuration(400)
                    anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
                    self._animation_group.addAnimation(anim)

        self._animation_group.finished.connect(lambda: self._on_layout_animation_finished(fit_view))
        self._animation_group.start()

    def _on_layout_animation_finished(self, fit_view: bool):
        self._update_all_connections()
        if fit_view:
            QTimer.singleShot(10, self._fit_view_with_padding)

    def _update_all_connections(self):
        for conn in self.connections:
            if conn.isVisible():
                conn.update_path()

    def _clear_scene(self) -> None:
        for conn in self.connections:
            conn.animation_timer.stop()
        self.scene.clear()
        self.nodes.clear()
        self.connections.clear()
        self._active_connections.clear()

    def _fit_view_with_padding(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if not rect.isValid(): return
        padding = 50
        rect.adjust(-padding, -padding, padding, padding)
        self.view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)

    def _find_node_by_path(self, target_path: str) -> Optional[ProjectNode]:
        norm_target_path = _normalize_path_key(target_path)
        node = self.nodes.get(norm_target_path)
        if node and node.node_type in ["file", "folder"]:
            return node

        for node in self.nodes.values():
            if _normalize_path_key(node.path) == norm_target_path and node.node_type in ["file", "folder"]:
                return node
        return None

    def _handle_agent_activity(self, agent_name: str, target_file_path: str):
        self.log("info", f"Visualizing activity for Agent: {agent_name} on file: {Path(target_file_path).name}")
        self._deactivate_all_connections()

        target_node = self._find_node_by_path(target_file_path)
        if not target_node:
            self.log("warning", f"Could not find a node for target path: {target_file_path}")
            return

        needs_relayout = False
        path_nodes = []
        current = target_node
        while current:
            path_nodes.insert(0, current)
            if not current.is_expanded and current.child_nodes:
                current.is_expanded = True
                self._set_children_visibility(current, True)
                needs_relayout = True
            current = current.parent_node

        if needs_relayout:
            self._relayout_and_animate()

        agent_colors = {
            "architect": Colors.AGENT_ARCHITECT_COLOR,
            "coder": Colors.AGENT_CODER_COLOR,
            "rewriter": Colors.ACCENT_GREEN,
            "healer": Colors.ACCENT_RED,
        }
        color = agent_colors.get(agent_name.lower(), Colors.ACCENT_BLUE)

        for node in path_nodes:
            if node.incoming_connection:
                node.incoming_connection.activate(color)
                self._active_connections.append(node.incoming_connection)

    def _deactivate_all_connections(self, *args, **kwargs):
        self.log("info", "Deactivating all visualizer connections.")
        for conn in self._active_connections:
            conn.deactivate()
        self._active_connections.clear()

    def show(self) -> None:
        super().show()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()

    def log(self, level: str, message: str):
        self.event_bus.emit("log_message_received", "ProjectVisualizer", level, message)