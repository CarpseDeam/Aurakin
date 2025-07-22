# src/ava/core/managers/service_manager.py
from __future__ import annotations
import sys
import subprocess
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional
import traceback  # For detailed error logging
import asyncio
import logging

from src.ava.core.event_bus import EventBus
from src.ava.core.llm_client import LLMClient
from src.ava.core.project_manager import ProjectManager
from src.ava.core.plugins.plugin_manager import PluginManager
from src.ava.services import (
    ActionService, AppStateService, ArchitectService,
    ProjectIndexerService, ImportFixerService,
    GenerationCoordinator, ContextManager, DependencyPlanner, IntegrationValidator,
    LSPClientService
)

if TYPE_CHECKING:
    from src.ava.services.action_service import ActionService
    from src.ava.services.rag_manager import RAGManager

logger = logging.getLogger(__name__)


class ServiceManager:
    """
    Manages all application services and their dependencies.
    Single responsibility: Service lifecycle and dependency injection.
    """

    def __init__(self, event_bus: EventBus, project_root: Path):
        """
        Initializes the ServiceManager.

        Args:
            event_bus: The application's event bus for communication.
            project_root: The root directory of the current project.
        """
        self.event_bus = event_bus
        self.project_root = project_root

        self.llm_client: Optional[LLMClient] = None
        self.project_manager: Optional[ProjectManager] = None
        self.plugin_manager: Optional[PluginManager] = None
        self.app_state_service: Optional[AppStateService] = None
        self.action_service: Optional["ActionService"] = None
        self.rag_manager: Optional["RAGManager"] = None
        self.lsp_client_service: Optional[LSPClientService] = None
        self.architect_service: Optional[ArchitectService] = None
        self.project_indexer_service: Optional[ProjectIndexerService] = None
        self.import_fixer_service: Optional[ImportFixerService] = None
        self.context_manager: Optional[ContextManager] = None
        self.dependency_planner: Optional[DependencyPlanner] = None
        self.integration_validator: Optional[IntegrationValidator] = None
        self.generation_coordinator: Optional[GenerationCoordinator] = None
        self._service_injection_enabled = True

        self.rag_server_process: Optional[subprocess.Popen] = None
        self.llm_server_process: Optional[subprocess.Popen] = None
        self.lsp_server_process: Optional[subprocess.Popen] = None

        self.log_to_event_bus("info", "[ServiceManager] Initialized")

    def log_to_event_bus(self, level: str, message: str):
        """
        Helper to send logs through the event bus.

        Args:
            level: The log level (e.g., 'info', 'error').
            message: The log message.
        """
        self.event_bus.emit("log_message_received", "ServiceManager", level, message)

    def initialize_core_components(self, project_root: Path, project_manager: ProjectManager):
        """
        Initializes core components like the LLMClient and ProjectManager.

        Args:
            project_root: The root directory of the project.
            project_manager: The manager for project-related state.
        """
        self.log_to_event_bus("info", "[ServiceManager] Initializing core components...")
        self.llm_client = LLMClient(project_root)
        self.project_manager = project_manager
        self.log_to_event_bus("info", "[ServiceManager] Core components initialized")

    async def initialize_plugins(self) -> bool:
        """
        Initializes the plugin manager and all registered plugins.

        Returns:
            True if initialization was successful, False otherwise.
        """
        if not self.plugin_manager:
            self.log_to_event_bus("warning", "[ServiceManager] No plugin manager available for plugin initialization")
            return False
        success = await self.plugin_manager.initialize()
        self.log_to_event_bus("info", "[ServiceManager] Plugin initialization completed")
        return success

    def initialize_services(self, code_viewer=None):
        """
        Initialize services with proper dependency order.

        Args:
            code_viewer: An optional reference to the code viewer UI component.
        """
        self.log_to_event_bus("info", "[ServiceManager] Initializing services...")
        from src.ava.services.rag_manager import RAGManager

        self.app_state_service = AppStateService(self.event_bus)
        self.project_indexer_service = ProjectIndexerService()
        self.import_fixer_service = ImportFixerService()
        self.context_manager = ContextManager(self)
        self.dependency_planner = DependencyPlanner(self)
        self.integration_validator = IntegrationValidator(self)
        self.rag_manager = RAGManager(self.event_bus, self.project_root)
        if self.project_manager:
            self.rag_manager.set_project_manager(self.project_manager)

        self.lsp_client_service = LSPClientService(self.event_bus, self.project_manager)

        # --- THIS IS THE FIX ---
        self.generation_coordinator = GenerationCoordinator(
            service_manager=self,
            event_bus=self.event_bus
        )
        # --- END FIX ---

        self.architect_service = ArchitectService(self.llm_client)
        self.action_service = ActionService(self.event_bus, self, None, None)

        self.log_to_event_bus("info", "[ServiceManager] Services initialized")

    def launch_background_servers(self):
        """Launches the RAG and LLM servers as separate processes."""
        python_executable_to_use: str
        cwd_for_servers: Path
        log_dir_for_servers: Path

        self.log_to_event_bus("info", "Determining paths for launching background servers...")
        if getattr(sys, 'frozen', False):
            base_path_for_bundle = self.project_root
            self.log_to_event_bus("info", f"Running in bundled mode. Base path: {base_path_for_bundle}")

            private_python_scripts_dir = base_path_for_bundle / ".venv" / "Scripts"

            if sys.platform == "win32":
                pythonw_exe = private_python_scripts_dir / "pythonw.exe"
                if pythonw_exe.exists():
                    python_executable_to_use = str(pythonw_exe)
                    self.log_to_event_bus("info", f"Using pythonw.exe for bundled server: {python_executable_to_use}")
                else:
                    python_exe = private_python_scripts_dir / "python.exe"
                    if not python_exe.exists():
                        error_msg = f"CRITICAL: Private Python executable (python.exe or pythonw.exe) not found in {private_python_scripts_dir}. Cannot start servers."
                        self.log_to_event_bus("error", error_msg)
                        return
                    python_executable_to_use = str(python_exe)
                    self.log_to_event_bus("info",
                                          f"pythonw.exe not found, using python.exe for bundled server: {python_executable_to_use}")
            else:
                python_exe = private_python_scripts_dir.parent / "bin" / "python"
                if not python_exe.exists():
                    error_msg = f"CRITICAL: Private Python executable not found at {python_exe}. Cannot start servers."
                    self.log_to_event_bus("error", error_msg)
                    return
                python_executable_to_use = str(python_exe)

            cwd_for_servers = base_path_for_bundle
            log_dir_for_servers = base_path_for_bundle
            self.log_to_event_bus("info",
                                  f"Bundled mode - Python: {python_executable_to_use}, CWD: {cwd_for_servers}, SubprocessLogDir: {log_dir_for_servers}")
        else:
            source_repo_root = self.project_root.parent
            self.log_to_event_bus("info", f"Running from source. Repo root: {source_repo_root}")
            python_executable_to_use = sys.executable
            cwd_for_servers = source_repo_root
            log_dir_for_servers = source_repo_root
            self.log_to_event_bus("info",
                                  f"Source mode - Python: {python_executable_to_use}, CWD: {cwd_for_servers}, SubprocessLogDir: {log_dir_for_servers}")

        try:
            log_dir_for_servers.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log_to_event_bus("error",
                                  f"Failed to create log directory {log_dir_for_servers} for server subprocesses: {e}")

        server_script_base_dir = self.project_root / "ava"
        llm_script_path = server_script_base_dir / "llm_server.py"
        rag_script_path = server_script_base_dir / "rag_server.py"
        lsp_subprocess_log_file = log_dir_for_servers / "lsp_server_subprocess.log"

        llm_subprocess_log_file = log_dir_for_servers / "llm_server_subprocess.log"
        rag_subprocess_log_file = log_dir_for_servers / "rag_server_subprocess.log"

        startupinfo = None
        if sys.platform == "win32" and not python_executable_to_use.endswith("pythonw.exe"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        env = os.environ.copy()
        if not getattr(sys, 'frozen', False):
            source_repo_root = self.project_root.parent
            env["PYTHONPATH"] = str(source_repo_root)

        if self.llm_server_process is None or self.llm_server_process.poll() is not None:
            self.log_to_event_bus("info", "Attempting to launch LLM server...")
            try:
                with open(llm_subprocess_log_file, "w", encoding="utf-8") as llm_log_handle:
                    self.llm_server_process = subprocess.Popen(
                        [python_executable_to_use, str(llm_script_path)], cwd=str(cwd_for_servers),
                        stdout=llm_log_handle, stderr=subprocess.STDOUT,
                        startupinfo=startupinfo,
                        env=env
                    )
                pid = self.llm_server_process.pid if self.llm_server_process else 'N/A'
                self.log_to_event_bus("info", f"LLM Server process started with PID: {pid}")
            except Exception as e:
                self.log_to_event_bus("error", f"Failed to launch LLM server: {e}\n{traceback.format_exc()}")

        if self.rag_server_process is None or self.rag_server_process.poll() is not None:
            self.log_to_event_bus("info", "Attempting to launch RAG server...")
            try:
                with open(rag_subprocess_log_file, "w", encoding="utf-8") as rag_log_handle:
                    self.rag_server_process = subprocess.Popen(
                        [python_executable_to_use, str(rag_script_path)], cwd=str(cwd_for_servers),
                        stdout=rag_log_handle, stderr=subprocess.STDOUT,
                        startupinfo=startupinfo,
                        env=env
                    )
                pid = self.rag_server_process.pid if self.rag_server_process else 'N/A'
                self.log_to_event_bus("info", f"RAG Server process started with PID: {pid}")
            except Exception as e:
                self.log_to_event_bus("error", f"Failed to launch RAG server: {e}\n{traceback.format_exc()}")

        if self.lsp_server_process is None or self.lsp_server_process.poll() is not None:
            self.log_to_event_bus("info", "Attempting to launch Python LSP server...")
            lsp_command = [python_executable_to_use, "-m", "pylsp", "--tcp", "--port", "8003"]
            try:
                with open(lsp_subprocess_log_file, "w", encoding="utf-8") as lsp_log_handle:
                    self.lsp_server_process = subprocess.Popen(
                        lsp_command, cwd=str(cwd_for_servers),
                        stdout=lsp_log_handle, stderr=subprocess.STDOUT,
                        startupinfo=startupinfo,
                        env=env
                    )
                pid = self.lsp_server_process.pid if self.lsp_server_process else 'N/A'
                self.log_to_event_bus("info", f"LSP Server process started with PID: {pid}")
                asyncio.create_task(self.lsp_client_service.connect())
            except FileNotFoundError:
                self.log_to_event_bus("error",
                                      "Failed to launch LSP server: `pylsp` command not found. Please ensure `python-lsp-server` is installed.")
            except Exception as e:
                self.log_to_event_bus("error", f"Failed to launch LSP server: {e}\n{traceback.format_exc()}")

    def terminate_background_servers(self):
        """Terminates all running background server processes."""
        self.log_to_event_bus("info", "[ServiceManager] Terminating background servers...")
        servers = {"LLM": self.llm_server_process, "RAG": self.rag_server_process, "LSP": self.lsp_server_process}
        for name, process in servers.items():
            if process and process.poll() is None:
                self.log_to_event_bus("info", f"[ServiceManager] Terminating {name} server (PID: {process.pid})...")
                process.terminate()
                try:
                    process.wait(timeout=5)
                    self.log_to_event_bus("info", f"[ServiceManager] {name} server terminated.")
                except subprocess.TimeoutExpired:
                    self.log_to_event_bus("warning",
                                          f"[ServiceManager] {name} server did not terminate gracefully. Killing.")
                    process.kill()
                except Exception as e:
                    self.log_to_event_bus("error", f"[ServiceManager] Error during {name} server termination: {e}")
        self.llm_server_process = self.rag_server_process = self.lsp_server_process = None
        self.log_to_event_bus("info", "[ServiceManager] Background server processes set to None.")

    async def shutdown(self):
        """Shuts down all services and background processes gracefully."""
        self.log_to_event_bus("info", "[ServiceManager] Shutting down services...")
        if self.lsp_client_service: await self.lsp_client_service.shutdown()
        self.terminate_background_servers()
        if self.plugin_manager and hasattr(self.plugin_manager, 'shutdown'):
            try:
                await self.plugin_manager.shutdown()
            except Exception as e:
                self.log_to_event_bus("error", f"[ServiceManager] Error shutting down plugin manager: {e}")
        self.log_to_event_bus("info", "[ServiceManager] Services shutdown complete")

    def is_fully_initialized(self) -> bool:
        """
        Checks if all essential services are initialized.

        Returns:
            True if the GenerationCoordinator is available, False otherwise.
        """
        return self.generation_coordinator is not None

    def get_lsp_client_service(self) -> LSPClientService:
        """Returns the LSPClientService instance."""
        return self.lsp_client_service

    def get_app_state_service(self) -> AppStateService:
        """Returns the AppStateService instance."""
        return self.app_state_service

    def get_action_service(self) -> ActionService:
        """Returns the ActionService instance."""
        return self.action_service

    def get_llm_client(self) -> LLMClient:
        """Returns the LLMClient instance."""
        return self.llm_client

    def get_project_manager(self) -> ProjectManager:
        """Returns the ProjectManager instance."""
        return self.project_manager

    def get_rag_manager(self) -> "RAGManager":
        """Returns the RAGManager instance."""
        return self.rag_manager

    def get_architect_service(self) -> ArchitectService:
        """Returns the ArchitectService instance."""
        return self.architect_service

    def get_project_indexer_service(self) -> ProjectIndexerService:
        """Returns the ProjectIndexerService instance."""
        return self.project_indexer_service

    def get_import_fixer_service(self) -> ImportFixerService:
        """Returns the ImportFixerService instance."""
        return self.import_fixer_service

    def get_context_manager(self) -> ContextManager:
        """Returns the ContextManager instance."""
        return self.context_manager

    def get_dependency_planner(self) -> DependencyPlanner:
        """Returns the DependencyPlanner instance."""
        return self.dependency_planner

    def get_integration_validator(self) -> IntegrationValidator:
        """Returns the IntegrationValidator instance."""
        return self.integration_validator

    def get_generation_coordinator(self) -> GenerationCoordinator:
        """Returns the GenerationCoordinator instance."""
        return self.generation_coordinator

    def get_plugin_manager(self) -> PluginManager:
        """Returns the PluginManager instance."""
        return self.plugin_manager