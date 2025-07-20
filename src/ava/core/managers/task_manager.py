# src/ava/core/managers/task_manager.py
import asyncio
from typing import Optional, Dict, TYPE_CHECKING
from PySide6.QtWidgets import QMessageBox

from src.ava.core.event_bus import EventBus

if TYPE_CHECKING:
    from src.ava.core.managers.service_manager import ServiceManager
    from src.ava.core.managers.window_manager import WindowManager


class TaskManager:
    """
    Manages background task lifecycle and coordination.
    Single responsibility: Task creation, monitoring, and cleanup.
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

        # Active tasks
        self.ai_task: Optional[asyncio.Task] = None

        # Manager references (set by Application)
        self.service_manager: "ServiceManager" = None
        self.window_manager: "WindowManager" = None

        print("[TaskManager] Initialized")

    def set_managers(self, service_manager: "ServiceManager", window_manager: "WindowManager"):
        """Set references to other managers."""
        self.service_manager = service_manager
        self.window_manager = window_manager

    def start_ai_workflow_task(self, workflow_coroutine) -> bool:
        """Start an AI workflow task."""
        if self.ai_task and not self.ai_task.done():
            main_window = self.window_manager.get_main_window() if self.window_manager else None
            QMessageBox.warning(main_window, "AI Busy", "The AI is currently processing another request.")
            return False

        self.ai_task = asyncio.create_task(workflow_coroutine)
        self.ai_task.add_done_callback(self._on_ai_task_done)

        print("[TaskManager] Started AI workflow task")
        return True

    def _on_ai_task_done(self, task: asyncio.Task):
        """Handle AI task completion."""
        try:
            task.result()
            self.event_bus.emit("ai_response_ready", "Code generation complete. Run the code or ask for modifications.")
        except asyncio.CancelledError:
            print("[TaskManager] AI task was cancelled")
        except Exception as e:
            print(f"[TaskManager] CRITICAL ERROR IN AI TASK: {e}")
            import traceback
            traceback.print_exc()

            main_window = self.window_manager.get_main_window() if self.window_manager else None
            QMessageBox.critical(main_window, "Workflow Error",
                                 f"The AI workflow failed unexpectedly.\n\nError: {e}")
        finally:
            self.event_bus.emit("ai_workflow_finished")

    def cancel_ai_task(self) -> bool:
        """Cancel the current AI task."""
        if self.ai_task and not self.ai_task.done():
            self.ai_task.cancel()
            print("[TaskManager] Cancelled AI task")
            return True
        return False

    async def cancel_all_tasks(self):
        """Cancel all running tasks and wait for them to complete."""
        tasks_to_cancel = []

        # Cancel AI task
        if self.ai_task and not self.ai_task.done():
            self.ai_task.cancel()
            tasks_to_cancel.append(self.ai_task)

        # Wait for all cancelled tasks to complete
        if tasks_to_cancel:
            print(f"[TaskManager] Waiting for {len(tasks_to_cancel)} tasks to cancel...")
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        print("[TaskManager] All tasks cancelled")

    def get_task_summary(self) -> dict:
        """Get a summary of all active tasks."""
        return {
            "ai_task_running": self.ai_task is not None and not self.ai_task.done(),
        }