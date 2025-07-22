from __future__ import annotations
import json
import logging
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.ava.prompts.planner import ARCHITECT_PROMPT

if TYPE_CHECKING:
    from src.ava.core.llm_client import LLMClient
    from src.ava.services.rag_service import RAGService

logger = logging.getLogger(__name__)


class ArchitectService:
    """
    Service for the Architect agent, handling both planning and reviewing.
    """

    def __init__(self, llm_client: "LLMClient", rag_service: "RAGService"):
        self.llm_client = llm_client
        self.rag_service = rag_service

    async def generate_plan(self, user_request: str, code_context: str) -> Optional[Dict[str, Any]]:
        """Generates the initial task plan for the Coder."""
        logger.info("Architect entering 'PLAN' mode...")
        rag_context = await self.rag_service.query(user_request) or "No relevant RAG context found."
        prompt = ARCHITECT_PROMPT.format(
            mode='PLAN',
            user_request=user_request,
            code_context=code_context,
            rag_context=rag_context
        )
        return await self._call_architect_llm(prompt)

    async def review_and_fix(self, user_request: str, code_context: str) -> Optional[Dict[str, Any]]:
        """Reviews the generated code and returns a list of fixes."""
        logger.info("Architect entering 'REVIEW' mode...")
        prompt = ARCHITECT_PROMPT.format(
            mode='REVIEW',
            user_request=user_request,
            code_context=code_context,
            rag_context="RAG context is not used in review mode."
        )
        return await self._call_architect_llm(prompt)

    async def _call_architect_llm(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Helper function to call the LLM and parse the JSON response."""
        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            logger.error("No model configured for the 'architect' role.")
            return None

        raw_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, prompt, "architect"):
                raw_response += chunk

            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if not match:
                raise ValueError("No JSON object found in the LLM response.")
            return json.loads(match.group(0))
        except Exception as e:
            logger.error(f"Architect LLM call failed: {e}\nRaw Response: {raw_response}", exc_info=True)
            return None