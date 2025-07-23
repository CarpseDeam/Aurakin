# src/ava/services/review_service.py
import asyncio
import json
from typing import Dict, Any, Optional, List

from src.ava.core.event_bus import EventBus
from src.ava.services.base_generation_service import BaseGenerationService


class ReviewService(BaseGenerationService):
    """Phase 3: Architect performs a final review of the generated code."""

    def __init__(self, service_manager: Any, event_bus: EventBus, user_request: str):
        super().__init__(service_manager, event_bus)
        self.user_request = user_request

    async def execute(self, files_to_review: Dict) -> Optional[Dict]:
        """
        Executes the final review stage on the implemented code.

        Args:
            files_to_review: The fully implemented code from the previous phase.

        Returns:
            The reviewed (and possibly fixed) code, or the original code if review fails.
        """
        self.log("info", "--- Phase 3: Architect is performing final integration review... ---")
        self.event_bus.emit("agent_status_changed", "Architect", "Final review...", "fa5s.search")

        architect = self.service_manager.get_architect_service()
        # The architect service already knows how to review.
        fixes_plan = await architect.review_and_fix(self.user_request, json.dumps(files_to_review, indent=2))

        if fixes_plan is None:
            self.log("warning", "Reviewer agent failed to return valid JSON. Skipping review.")
            return files_to_review

        if fixes := fixes_plan.get("fixes"):
            self.log("info", f"Architect found {len(fixes)} issues. Applying final fixes...")
            return await self._apply_animated_surgical_edits(files_to_review, fixes)

        self.log("success", "Architect review complete. No issues found.")
        return files_to_review

    async def _apply_animated_surgical_edits(self, original_files: Dict, edits: List[Dict]) -> Dict:
        """Applies fixes with UI animation."""
        modified_files = original_files.copy()
        for edit in edits:
            filename = edit.get("filename")
            start = edit.get("start_line")
            end = edit.get("end_line")
            code = edit.get("corrected_code")

            if not all([filename, start, end, code is not None]):
                self.log("warning", f"Reviewer provided an incomplete fix and it was discarded: {edit}")
                continue
            if filename not in modified_files:
                self.log("warning", f"Reviewer tried to edit non-existent file: {filename}")
                continue

            # NEW event for visualizer
            if self.project_manager and self.project_manager.active_project_path:
                abs_path_str = str(self.project_manager.active_project_path / filename)
                self.event_bus.emit("agent_activity_started", "Architect", abs_path_str)


            self.event_bus.emit("highlight_lines_for_edit", filename, start, end)
            await asyncio.sleep(0.75)
            self.event_bus.emit("delete_highlighted_lines", filename)
            await asyncio.sleep(0.4)

            lines = modified_files[filename].splitlines()
            # Delete the specified lines (inclusive)
            del lines[start - 1:end]
            # Insert the corrected code at the start line position
            lines[start - 1:start - 1] = code.splitlines()

            final_content = "\n".join(lines)
            modified_files[filename] = final_content
            self.event_bus.emit("file_content_updated", filename, final_content)
            await asyncio.sleep(0.2)
        return modified_files