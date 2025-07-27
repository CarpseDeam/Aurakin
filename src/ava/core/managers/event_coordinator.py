# src/ava/core/managers/event_coordinator.py
import asyncio
import logging
from typing import TYPE_CHECKING, Any
from src.ava.core.event_bus import EventBus

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager
    from src.ava.core.managers.window_manager import WindowManager
    from src.ava.core.managers.task_manager import TaskManager
    from src.ava.core.managers.workflow_manager import WorkflowManager

logger = logging.getLogger(__name__)


class EventCoordinator:
    """
    Coordinates events between different components of the application.
    Single responsibility: Event routing and component integration.
    """

    def __init__(self, event_bus: EventBus):
        """
        Initializes the EventCoordinator.

        Args:
            event_bus: The application's central event bus.
        """
        self.event_bus = event_bus
        self.service_manager: "ServiceManager" = None
        self.window_manager: "WindowManager" = None
        self.task_manager: "TaskManager" = None
        self.workflow_manager: "WorkflowManager" = None
        logger.info("Initialized")

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager",
                     task_manager: "TaskManager",
                     workflow_manager: "WorkflowManager") -> None:
        """
        Set references to other managers.

        Args:
            service_manager: The application's service manager.
            window_manager: The application's window manager.
            task_manager: The application's task manager.
            workflow_manager: The application's workflow manager.
        """
        self.service_manager = service_manager
        self.window_manager = window_manager
        self.task_manager = task_manager
        self.workflow_manager = workflow_manager

        # Pass managers to the action service now that they are all available
        action_service = self.service_manager.get_action_service()
        if action_service:
            action_service.window_manager = self.window_manager
            action_service.task_manager = self.task_manager

    def wire_all_events(self) -> None:
        """Wire all events between components."""
        logger.info("Wiring all events...")
        self._wire_ui_events()
        self._wire_ai_workflow_events()
        self._wire_plugin_events()
        self._wire_chat_session_events()
        self._wire_status_bar_events()
        self._wire_lsp_events()
        self._wire_visualizer_events()
        self._wire_test_lab_events()
        self._wire_executor_events()

        # Allows plugins to request core manager instances for advanced operations.
        self.event_bus.subscribe(
            "plugin_requesting_managers",
            lambda callback: callback(self.service_manager, self.task_manager, self.workflow_manager)
        )

        logger.info("All events wired successfully.")

    def _wire_executor_events(self) -> None:
        """Wire events for the command execution engine and its log viewer."""
        if not self.window_manager:
            return
        code_viewer = self.window_manager.get_code_viewer()
        if not code_viewer or not hasattr(code_viewer, 'executor_log_panel'):
            logger.warning("ExecutorLogPanel not available for event wiring.")
            return

        executor_panel = code_viewer.executor_log_panel
        # --- THIS IS THE FIX ---
        # Decouple clearing from running. Any part of the app can now request a clear.
        self.event_bus.subscribe("clear_executor_log", executor_panel.clear_output)
        # The old event still clears the log for backward compatibility with fire-and-forget buttons
        self.event_bus.subscribe("execute_command_requested", lambda command: executor_panel.clear_output())
        # --- END OF FIX ---
        self.event_bus.subscribe("terminal_output_received", executor_panel.append_output)
        logger.info("Executor events wired.")

    def _wire_test_lab_events(self) -> None:
        """Wire events for the Test Lab feature."""
        if not self.window_manager:
            return
        code_viewer = self.window_manager.get_code_viewer()
        if not code_viewer or not hasattr(code_viewer, 'file_tree_manager'):
            logger.warning("FileTreeManager not available for Test Lab event wiring.")
            return

        self.event_bus.subscribe("test_file_generated",
                                 lambda path: code_viewer.file_tree_manager.refresh_tree_from_disk())
        logger.info("Test Lab events wired.")

    def _wire_visualizer_events(self) -> None:
        """Wire events for the real-time project visualizer."""
        if not self.window_manager:
            return
        visualizer = self.window_manager.get_project_visualizer()
        if not visualizer:
            logger.warning("ProjectVisualizer not available for event wiring.")
            return

        self.event_bus.subscribe("project_scaffold_generated", visualizer.display_scaffold)
        self.event_bus.subscribe("project_root_selected", visualizer.display_existing_project)
        self.event_bus.subscribe("workflow_finalized", lambda final_code: visualizer.display_existing_project(
            self.service_manager.project_manager.active_project_path))
        self.event_bus.subscribe("agent_activity_started", visualizer._handle_agent_activity)
        self.event_bus.subscribe("ai_workflow_finished", visualizer._deactivate_all_connections)
        self.event_bus.subscribe("test_file_generated", lambda path: visualizer.display_existing_project(
            self.service_manager.project_manager.active_project_path))
        logger.info("Project Visualizer events wired.")

    def _wire_lsp_events(self) -> None:
        """Wire events for the Language Server Protocol integration."""
        if not self.window_manager: return
        code_viewer = self.window_manager.get_code_viewer()
        if not code_viewer or not hasattr(code_viewer, 'editor_manager'):
            logger.warning("CodeViewer or EditorTabManager not available for LSP event wiring.")
            return

        editor_manager = code_viewer.editor_manager
        self.event_bus.subscribe("lsp_diagnostics_received", editor_manager.handle_diagnostics)
        logger.info("LSP events wired.")

    def _wire_status_bar_events(self) -> None:
        """Wire events for updating the status bar."""
        if not self.window_manager: return
        main_window = self.window_manager.get_main_window()
        if not main_window or not hasattr(main_window, 'sidebar'): return

        status_bar = main_window.statusBar()
        if status_bar and hasattr(status_bar, 'update_agent_status'):
            self.event_bus.subscribe("agent_status_changed", status_bar.update_agent_status)
            logger.info("Status bar agent events wired.")
        else:
            logger.warning("StatusBar not found or is missing 'update_agent_status' method.")

    def _wire_chat_session_events(self) -> None:
        """Wire events for saving and loading chat sessions."""
        if not self.window_manager: return
        main_window = self.window_manager.get_main_window()
        if not main_window or not hasattr(main_window, 'chat_interface'):
            logger.warning("MainWindow or ChatInterface not available for chat session event wiring.")
            return

        chat_interface = main_window.chat_interface
        if chat_interface:
            self.event_bus.subscribe("save_chat_requested", chat_interface.save_session)
            self.event_bus.subscribe("load_chat_requested", chat_interface.load_session)
            logger.info("Chat session events wired.")
        else:
            logger.warning("ChatInterface not found on MainWindow for chat session event wiring.")

    def _wire_ui_events(self) -> None:
        """Wire events originating from the user interface."""
        if not all([self.service_manager, self.window_manager]):
            logger.warning("UI Event Wiring: ServiceManager or WindowManager not available.")
            return

        action_service = self.service_manager.get_action_service()
        if action_service:
            self.event_bus.subscribe("new_project_requested",
                                     lambda: asyncio.create_task(action_service.handle_new_project()))
            self.event_bus.subscribe("load_project_requested",
                                     lambda: asyncio.create_task(action_service.handle_load_project()))
            self.event_bus.subscribe("new_session_requested", action_service.handle_new_session)
            self.event_bus.subscribe("build_prompt_from_chat_requested", action_service.handle_build_prompt_from_chat)
        else:
            logger.warning("UI Event Wiring: ActionService not available.")

        app_state_service = self.service_manager.get_app_state_service()
        if app_state_service:
            self.event_bus.subscribe("interaction_mode_change_requested", app_state_service.set_interaction_mode)
        else:
            logger.warning("UI Event Wiring: AppStateService not available.")

        if self.window_manager:
            self.event_bus.subscribe("app_state_changed", self.window_manager.handle_app_state_change)
        else:
            logger.warning("UI Event Wiring: WindowManager not available for app_state_changed.")

        self.event_bus.subscribe(
            "configure_models_requested",
            lambda: asyncio.create_task(self.window_manager.show_model_config_dialog())
        )

        rag_manager = self.service_manager.get_rag_manager()
        if rag_manager:
            self.event_bus.subscribe("add_knowledge_requested", rag_manager.open_add_knowledge_dialog)
            self.event_bus.subscribe("add_active_project_to_rag_requested", rag_manager.ingest_active_project)
            self.event_bus.subscribe("add_global_knowledge_requested", rag_manager.open_add_global_knowledge_dialog)
        else:
            logger.warning("UI Event Wiring: RAGManager not available.")

        self.event_bus.subscribe("plugin_management_requested", self.window_manager.show_plugin_management_dialog)

        plugin_manager = self.service_manager.get_plugin_manager()
        if plugin_manager:
            self.event_bus.subscribe("plugin_enable_requested",
                                     lambda name: asyncio.create_task(plugin_manager.start_plugin(name)))
            self.event_bus.subscribe("plugin_disable_requested",
                                     lambda name: asyncio.create_task(plugin_manager.stop_plugin(name)))
            self.event_bus.subscribe("plugin_reload_requested",
                                     lambda name: asyncio.create_task(plugin_manager.reload_plugin(name)))
        else:
            logger.warning("UI Event Wiring: PluginManager not available.")

        self.event_bus.subscribe("show_log_viewer_requested", self.window_manager.show_log_viewer)
        self.event_bus.subscribe("show_code_viewer_requested", self.window_manager.show_code_viewer)
        self.event_bus.subscribe("show_project_visualizer_requested", self.window_manager.show_project_visualizer)
        logger.info("UI events wired.")

    def _wire_ai_workflow_events(self) -> None:
        """Wire events related to the AI code generation workflow."""
        if self.workflow_manager:
            self.event_bus.subscribe("user_request_submitted", self.workflow_manager.handle_user_request)
        else:
            logger.warning("AI Workflow Event Wiring: WorkflowManager not available.")

        code_viewer = self.window_manager.get_code_viewer() if self.window_manager else None
        if code_viewer and hasattr(code_viewer, 'editor_manager'):
            editor_manager = code_viewer.editor_manager

            self.event_bus.subscribe("project_scaffold_generated", code_viewer.display_scaffold)
            self.event_bus.subscribe("file_content_updated", editor_manager.create_or_update_tab)
            self.event_bus.subscribe("highlight_lines_for_edit", editor_manager.handle_highlight_lines)
            self.event_bus.subscribe("delete_highlighted_lines", editor_manager.handle_delete_lines)
            self.event_bus.subscribe("stream_text_at_cursor", editor_manager.handle_stream_at_cursor)
            self.event_bus.subscribe("position_cursor", editor_manager.handle_position_cursor)
            self.event_bus.subscribe("finalize_editor_content", editor_manager.handle_finalize_content)
            self.event_bus.subscribe("build_workflow_started", lambda: editor_manager.set_generating_state(True))
            # --- THIS IS THE FIX ---
            # The new 'ai_task_started' event now correctly signals the start of any AI task.
            # We also still listen for the old events for backward compatibility if needed.
            self.event_bus.subscribe("ai_task_started", lambda: editor_manager.set_generating_state(True))
            self.event_bus.subscribe("ai_workflow_finished", lambda: editor_manager.set_generating_state(False))
        else:
            logger.warning("AI Workflow Event Wiring: CodeViewer or EditorTabManager not available.")
        logger.info("AI workflow events wired.")

    def _wire_plugin_events(self) -> None:
        """Wire events related to the plugin system."""
        plugin_manager = self.service_manager.get_plugin_manager()
        if plugin_manager:
            self.event_bus.subscribe("plugin_loaded", lambda name: logger.info(f"Plugin loaded: {name}"))
            self.event_bus.subscribe("plugin_unloaded",
                                     lambda name: logger.info(f"Plugin unloaded: {name}"))
            self.event_bus.subscribe("plugin_error",
                                     lambda name, err: self.event_bus.emit("log_message_received", "Plugin", "error",
                                                                           f"Error in {name}: {err}"))
            self.event_bus.subscribe("plugin_state_changed", self._on_plugin_state_changed_for_sidebar)
        else:
            logger.warning("Plugin Event Wiring: PluginManager not available.")
        logger.info("Plugin events wired.")

    def _on_plugin_state_changed_for_sidebar(self, plugin_name: str, old_state: Any, new_state: Any) -> None:
        """
        Callback for when a plugin's state changes, to update the sidebar.
        """
        self._update_sidebar_plugin_status()

    def _update_sidebar_plugin_status(self) -> None:
        """Updates the plugin status indicator in the sidebar."""
        if not self.service_manager or not self.window_manager: return
        plugin_manager = self.service_manager.get_plugin_manager()
        if not plugin_manager: return
        enabled_plugins = plugin_manager.config.get_enabled_plugins()
        status = "off"
        if enabled_plugins:
            all_plugins_info = plugin_manager.get_all_plugins_info()
            status = "ok"
            for plugin in all_plugins_info:
                if plugin['name'] in enabled_plugins and plugin.get('state') != 'started':
                    status = "error"
                    break
        main_window = self.window_manager.get_main_window()
        if main_window and hasattr(main_window, 'sidebar'):
            main_window.sidebar.update_plugin_status(status)
            logger.info(f"Sidebar plugin status updated to: {status}")