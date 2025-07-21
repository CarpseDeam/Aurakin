# src/ava/gui/project_visualizer_window.py

import logging
import math
import random
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import (
    QPointF,
    QRectF,
    QTimer,
    Qt,
    QEasingCurve,
    QPropertyAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPen, QCloseEvent
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
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
from src.ava.gui.project_node import ProjectNode

logger = logging.getLogger(__name__)


class ProjectVisualizerWindow(QMainWindow):
    """
    The main window for the project visualizer.

    This window displays a dynamic, force-directed graph of the files and folders
    in the currently active project. It also visualizes AI agent activity
    by animating 'drones' that travel between the nodes of the graph.
    """

    def __init__(
        self,
        event_bus: EventBus,
        project_manager: ProjectManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        """
        Initializes the ProjectVisualizerWindow.

        Args:
            event_bus: The application's central event bus for communication.
            project_manager: The manager for the active project's data.
            parent: The parent widget, if any.
        """
        super().__init__(parent)
        self.event_bus = event_bus
        self.project_manager = project_manager

        self.nodes: Dict[str, ProjectNode] = {}
        self.connections: List[QGraphicsLineItem] = []
        self.active_drones: List[DroneItem] = []

        self.physics_timer = QTimer(self)
        self.physics_timer.setInterval(16)  # ~60 FPS
        self.physics_timer.timeout.connect(self._update_layout_physics)

        self._setup_ui()
        self._connect_events()

        # For demonstration purposes, launch a drone periodically
        self.demo_drone_timer = QTimer(self)
        self.demo_drone_timer.setInterval(5000)  # Every 5 seconds
        self.demo_drone_timer.timeout.connect(self._launch_demo_drone)

    def _setup_ui(self) -> None:
        """
        Initializes the user interface, setting up the graphics scene and view.
        """
        self.setWindowTitle("Project Visualizer")
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
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        layout.addWidget(self.view)

    def _connect_events(self) -> None:
        """
        Subscribes to relevant events on the application's event bus.
        """
        self.event_bus.subscribe("project_root_selected", self._handle_project_load)
        # Placeholder for a future event to trigger drone animations
        # self.event_bus.subscribe("visualizer_drone_request", self.launch_drone)

    def _handle_project_load(self, project_path_str: str) -> None:
        """
        Callback for when a new project is loaded. Clears the old visualization
        and builds a new one for the specified project.

        Args:
            project_path_str: The string path to the root of the loaded project.
        """
        logger.info(f"Visualizer received project load event for: {project_path_str}")
        self._clear_scene()
        if project_path_str:
            project_path = Path(project_path_str)
            self._populate_scene(project_path)
            self.demo_drone_timer.start()

    def _clear_scene(self) -> None:
        """
        Resets the visualizer to a clean state, removing all nodes, connections,
        and drones. Stops any running timers.
        """
        self.physics_timer.stop()
        self.demo_drone_timer.stop()
        self.scene.clear()
        self.nodes.clear()
        self.connections.clear()
        self.active_drones.clear()
        logger.info("Project visualizer scene cleared.")

    def _populate_scene(self, project_path: Path) -> None:
        """
        Builds the visual graph for a given project path.

        Args:
            project_path: The root path of the project to visualize.
        """
        file_structure = self.project_manager.get_project_files()
        if not file_structure:
            logger.warning("Cannot populate visualizer: No files found in project.")
            return

        # Create a hierarchical dictionary from the flat file list
        tree = {}
        for rel_path_str in file_structure.keys():
            parts = Path(rel_path_str).parts
            current_level = tree
            for part in parts:
                if part not in current_level:
                    current_level[part] = {}
                current_level = current_level[part]

        # Create the root node for the project itself
        root_node = ProjectNode(project_path.name, str(project_path), is_folder=True)
        self.nodes[str(project_path)] = root_node
        self.scene.addItem(root_node)

        # Recursively create nodes and connections
        self._create_nodes_recursively(tree, project_path, root_node)

        self.view.centerOn(root_node)
        self.physics_timer.start()

    def _create_nodes_recursively(
        self, tree: Dict, current_path: Path, parent_node: ProjectNode
    ) -> None:
        """
        Recursively traverses the project structure to create and connect nodes.

        Args:
            tree: The hierarchical dictionary representing the project structure.
            current_path: The file system path of the current level in the tree.
            parent_node: The parent ProjectNode to connect children to.
        """
        for name, children in tree.items():
            item_path = current_path / name
            is_folder = bool(children)

            node = ProjectNode(name, str(item_path), is_folder)
            self.nodes[str(item_path)] = node
            self.scene.addItem(node)

            # Position new nodes near their parent initially
            offset = QPointF(
                (random.random() - 0.5) * 50, (random.random() - 0.5) * 50
            )
            node.setPos(parent_node.pos() + offset)

            # Create a visual connection
            connection = QGraphicsLineItem(
                parent_node.pos().x(),
                parent_node.pos().y(),
                node.pos().x(),
                node.pos().y(),
            )
            connection.setPen(QPen(QColor(Colors.BORDER_DEFAULT), 1))
            connection.setZValue(-1)  # Draw behind nodes
            self.scene.addItem(connection)
            self.connections.append(connection)
            # Store references to nodes on the line item for easy updates
            connection.setProperty("start_node", parent_node)
            connection.setProperty("end_node", node)

            if is_folder:
                self._create_nodes_recursively(children, item_path, node)

    def _update_layout_physics(self) -> None:
        """
        Executes one step of the force-directed layout simulation.
        This method is called repeatedly by the physics_timer.
        """
        if not self.nodes:
            return

        k_attract = 0.02
        k_repel = 1500.0
        ideal_length = 120.0
        damping = 0.95

        forces: Dict[str, QPointF] = {path: QPointF(0, 0) for path in self.nodes}

        # Calculate repulsive forces between all pairs of nodes
        node_list = list(self.nodes.values())
        for i in range(len(node_list)):
            for j in range(i + 1, len(node_list)):
                node_a = node_list[i]
                node_b = node_list[j]
                delta = node_a.pos() - node_b.pos()
                distance = math.hypot(delta.x(), delta.y()) + 0.1  # Avoid division by zero
                repulsive_force = k_repel / (distance * distance)
                force_vector = (delta / distance) * repulsive_force
                forces[node_a.path] += force_vector
                forces[node_b.path] -= force_vector

        # Calculate attractive forces (springs) along connections
        for conn in self.connections:
            node_a = conn.property("start_node")
            node_b = conn.property("end_node")
            delta = node_a.pos() - node_b.pos()
            distance = math.hypot(delta.x(), delta.y()) + 0.1
            attractive_force = k_attract * (distance - ideal_length)
            force_vector = (delta / distance) * attractive_force
            forces[node_a.path] -= force_vector
            forces[node_b.path] += force_vector

        # Apply forces to update node positions
        for path, node in self.nodes.items():
            velocity = (node.velocity + forces[path]) * damping
            node.setPos(node.pos() + velocity)
            node.velocity = velocity

        # Update connection lines to follow nodes
        for conn in self.connections:
            start_node = conn.property("start_node")
            end_node = conn.property("end_node")
            conn.setLine(
                start_node.pos().x(),
                start_node.pos().y(),
                end_node.pos().x(),
                end_node.pos().y(),
            )

    def launch_drone(self, start_node_path: str, end_node_path: str) -> None:
        """
        Creates and animates a drone to fly between two nodes in the graph.

        Args:
            start_node_path: The string path of the starting node.
            end_node_path: The string path of the destination node.
        """
        start_node = self.nodes.get(start_node_path)
        end_node = self.nodes.get(end_node_path)

        if not start_node or not end_node:
            logger.warning(
                f"Cannot launch drone: Node not found. "
                f"Start: '{start_node_path}', End: '{end_node_path}'"
            )
            return

        drone = DroneItem()
        self.scene.addItem(drone)
        drone.setPos(start_node.pos())
        self.active_drones.append(drone)

        animation = QPropertyAnimation(drone, b"pos")
        animation.setEndValue(end_node.pos())
        animation.setDuration(2000)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def on_animation_finished():
            if drone in self.active_drones:
                self.active_drones.remove(drone)
            if drone.scene():
                self.scene.removeItem(drone)

        animation.finished.connect(on_animation_finished)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _launch_demo_drone(self) -> None:
        """
        Launches a drone between two random nodes for demonstration purposes.
        """
        if len(self.nodes) < 2:
            return

        node_paths = list(self.nodes.keys())
        start_path, end_path = random.sample(node_paths, 2)
        self.launch_drone(start_path, end_path)
        logger.info(f"Launched demo drone from {start_path} to {end_path}")

    def show(self) -> None:
        """
        Shows the window and ensures the visualization is up-to-date.
        """
        super().show()
        if self.project_manager and self.project_manager.active_project_path:
            self._handle_project_load(str(self.project_manager.active_project_path))
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Handles the window close event to stop background timers.

        Args:
            event: The close event.
        """
        logger.info("Closing Project Visualizer. Stopping timers.")
        self.physics_timer.stop()
        self.demo_drone_timer.stop()
        super().closeEvent(event)