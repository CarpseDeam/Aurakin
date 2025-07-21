# src/ava/core/managers/window_manager.py
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.ava.gui.main_window import MainWindow
from src.ava.gui.code_viewer import CodeViewerWindow
from src.ava.gui.model_config_dialog import ModelConfigurationDialog
from src.ava.gui.plugin_management_dialog import PluginManagementDialog
from src.ava.gui.log_viewer import LogViewerWindow
from src.ava.gui.node_viewer.project_visualizer_window import ProjectVisualizerWindow

from src.ava.core.event_bus import EventBus
from src.ava.core.llm_client import LLMClient
from src.ava.core.project_manager import ProjectManager
from src.ava.core.app_state import AppState

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager

logger = logging.getLogger(__name__)


class WindowManager:
    """
    Creates and manages all GUI windows.
    Single responsibility: Window lifecycle and access management.
    """

    def __init__(self, event_bus: EventBus, project_manager: ProjectManager) -> None:
        """
        Initializes the WindowManager.

        Args:
            event_bus: The application's central event bus.
            project_manager: The manager for the active project.
        """
        self.event_bus = event_bus
        self.project_manager = project_manager

        # Main windows
        self.main_window: Optional[MainWindow] = None
        self.code_viewer: Optional[CodeViewerWindow] = None
        self.log_viewer: Optional[LogViewerWindow] = None
        self.project_visualizer: Optional[ProjectVisualizerWindow] = None

        # Dialogs
        self.model_config_dialog: Optional[ModelConfigurationDialog] = None
        self.plugin_management_dialog: Optional[PluginManagementDialog] = None

        logger.info("Initialized")

    def initialize_windows(self, llm_client: LLMClient, service_manager: "ServiceManager", project_root: Path) -> None:
        """
        Initialize all GUI windows.

        Args:
            llm_client: The client for interacting with LLMs.
            service_manager: The manager for all application services.
            project_root: The root directory of the application's source.
        """
        logger.info("Initializing windows...")

        # --- Get necessary services ---
        lsp_client_service = service_manager.get_lsp_client_service()
        plugin_manager = service_manager.get_plugin_manager()

        # --- Create main windows ---
        self.main_window = MainWindow(self.event_bus, project_root)
        self.code_viewer = CodeViewerWindow(self.event_bus, self.project_manager, lsp_client_service)
        self.log_viewer = LogViewerWindow(self.event_bus)
        self.project_visualizer = ProjectVisualizerWindow(self.event_bus, self.project_manager)

        # --- Create dialogs ---
        self.model_config_dialog = ModelConfigurationDialog(llm_client, self.main_window)
        self.plugin_management_dialog = PluginManagementDialog(plugin_manager, self.event_bus, self.main_window)

        logger.info("Windows initialized")

    def handle_app_state_change(self, new_state: AppState, project_name: Optional[str]) -> None:
        """
        Listens for global state changes and updates all relevant UI components.
        This is the central point for UI reaction to state changes.

        Args:
            new_state: The new application state (BOOTSTRAP or MODIFY).
            project_name: The name of the active project, if any.
        """
        self.update_project_display(project_name or "(none)")

        if new_state == AppState.MODIFY:
            if self.project_manager and self.project_manager.active_project_path:
                self.load_project_in_code_viewer(str(self.project_manager.active_project_path))
        else:  # BOOTSTRAP state
            self.prepare_code_viewer_for_new_project()

    # --- Window Getters ---
    def get_main_window(self) -> MainWindow:
        """
        Returns the MainWindow instance.

        Returns:
            The MainWindow instance.
        """
        return self.main_window

    def get_code_viewer(self) -> CodeViewerWindow:
        """
        Returns the CodeViewerWindow instance.

        Returns:
            The CodeViewerWindow instance.
        """
        return self.code_viewer

    def get_log_viewer(self) -> LogViewerWindow:
        """
        Returns the LogViewerWindow instance.

        Returns:
            The LogViewerWindow instance.
        """
        return self.log_viewer

    def get_project_visualizer(self) -> ProjectVisualizerWindow:
        """
        Returns the ProjectVisualizerWindow instance.

        Returns:
            The ProjectVisualizerWindow instance.
        """
        return self.project_visualizer

    def get_model_config_dialog(self) -> ModelConfigurationDialog:
        """
        Returns the ModelConfigurationDialog instance.

        Returns:
            The ModelConfigurationDialog instance.
        """
        return self.model_config_dialog

    def get_plugin_management_dialog(self) -> PluginManagementDialog:
        """
        Returns the PluginManagementDialog instance.

        Returns:
            The PluginManagementDialog instance.
        """
        return self.plugin_management_dialog

    # --- Show Window Methods ---
    def show_main_window(self) -> None:
        """Shows the main application window."""
        if self.main_window: self.main_window.show()

    def show_code_viewer(self) -> None:
        """Shows the code viewer window."""
        if self.code_viewer: self.code_viewer.show_window()

    def show_log_viewer(self) -> None:
        """Shows the log viewer window."""
        if self.log_viewer: self.log_viewer.show()

    def show_project_visualizer(self) -> None:
        """Shows the project visualizer window."""
        if self.project_visualizer:
            self.project_visualizer.show()

    async def show_model_config_dialog(self) -> None:
        """Asynchronously populates model data and then shows the dialog."""
        if self.model_config_dialog:
            if self.model_config_dialog.isVisible():
                self.model_config_dialog.activateWindow()
                self.model_config_dialog.raise_()
                return

            await self.model_config_dialog.populate_models_async()
            self.model_config_dialog.populate_settings()
            self.model_config_dialog.show()

    def show_plugin_management_dialog(self) -> None:
        """Shows the plugin management dialog."""
        if self.plugin_management_dialog: self.plugin_management_dialog.exec()

    # --- UI Update Methods ---
    def update_project_display(self, project_name: str) -> None:
        """
        Updates the project name display in the sidebar.

        Args:
            project_name: The name of the project to display.
        """
        if self.main_window and hasattr(self.main_window, 'sidebar'):
            self.main_window.sidebar.update_project_display(project_name)

    def prepare_code_viewer_for_new_project(self) -> None:
        """Prepares the code viewer for a new project session."""
        if self.code_viewer: self.code_viewer.prepare_for_new_project_session()

    def load_project_in_code_viewer(self, project_path: str) -> None:
        """
        Loads a project into the code viewer's file tree.

        Args:
            project_path: The path to the project to load.
        """
        if self.code_viewer:
            self.code_viewer.load_project(project_path)

    def is_fully_initialized(self) -> bool:
        """
        Check if all windows are initialized.

        Returns:
            True if all windows have been created, False otherwise.
        """
        return all([
            self.main_window,
            self.code_viewer,
            self.log_viewer,
            self.model_config_dialog,
            self.plugin_management_dialog,
            self.project_visualizer
        ])