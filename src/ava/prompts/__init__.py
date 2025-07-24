# src/ava/prompts/__init__.py

# Prompt for the Architect's final review
from .planner import ARCHITECT_PROMPT

# Prompts for the new "Blueprint" workflow
from .scaffolding import ARCHITECT_BLUEPRINT_PROMPT, CODER_IMPLEMENT_MARKER_PROMPT

__all__ = [
    'ARCHITECT_PROMPT',
    'ARCHITECT_BLUEPRINT_PROMPT',
    'CODER_IMPLEMENT_MARKER_PROMPT',
]