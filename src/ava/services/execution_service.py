# src/ava/services/execution_service.py
import asyncio
import sys
from typing import TYPE_CHECKING, Optional

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
            # For critical errors, push a message to the live terminal view.
            self.event_bus.emit("terminal_output_received", f"--- ENGINE ERROR: {message} ---")
        self.event_bus.emit("log_message_received", self.__class__.__name__, level, message, **kwargs)

    async def handle_execute_command(self, command: str):
        """
        Handles the incoming command execution request.
        Creates a background task to run the command without blocking.
        """
        if self.current_process and self.current_process.returncode is None:
            self.log("warning", "Another command is already running. Please wait for it to finish.")
            self.event_bus.emit("terminal_output_received",
                                "--- A command is already in progress. Please wait. ---")
            return

        self.log("info", f"Received execution request for command: '{command}'")
        asyncio.create_task(self._run_command(command))

    async def _run_command(self, command: str):
        """
        The core coroutine that executes the command as a subprocess.
        """
        if not self.project_manager or not self.project_manager.active_project_path:
            self.log("error", "Cannot execute command: No active project.")
            self.event_bus.emit("command_execution_finished", -1)
            return

        venv_python = self.project_manager.venv_python_path

        # --- NEW: Smart venv creation logic ---
        if not venv_python or not venv_python.exists():
            self.event_bus.emit("terminal_output_received", "--- No virtual environment found. Attempting to create one now... ---")
            self.log("info", "No .venv found. Triggering automatic creation.")

            if self.project_manager.venv_manager:
                success = self.project_manager.venv_manager.create_venv()
                if success:
                    self.event_bus.emit("terminal_output_received", "--- Virtual environment created successfully. ---")
                    # Now that it's created, get the path again.
                    venv_python = self.project_manager.venv_python_path
                else:
                    error_msg = f"Failed to create virtual environment for project '{self.project_manager.active_project_name}'."
                    self.log("error", error_msg)
                    self.event_bus.emit("terminal_output_received", f"--- {error_msg} ---")
                    self.event_bus.emit("command_execution_finished", -1)
                    return
            else:
                error_msg = "VenvManager is not available on the ProjectManager."
                self.log("error", error_msg)
                self.event_bus.emit("terminal_output_received", f"--- {error_msg} ---")
                self.event_bus.emit("command_execution_finished", -1)
                return
        # --- End of new logic ---


        if not venv_python or not venv_python.exists():
            error_msg = f"Python executable still not found in .venv for project '{self.project_manager.active_project_name}' after creation attempt."
            self.log("error", error_msg)
            self.event_bus.emit("terminal_output_received", f"--- {error_msg} ---")
            self.event_bus.emit("command_execution_finished", -1)
            return

        parts = command.split()
        executable = parts[0].lower()

        if executable == "python":
            full_command = f'"{venv_python}" {" ".join(parts[1:])}'
        elif executable == "pip":
            pip_exe = venv_python.parent / "pip.exe" if sys.platform == "win32" else venv_python.parent / "pip"
            full_command = f'"{pip_exe}" {" ".join(parts[1:])}'
        else:
            full_command = f'"{venv_python}" -m {command}'

        self.event_bus.emit("terminal_output_received", f"> {command}\n")

        try:
            self.current_process = await asyncio.create_subprocess_shell(
                full_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.project_manager.active_project_path
            )

            while True:
                line_bytes = await self.current_process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode(sys.stdout.encoding, errors='replace').rstrip()
                self.event_bus.emit("terminal_output_received", line)

            await self.current_process.wait()
            return_code = self.current_process.returncode

            if return_code == 0:
                self.event_bus.emit("terminal_output_received", f"\n--- Command finished successfully (Exit Code: {return_code}) ---")
            else:
                self.event_bus.emit("terminal_output_received", f"\n--- Command failed (Exit Code: {return_code}) ---")

            self.event_bus.emit("command_execution_finished", return_code)

        except FileNotFoundError:
            self.log("error", f"Command failed: Executable not found for '{command}'")
            self.event_bus.emit("command_execution_finished", -1)
        except Exception as e:
            self.log("error", f"An unexpected error occurred while executing command '{command}': {e}")
            self.event_bus.emit("terminal_output_received", f"--- An exception occurred: {e} ---")
            self.event_bus.emit("command_execution_finished", -1)
        finally:
            self.current_process = None