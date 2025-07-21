# src/ava/core/plugins/examples/creative_assistant/__init__.py

import asyncio
import aiohttp
import json

from src.ava.core.plugins.plugin_system import PluginBase, BackgroundPluginMixin, PluginMetadata
from src.ava.prompts import CREATIVE_ASSISTANT_PROMPT


class CreativeAssistantPlugin(PluginBase, BackgroundPluginMixin):
    """
    A creative assistant plugin named Aura that helps refine ideas into technical prompts.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Creative Assistant (Aura)",
            version="1.0.0",
            description="A creative partner to brainstorm and structure technical prompts.",
            author="Avakin",
            enabled_by_default=True
        )

    def __init__(self, event_bus, plugin_config):
        super().__init__(event_bus, plugin_config)
        # This state is no longer managed here; WorkflowManager is in charge.
        self.is_active = False
        self.conversation_history = []
        self.llm_server_url = "http://127.0.0.1:8002/stream_chat"

    async def load(self) -> bool:
        self.log("info", f"{self.metadata.name} loaded.")
        return True

    async def start(self) -> bool:
        # --- FIX: The plugin no longer directly subscribes to user requests. ---
        # This responsibility now belongs solely to the WorkflowManager.
        # self.subscribe_to_event("user_request_submitted", self.handle_user_request)
        self.log("info", f"{self.metadata.name} started. Its logic is now managed by the core WorkflowManager.")
        self.set_state(self.state.STARTED)
        return True

    async def stop(self) -> bool:
        self.is_active = False
        self.log("info", f"{self.metadata.name} stopped.")
        self.set_state(self.state.STOPPED)
        return True

    async def unload(self) -> bool:
        return True

    # --- FIX: All request handling logic has been removed from the plugin ---
    # and centralized in the WorkflowManager to prevent race conditions and
    # ensure a single source of truth for handling user input based on the
    # application's InteractionMode.