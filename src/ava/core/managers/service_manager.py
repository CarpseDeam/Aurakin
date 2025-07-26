# src/ava/core/managers/service_manager.py
from __future__ import annotations
import sys
import subprocess
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional
import traceback  # For detailed error logging
import asyncio

from src.ava.core import process_manager

from src.ava.core.event_bus import EventBus
from src.ava.core.llm_client import LLMClient
from src.ava.core.project_manager import ProjectManager
from src.ava.core.plugins.plugin_manager import PluginManager
from src.ava.services import (
    ActionService, AppStateService,
    ProjectIndexerService, ImportFixerService,
    GenerationCoordinator, RAGService,
    LSPClientService, TestGenerationService, CodeExtractorService,
    ExecutionService
)

if TYPE_CHECKING:
    from src.ava.services.action_service import ActionService
    from src.ava.services.rag_manager import RAGManager


class ServiceManager:
    """
    Manages all application services and their dependencies.
    Single responsibility: Service lifecycle and dependency injection.
    """

    def __init__(self, event_bus: EventBus, project_root: Path):
        self.event_bus = event_bus
        self.project_root = project_root

        self.llm_client: LLMClient = None
        self.project_manager: ProjectManager = None
        self.plugin_manager: PluginManager = None
        self.app_state_service: AppStateService = None
        self.action_service: "ActionService" = None
        self.rag_manager: "RAGManager" = None
        self.lsp_client_service: LSPClientService = None
        self.project_indexer_service: ProjectIndexerService = None
        self.import_fixer_service: ImportFixerService = None
        self.generation_coordinator: GenerationCoordinator = None
        self.test_generation_service: TestGenerationService = None
        self.code_extractor_service: CodeExtractorService = None
        self.execution_service: ExecutionService = None
        self._service_injection_enabled = True

        self.log_to_event_bus("info", "[ServiceManager] Initialized")

    def log_to_event_bus(self, level: str, message: str):
        """Helper to send logs through the event bus."""
        self.event_bus.emit("log_message_received", "ServiceManager", level, message)

    def initialize_core_components(self, project_root: Path, project_manager: ProjectManager):
        self.log_to_event_bus("info", "[ServiceManager] Initializing core components...")
        self.llm_client = LLMClient(project_root)
        self.project_manager = project_manager
        self.log_to_event_bus("info", "[ServiceManager] Core components initialized")

    async def initialize_plugins(self) -> bool:
        if not self.plugin_manager:
            self.log_to_event_bus("warning", "[ServiceManager] No plugin manager available for plugin initialization")
            return False
        success = await self.plugin_manager.initialize()
        self.log_to_event_bus("info", "[ServiceManager] Plugin initialization completed")
        return success

    def initialize_services(self, code_viewer=None):
        """Initialize services with proper dependency order."""
        self.log_to_event_bus("info", "[ServiceManager] Initializing services...")
        from src.ava.services.rag_manager import RAGManager

        self.app_state_service = AppStateService(self.event_bus)
        self.project_indexer_service = ProjectIndexerService()
        self.import_fixer_service = ImportFixerService()
        self.code_extractor_service = CodeExtractorService()
        self.execution_service = ExecutionService(self.event_bus, self.project_manager)

        self.rag_manager = RAGManager(self.event_bus, self.project_root)
        if self.project_manager:
            self.rag_manager.set_project_manager(self.project_manager)

        self.lsp_client_service = LSPClientService(self.event_bus, self.project_manager)

        self.generation_coordinator = GenerationCoordinator(
            service_manager=self,
            event_bus=self.event_bus
        )

        self.test_generation_service = TestGenerationService(
            service_manager=self,
            event_bus=self.event_bus
        )

        self.action_service = ActionService(self.event_bus, self, None, None)

        self.log_to_event_bus("info", "[ServiceManager] Services initialized")

    def launch_background_servers(self):
        """Launches the RAG and LLM servers as separate processes and registers them for cleanup."""
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

        # --- DEV TOGGLE: Comment out these lines to disable log file creation ---
        # lsp_subprocess_log_file = log_dir_for_servers / "lsp_server_subprocess.log"
        # llm_subprocess_log_file = log_dir_for_servers / "llm_server_subprocess.log"
        # rag_subprocess_log_file = log_dir_for_servers / "rag_server_subprocess.log"
        # --- END TOGGLE ---

        startupinfo = None
        if sys.platform == "win32" and not python_executable_to_use.endswith("pythonw.exe"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        env = os.environ.copy()
        if not getattr(sys, 'frozen', False):
            source_repo_root = self.project_root.parent
            env["PYTHONPATH"] = str(source_repo_root)

        self.log_to_event_bus("info", "Attempting to launch LLM server...")
        try:
            # --- DEV TOGGLE: LOGS DISABLED ---
            # To re-enable, comment out this block and uncomment the one below.
            llm_proc = subprocess.Popen(
                [python_executable_to_use, str(llm_script_path)], cwd=str(cwd_for_servers),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                env=env
            )
            # --- END DISABLED BLOCK ---

            # --- DEV TOGGLE: LOGS ENABLED ---
            # To enable, uncomment this block and comment out the one above.
            # with open(llm_subprocess_log_file, "w", encoding="utf-8") as llm_log_handle:
            #     llm_proc = subprocess.Popen(
            #         [python_executable_to_use, str(llm_script_path)], cwd=str(cwd_for_servers),
            #         stdout=llm_log_handle, stderr=subprocess.STDOUT,
            #         startupinfo=startupinfo,
            #         env=env
            #     )
            # --- END ENABLED BLOCK ---

            process_manager.register(llm_proc, "LLM Server")
            pid = llm_proc.pid if llm_proc else 'N/A'
            self.log_to_event_bus("info", f"LLM Server process started with PID: {pid}")
        except Exception as e:
            self.log_to_event_bus("error", f"Failed to launch LLM server: {e}\n{traceback.format_exc()}")

        self.log_to_event_bus("info", "Attempting to launch RAG server...")
        try:
            # --- DEV TOGGLE: LOGS DISABLED ---
            rag_proc = subprocess.Popen(
                [python_executable_to_use, str(rag_script_path)], cwd=str(cwd_for_servers),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                env=env
            )
            # --- END DISABLED BLOCK ---

            # --- DEV TOGGLE: LOGS ENABLED ---
            # with open(rag_subprocess_log_file, "w", encoding="utf-8") as rag_log_handle:
            #     rag_proc = subprocess.Popen(
            #         [python_executable_to_use, str(rag_script_path)], cwd=str(cwd_for_servers),
            #         stdout=rag_log_handle, stderr=subprocess.STDOUT,
            #         startupinfo=startupinfo,
            #         env=env
            #     )
            # --- END ENABLED BLOCK ---

            process_manager.register(rag_proc, "RAG Server")
            pid = rag_proc.pid if rag_proc else 'N/A'
            self.log_to_event_bus("info", f"RAG Server process started with PID: {pid}")
        except Exception as e:
            self.log_to_event_bus("error", f"Failed to launch RAG server: {e}\n{traceback.format_exc()}")

        self.log_to_event_bus("info", "Attempting to launch Python LSP server...")
        lsp_command = [python_executable_to_use, "-m", "pylsp", "--tcp", "--port", "8003"]
        try:
            # --- DEV TOGGLE: LOGS DISABLED ---
            lsp_proc = subprocess.Popen(
                lsp_command, cwd=str(cwd_for_servers),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                startupinfo=startupinfo,
                env=env
            )
            # --- END DISABLED BLOCK ---

            # --- DEV TOGGLE: LOGS ENABLED ---
            # with open(lsp_subprocess_log_file, "w", encoding="utf-8") as lsp_log_handle:
            #     lsp_proc = subprocess.Popen(
            #         lsp_command, cwd=str(cwd_for_servers),
            #         stdout=lsp_log_handle, stderr=subprocess.STDOUT,
            #         startupinfo=startupinfo,
            #         env=env
            #     )
            # --- END ENABLED BLOCK ---

            process_manager.register(lsp_proc, "Python LSP Server")
            pid = lsp_proc.pid if lsp_proc else 'N/A'
            self.log_to_event_bus("info", f"LSP Server process started with PID: {pid}")
            asyncio.create_task(self.lsp_client_service.connect())
        except FileNotFoundError:
            self.log_to_event_bus("error",
                                  "Failed to launch LSP server: `pylsp` command not found. Please ensure `python-lsp-server` is installed.")
        except Exception as e:
            self.log_to_event_bus("error", f"Failed to launch LSP server: {e}\n{traceback.format_exc()}")

    def terminate_background_servers(self):
        """Terminates background servers by calling the central ProcessManager."""
        self.log_to_event_bus("info",
                              "[ServiceManager] Handing off to ProcessManager to terminate background servers...")
        process_manager.terminate_all()

    async def shutdown(self):
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
        return self.generation_coordinator is not None

    def get_lsp_client_service(self) -> LSPClientService:
        return self.lsp_client_service

    def get_app_state_service(self) -> AppStateService:
        return self.app_state_service

    def get_action_service(self) -> ActionService:
        return self.action_service

    def get_llm_client(self) -> LLMClient:
        return self.llm_client

    def get_project_manager(self) -> ProjectManager:
        return self.project_manager

    def get_rag_manager(self) -> "RAGManager":
        return self.rag_manager

    def get_project_indexer_service(self) -> ProjectIndexerService:
        return self.project_indexer_service

    def get_import_fixer_service(self) -> ImportFixerService:
        return self.import_fixer_service

    def get_generation_coordinator(self) -> GenerationCoordinator:
        return self.generation_coordinator

    def get_test_generation_service(self) -> TestGenerationService:
        return self.test_generation_service

    def get_code_extractor_service(self) -> CodeExtractorService:
        return self.code_extractor_service

    def get_execution_service(self) -> ExecutionService:
        return self.execution_service

    def get_plugin_manager(self) -> PluginManager:
        return self.plugin_manager