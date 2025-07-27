# src/ava/services/execution_service.py
import asyncio
import sys
import os
from typing import TYPE_CHECKING, Optional, Tuple

from src.ava.core.event_bus import EventBus

if TYPE_CHECKING:
    from src.ava.core.project_manager import ProjectManager


class ExecutionService:
    """
    The universal command execution engine.
    Listens for 'execute_command_requested' events and runs the specified
    command in the active project's virtual environment.
    """

    def __init__(self, event_bus: EventBus, project_manager: "ProjectManager"):
        self.event_bus = event_bus
        self.project_manager = project_manager
        self.current_process: Optional[asyncio.subprocess.Process] = None

        self.event_bus.subscribe("execute_command_requested", self.handle_execute_command)
        self.log("info", "ExecutionService Initialized and listening for commands.")

    def log(self, level: str, message: str, **kwargs):
        """Helper to emit log messages and user-facing terminal output for errors."""
        if level == "error":
            self.event_bus.emit("terminal_output_received", f"--- ENGINE ERROR: {message} ---")
        self.event_bus.emit("log_message_received", self.__class__.__name__, level, message, **kwargs)

    def handle_execute_command(self, command: str):
        """
        Handles the incoming command execution request for UI display.
        This is a "fire-and-forget" method from the caller's perspective.
        """
        if self.current_process and self.current_process.returncode is None:
            self.log("warning", "Another command is already running. Please wait for it to finish.")
            self.event_bus.emit("terminal_output_received",
                                "--- A command is already in progress. Please wait. ---")
            return

        self.log("info", f"Received execution request for command: '{command}'")
        asyncio.create_task(self.execute_and_capture(command))

    async def execute_and_capture(self, command: str) -> Tuple[int, str]:
        """
        The core coroutine that executes a command, streams its output to the UI,
        and returns the final exit code and full output.
        """
        if self.current_process and self.current_process.returncode is None:
            self.log("warning", "Another command is already running. Please wait for it to finish.")
            return -1, "Command already in progress."

        if not self.project_manager or not self.project_manager.active_project_path:
            self.log("error", "Cannot execute command: No active project.")
            return -1, "No active project."

        # --- THIS IS THE FIX ---
        # The service now explicitly clears the log before every run.
        self.event_bus.emit("clear_executor_log")
        self.event_bus.emit("terminal_output_received", f"> {command}\n")
        # --- END OF FIX ---

        venv_python = self.project_manager.venv_python_path
        if not venv_python or not venv_python.exists():
            self.event_bus.emit("terminal_output_received",
                                "--- No virtual environment found. Attempting to create one now... ---")
            self.log("info", "No .venv found. Triggering automatic creation.")
            success = await asyncio.to_thread(self.project_manager.venv_manager.create_venv)
            if success:
                self.event_bus.emit("terminal_output_received", "--- Virtual environment created successfully. ---")
                venv_python = self.project_manager.venv_python_path
            else:
                error_msg = f"Failed to create virtual environment for project '{self.project_manager.active_project_name}'."
                self.log("error", error_msg)
                self.event_bus.emit("terminal_output_received", f"--- {error_msg} ---")
                return -1, error_msg

        if not venv_python or not venv_python.exists():
            error_msg = f"Python executable still not found in .venv for project '{self.project_manager.active_project_name}'."
            self.log("error", error_msg)
            return -1, error_msg

        env = os.environ.copy()
        env['PYTHONPATH'] = str(self.project_manager.active_project_path)
        self.log("info", f"Executing with PYTHONPATH set to: {env['PYTHONPATH']}")

        full_command = f'"{venv_python}" {command[len("python "):]}' if command.lower().startswith(
            "python ") else f'"{venv_python}" -m {command}'
        full_output = []

        try:
            self.current_process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.project_manager.active_project_path,
                env=env
            )
            while True:
                line_bytes = await self.current_process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode(sys.stdout.encoding, errors='replace').rstrip()
                self.event_bus.emit("terminal_output_received", line)
                full_output.append(line)

            await self.current_process.wait()
            return_code = self.current_process.returncode
            if return_code == 0:
                self.event_bus.emit("terminal_output_received",
                                    f"\n--- Command finished successfully (Exit Code: {return_code}) ---")
            else:
                self.event_bus.emit("terminal_output_received", f"\n--- Command failed (Exit Code: {return_code}) ---")

            self.event_bus.emit("command_execution_finished", return_code)
            return return_code, "\n".join(full_output)
        except Exception as e:
            msg = f"An unexpected error occurred while executing command '{command}': {e}"
            self.log("error", msg)
            self.event_bus.emit("terminal_output_received", f"--- An exception occurred: {e} ---")
            self.event_bus.emit("command_execution_finished", -1)
            return -1, msg
        finally:
            self.current_process = None