from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.ava.prompts.planner import TASK_PLANNER_PROMPT

if TYPE_CHECKING:
    from src.ava.core.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ArchitectService:
    """
    A simplified service to generate a JSON task plan from a user request.

    This service is responsible for formatting the planner prompt, calling the
    Language Model (LLM), and parsing the resulting JSON plan. It does not
    handle RAG, event emissions, or other complex logic, which is managed
    by the calling workflow.
    """

    def __init__(self, llm_client: "LLMClient"):
        """
        Initializes the ArchitectService.

        Args:
            llm_client: The client for interacting with the LLM.
        """
        self.llm_client = llm_client

    async def generate_plan(
        self,
        user_request: str,
        code_context: str,
        rag_context: str,
        system_directive: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Generates a structured task plan by calling the LLM.

        Args:
            user_request: The user's request for code generation or modification.
            code_context: A JSON string representing existing files and their content.
            rag_context: Contextual information retrieved from RAG.
            system_directive: A specific directive for the LLM based on project state.

        Returns:
            A dictionary representing the plan, or None if planning fails.
        """
        logger.info("ArchitectService generating task plan...")

        prompt = TASK_PLANNER_PROMPT.format(
            system_directive=system_directive,
            user_request=user_request,
            code_context=code_context,
            rag_context=rag_context,
        )

        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            logger.error("No model configured for the 'architect' role.")
            return None

        raw_response = ""
        try:
            # Stream the response and accumulate it
            async for chunk in self.llm_client.stream_chat(
                provider, model, prompt, "architect"
            ):
                raw_response += chunk

            # Parse the accumulated response
            plan = self._parse_json_response(raw_response)
            if not isinstance(plan.get("tasks"), list):
                raise ValueError(
                    "AI did not return a valid task plan in JSON format. "
                    "The 'tasks' key is missing or not a list."
                )

            logger.info(
                f"Successfully generated task plan with {len(plan['tasks'])} tasks."
            )
            return plan
        except Exception as e:
            logger.error(f"Task plan creation failed: {e}", exc_info=True)
            logger.debug(f"Raw LLM response that caused error:\n{raw_response}")
            return None

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        Robustly parses a JSON object from a string that may contain other text.

        It looks for a JSON object enclosed in curly braces.

        Args:
            response: The string response from the LLM.

        Returns:
            The parsed dictionary.

        Raises:
            ValueError: If no JSON object is found or if the JSON is invalid.
        """
        # Use regex to find the JSON block, which might be wrapped in ```json ... ```
        match = re.search(r"\{.*\}", response, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in the LLM response.")

        json_string = match.group(0)
        try:
            return json.loads(json_string)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from response: {e}")
            logger.debug(f"Invalid JSON string: {json_string}")
            raise ValueError("Failed to decode JSON from response.") from e