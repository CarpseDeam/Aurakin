# src/ava/gui/project_visualizer_window.py

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QEasingCurve,
    QPropertyAnimation,
    QSequentialAnimationGroup, QTimer, QParallelAnimationGroup,
)
from PySide6.QtGui import QColor, QPainter, QPen, QCloseEvent, QPainterPath
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from src.ava.core.event_bus import EventBus
from src.ava.core.project_manager import ProjectManager
from src.ava.gui.components import Colors
from src.ava.gui.drone_item import DroneItem
from src.ava.gui.project_node import ProjectNode, NODE_WIDTH, NODE_HEIGHT

logger = logging.getLogger(__name__)

# Layout Constants
COLUMN_WIDTH = NODE_WIDTH + 100
ROW_HEIGHT = NODE_HEIGHT + 25
ORBIT_RADIUS = NODE_WIDTH * 0.4
AI_CORE_OFFSET = -COLUMN_WIDTH * 1.5  # Increased offset for more space


class AICoreNode(QGraphicsObject):
    """A special node representing the central AI core."""
    def __init__(self) -> None:
        """Initializes the AICoreNode."""
        super().__init__()
        self.outgoing_connections: List[ConnectionItem] = []

    def boundingRect(self) -> QRectF:
        """
        Defines the outer bounding rectangle of the node.

        Returns:
            A QRectF representing the node's boundaries.
        """
        return QRectF(-30, -30, 60, 60)

    def add_connection(self, connection: 'ConnectionItem', is_outgoing: bool) -> None:
        """
        Registers an outgoing connection with this node.

        The signature now matches the call in _draw_connection, accepting
        the 'is_outgoing' argument even though it's always True for the AI Core.

        Args:
            connection: The connection item to register.
            is_outgoing: Must be True for AICoreNode.
        """
        if is_outgoing:
            self.outgoing_connections.append(connection)

    def paint(self, painter: QPainter, option, widget) -> None:
        """
        Paints the contents of the node.

        Args:
            painter: The QPainter instance to use for drawing.
            option: Provides style options for the item.
            widget: The widget that is being painted on, if any.
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(Colors.ACCENT_PURPLE), 2))
        painter.setBrush(QColor(Colors.ELEVATED_BG))
        painter.drawEllipse(self.boundingRect())
        painter.setPen(QColor(Colors.ACCENT_PURPLE))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(20)
        painter.setFont(font)
        painter.drawText(self.boundingRect(), Qt.AlignmentFlag.AlignCenter, "A")


class ConnectionItem(QGraphicsPathItem):
    """A QGraphicsPathItem that draws a cubic Bezier curve between two nodes."""
    def __init__(self, start_node: QGraphicsObject, end_node: QGraphicsObject, is_ai_link: bool = False) -> None:
        """
        Initializes the ConnectionItem.

        Args:
            start_node: The node where the connection originates.
            end_node: The node where the connection terminates.
            is_ai_link: True if this is a special link from the AI Core.
        """
        super().__init__()
        self.start_node = start_node
        self.end_node = end_node
        self.is_ai_link = is_ai_link
        self.setZValue(-1)
        self.update_path()

    def update_path(self) -> None:
        """Recalculates and redraws the Bezier curve based on node positions."""
        start_rect = self.start_node.sceneBoundingRect()
        end_rect = self.end_node.sceneBoundingRect()

        start_point = QPointF(start_rect.right(), start_rect.center().y())
        if isinstance(self.start_node, AICoreNode):
            start_point = start_rect.center()

        end_point = QPointF(end_rect.left(), end_rect.center().y())

        path = QPainterPath(start_point)
        path.cubicTo(start_point.x() + 50, start_point.y(), end_point.x() - 50, end_point.y(), end_point.x(),
                     end_point.y())

        pen_color = Colors.ACCENT_PURPLE if self.is_ai_link else Colors.BORDER_DEFAULT
        pen_width = 2 if self.is_ai_link else 1.5
        pen_style = Qt.PenStyle.DashLine if self.is_ai_link else Qt.PenStyle.SolidLine
        self.setPen(QPen(QColor(pen_color), pen_width, pen_style))
        self.setPath(path)


class ProjectVisualizerWindow(QMainWindow):
    """A window for visualizing the project structure and AI activity."""
    def __init__(
            self,
            event_bus: EventBus,
            project_manager: ProjectManager,
            parent: Optional[QWidget] = None,
    ) -> None:
        """
        Initializes the ProjectVisualizerWindow.

        Args:
            event_bus: The application's central event bus.
            project_manager: The manager for the active project.
            parent: The parent widget, if any.
        """
        super().__init__(parent)
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.nodes: Dict[str, ProjectNode] = {}
        self.active_drones: Dict[str, DroneItem] = {}
        self.animation_groups: Dict[str, QSequentialAnimationGroup] = {}
        self._setup_ui()
        self._connect_events()

    def _setup_ui(self) -> None:
        """Initializes the user interface."""
        self.setWindowTitle("Project Visualizer (Protoss Carrier)")
        self.setGeometry(150, 150, 1200, 800)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scene = QGraphicsScene(self)
        self.scene.setBackgroundBrush(QColor(Colors.PRIMARY_BG))
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        layout.addWidget(self.view)
        self.ai_core = AICoreNode()
        self.scene.addItem(self.ai_core)

    def _connect_events(self) -> None:
        """Subscribes to relevant events from the event bus."""
        self.event_bus.subscribe("project_root_selected", self._load_graph_from_disk)
        self.event_bus.subscribe("project_plan_generated", self._handle_project_plan_generated)
        self.event_bus.subscribe("coordinated_generation_progress", self._handle_drone_request)
        self.event_bus.subscribe("ai_workflow_finished", self._recall_all_drones)

    def _clear_scene(self) -> None:
        """Clears all items from the graphics scene and resets state."""
        for anim in self.animation_groups.values():
            anim.stop()
        self.scene.clear()
        self.nodes.clear()
        self.active_drones.clear()
        self.animation_groups.clear()
        self.ai_core = AICoreNode()
        self.scene.addItem(self.ai_core)
        logger.info("Project visualizer scene cleared.")

    def _handle_project_plan_generated(self, plan: Dict) -> None:
        """
        Handles the generation of a new project plan by building an animated graph.

        Args:
            plan: The project plan dictionary from the ArchitectService.
        """
        self._clear_scene()
        if not self.project_manager.active_project_path: return

        planned_filenames = {task['filename'] for task in plan.get("tasks", [])}
        existing_filenames = set(self.project_manager.get_project_files().keys())
        all_filenames = list(planned_filenames.union(existing_filenames))

        tree = self._build_tree_from_paths(all_filenames)
        positions = self._calculate_node_positions(tree, self.project_manager.active_project_path)

        root_path = str(self.project_manager.active_project_path)
        root_node = ProjectNode(self.project_manager.active_project_path.name, root_path, True)
        root_node.setPos(positions[root_path])
        self.nodes[root_path] = root_node
        self.scene.addItem(root_node)

        self.ai_core.setPos(AI_CORE_OFFSET, positions[root_path].y())
        self._draw_connection(self.ai_core, root_node, is_ai_link=True)

        build_animation = QSequentialAnimationGroup()
        self._animate_graph_build(tree, self.project_manager.active_project_path, root_node, positions, build_animation)

        build_animation.finished.connect(lambda: QTimer.singleShot(50, lambda: self.view.fitInView(
            self.scene.itemsBoundingRect().adjusted(-150, -50, 100, 50),
            Qt.AspectRatioMode.KeepAspectRatio)))
        build_animation.start()

    def _load_graph_from_disk(self, project_path_str: str) -> None:
        """
        Loads the project structure from disk and displays it statically.

        Args:
            project_path_str: The string path to the project root.
        """
        self._clear_scene()
        if not project_path_str: return

        project_path = Path(project_path_str)
        all_files = self.project_manager.get_project_files()
        tree = self._build_tree_from_paths(list(all_files.keys()))
        positions = self._calculate_node_positions(tree, project_path)

        for path_str, pos in positions.items():
            path_obj = Path(path_str)
            is_folder = path_obj.is_dir() or any(p.startswith(path_str + '/') for p in all_files.keys())
            node = ProjectNode(path_obj.name, path_str, is_folder)
            self.nodes[path_str] = node
            self.scene.addItem(node)
            node.setPos(pos)

        for path_str, node in self.nodes.items():
            parent_path = str(Path(path_str).parent)
            if parent_path in self.nodes:
                self._draw_connection(self.nodes[parent_path], node)

        self._draw_connection(self.ai_core, self.nodes[str(project_path)], is_ai_link=True)

        QTimer.singleShot(50, lambda: self.view.fitInView(
            self.scene.itemsBoundingRect().adjusted(-150, -50, 100, 50),
            Qt.AspectRatioMode.KeepAspectRatio))

    def _build_tree_from_paths(self, paths: List[str]) -> Dict:
        """
        Builds a nested dictionary representing the file tree from a flat list of paths.

        Args:
            paths: A list of relative file path strings.

        Returns:
            A dictionary representing the file tree structure.
        """
        tree = {}
        for rel_path_str in paths:
            parts = Path(rel_path_str).parts
            if not parts: continue
            current_level = tree
            for part in parts:
                if part not in current_level: current_level[part] = {}
                current_level = current_level[part]
        return tree

    def _calculate_node_positions(self, tree: Dict, root_path: Path) -> Dict[str, QPointF]:
        """
        Calculates the layout positions for all nodes in the tree.

        Args:
            tree: The file tree dictionary.
            root_path: The Path object for the project root.

        Returns:
            A dictionary mapping file path strings to their calculated QPointF positions.
        """
        positions = {}
        column_counts = {}
        y_positions = {}

        self._calculate_column_counts(tree, 1, column_counts)
        for col, count in column_counts.items():
            total_height = count * ROW_HEIGHT
            y_positions[col] = -total_height / 2 + ROW_HEIGHT / 2

        root_y_center = 0
        if 1 in column_counts and column_counts[1] > 0:
            total_first_col_height = column_counts[1] * ROW_HEIGHT
            root_y_center = y_positions[1] + (total_first_col_height / 2) - (ROW_HEIGHT / 2)

        positions[str(root_path)] = QPointF(0, root_y_center)
        self._calculate_positions_recursively(tree, root_path, 1, y_positions, positions)
        return positions

    def _calculate_column_counts(self, tree: Dict, column: int, counts: Dict[int, int]) -> None:
        """Recursively counts the number of nodes in each column of the tree."""
        counts[column] = counts.get(column, 0) + len(tree)
        for _, children in tree.items():
            if children:
                self._calculate_column_counts(children, column + 1, counts)

    def _calculate_positions_recursively(self, tree: Dict, current_path: Path, column: int, y_pos_map: Dict,
                                         positions: Dict) -> None:
        """Recursively calculates the final X, Y position for each node."""
        sorted_items = sorted(tree.items(), key=lambda item: not bool(item[1]))
        for name, children in sorted_items:
            item_path = current_path / name
            y_pos = y_pos_map.get(column, 0)
            positions[str(item_path)] = QPointF(column * COLUMN_WIDTH, y_pos)
            y_pos_map[column] = y_pos + ROW_HEIGHT
            if children:
                self._calculate_positions_recursively(children, item_path, column + 1, y_pos_map, positions)

    def _animate_graph_build(self, tree: Dict, current_path: Path, parent_node: ProjectNode, positions: Dict,
                             anim_group: QSequentialAnimationGroup) -> None:
        """
        Recursively builds the animation for creating and positioning nodes level by level.

        Args:
            tree: The current subtree to process.
            current_path: The path corresponding to the current level of the tree.
            parent_node: The parent node from which the new nodes will animate.
            positions: The dictionary of final node positions.
            anim_group: The main sequential animation group to add level animations to.
        """
        sorted_items = sorted(tree.items(), key=lambda item: not bool(item[1]))
        level_anims = QParallelAnimationGroup()
        for name, children in sorted_items:
            item_path_obj = current_path / name
            item_path_str = str(item_path_obj)
            is_folder = bool(children)

            node = ProjectNode(name, item_path_str, is_folder)
            self.nodes[item_path_str] = node
            self.scene.addItem(node)
            node.setOpacity(0)
            node.setPos(parent_node.pos())

            fade_in = QPropertyAnimation(node, b"opacity")
            fade_in.setDuration(300)
            fade_in.setStartValue(0)
            fade_in.setEndValue(1)

            move_anim = QPropertyAnimation(node, b"pos")
            move_anim.setDuration(500)
            move_anim.setEndValue(positions[item_path_str])
            move_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            node_anim_group = QParallelAnimationGroup()
            node_anim_group.addAnimation(fade_in)
            node_anim_group.addAnimation(move_anim)

            connection = self._draw_connection(parent_node, node)
            connection.setVisible(False)
            node_anim_group.finished.connect(lambda c=connection: c.setVisible(True))

            level_anims.addAnimation(node_anim_group)

            if is_folder:
                self._animate_graph_build(children, item_path_obj, node, positions, anim_group)

        if level_anims.animationCount() > 0:
            anim_group.addAnimation(level_anims)

    def _draw_connection(self, start_node: QGraphicsObject, end_node: QGraphicsObject,
                         is_ai_link: bool = False) -> ConnectionItem:
        """
        Creates a ConnectionItem between two nodes and registers it with them.

        Args:
            start_node: The node where the connection originates.
            end_node: The node where the connection terminates.
            is_ai_link: True if this is a special link from the AI Core.

        Returns:
            The created ConnectionItem.
        """
        connection = ConnectionItem(start_node, end_node, is_ai_link)
        self.scene.addItem(connection)

        if isinstance(start_node, (ProjectNode, AICoreNode)):
            start_node.add_connection(connection, is_outgoing=True)
        if isinstance(end_node, ProjectNode):
            end_node.add_connection(connection, is_outgoing=False)
        return connection

    def _construct_drone_path(self, target_node: ProjectNode) -> QPainterPath:
        """
        Constructs a flight path for a drone from the AI Core to a target node.

        The path traverses the project hierarchy from the root to the target.

        Args:
            target_node: The destination ProjectNode for the drone.

        Returns:
            A QPainterPath representing the flight trajectory.
        """
        path_nodes = []
        curr = target_node
        while curr:
            path_nodes.append(curr)
            parent_path_str = str(Path(curr.path).parent)
            curr = self.nodes.get(parent_path_str)
        path_nodes.reverse()

        path = QPainterPath(self.ai_core.pos())
        for node in path_nodes:
            end_point = node.sceneBoundingRect().center()
            path.lineTo(end_point)

        final_approach_point = target_node.sceneBoundingRect().center() - QPointF(0, ORBIT_RADIUS)
        path.lineTo(final_approach_point)
        return path

    def _handle_drone_request(self, progress_data: Dict) -> None:
        """
        Handles an event indicating AI progress on a file, launching a drone if needed.

        Args:
            progress_data: A dictionary containing the filename being worked on.
        """
        filename = progress_data.get("filename")
        if not filename or not self.project_manager.active_project_path: return
        target_path = str(self.project_manager.active_project_path / filename)
        if target_path in self.nodes and target_path not in self.active_drones:
            self.launch_drone(target_path)

    def launch_drone(self, target_node_path: str) -> None:
        """
        Launches a drone and animates its flight to and orbit around a target node.

        Args:
            target_node_path: The string path of the target node.
        """
        target_node = self.nodes.get(target_node_path)
        if not target_node: return

        drone = DroneItem()
        self.scene.addItem(drone)
        drone.setPos(self.ai_core.pos())
        self.active_drones[target_node_path] = drone
        target_node.set_active(True)

        flight_path = self._construct_drone_path(target_node)
        drone.set_follow_path(flight_path)

        fly_anim = QPropertyAnimation(drone, b"pathProgress")
        fly_anim.setDuration(int(flight_path.length() * 2.5))
        fly_anim.setStartValue(0.0)
        fly_anim.setEndValue(1.0)
        fly_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        orbit_anim = QPropertyAnimation(drone, b"orbitAngle")
        orbit_anim.setDuration(4000)
        orbit_anim.setStartValue(-90)
        orbit_anim.setEndValue(270)
        orbit_anim.setLoopCount(-1)

        anim_group = QSequentialAnimationGroup()
        anim_group.addAnimation(fly_anim)
        anim_group.addAnimation(orbit_anim)
        fly_anim.finished.connect(
            lambda: drone.set_orbit_parameters(target_node.sceneBoundingRect().center(), ORBIT_RADIUS))
        self.animation_groups[target_node_path] = anim_group
        anim_group.start()

    def _recall_all_drones(self) -> None:
        """Recalls all active drones, animating their return to the AI Core."""
        for path, drone in list(self.active_drones.items()):
            if path in self.animation_groups: self.animation_groups[path].stop()
            node = self.nodes.get(path)
            if node: node.set_active(False)

            fly_back_anim = QPropertyAnimation(drone, b"pos")
            fly_back_anim.setDuration(800)
            fly_back_anim.setStartValue(drone.pos())
            fly_back_anim.setEndValue(self.ai_core.pos())
            fly_back_anim.setEasingCurve(QEasingCurve.Type.InCubic)
            fly_back_anim.finished.connect(lambda d=drone: self.scene.removeItem(d) if d.scene() else None)
            fly_back_anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        self.active_drones.clear()
        self.animation_groups.clear()

    def show(self) -> None:
        """Shows the window and loads the initial project graph if available."""
        super().show()
        if self.project_manager and self.project_manager.active_project_path:
            self._load_graph_from_disk(str(self.project_manager.active_project_path))
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Overrides the close event to hide the window instead of closing it.

        Args:
            event: The close event.
        """
        self.hide()
        event.ignore()