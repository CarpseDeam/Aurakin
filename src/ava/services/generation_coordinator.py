# src/ava/services/generation_coordinator.py
import logging
from typing import Dict, Any, Optional

from .scaffolding_service import ScaffoldingService
from .implementation_service import ImplementationService
from .review_service import ReviewService
from ..core.event_bus import EventBus

logger = logging.getLogger(__name__)


class GenerationCoordinator:
    """
    Orchestrates the new "Blueprint" workflow by coordinating
    the Scaffolding, Implementation, and Review services.
    """

    def __init__(self, service_manager: Any, event_bus: EventBus):
        self.service_manager = service_manager
        self.event_bus = event_bus

    async def coordinate_generation(
            self,
            existing_files: Optional[Dict[str, str]],
            user_request: str
    ) -> Optional[Dict[str, str]]:
        """Executes the three-phase generation pipeline."""

        self.event_bus.emit("build_workflow_started")

        # Instantiate services for this run
        scaffolding_service = ScaffoldingService(self.service_manager, self.event_bus)
        implementation_service = ImplementationService(self.service_manager, self.event_bus)
        review_service = ReviewService(self.service_manager, self.event_bus, user_request)

        # --- PHASE 1: SCAFFOLDING (BLUEPRINTING) ---
        scaffold_files = await scaffolding_service.execute(user_request)
        if not scaffold_files:
            self.log("error", "Scaffolding phase failed. Aborting generation.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        # --- PHASE 2: IMPLEMENTATION ---
        implemented_files = await implementation_service.execute(scaffold_files)
        if not implemented_files:
            self.log("error", "Implementation phase failed. Aborting generation.")
            self.event_bus.emit("ai_workflow_finished")
            return None

        # --- PHASE 3: REVIEW ---
        reviewed_files = await review_service.execute(implemented_files)
        if reviewed_files is None:
            self.log("warning", "Review stage failed. Returning implemented code as-is.")
            self.event_bus.emit("ai_workflow_finished")
            return implemented_files

        self.log("success", "✅ Blueprint Workflow Finished Successfully.")
        return reviewed_files

    def log(self, level: str, message: str, **kwargs):
        """Helper to emit log messages for the coordinator itself."""
        self.event_bus.emit("log_message_received", "GenCoordinator", level, message, **kwargs)