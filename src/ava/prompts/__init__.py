# src/ava/prompts/__init__.py

# Prompts for the new, lean workflow
from .planner import ARCHITECT_PROMPT
from .scaffolding import ARCHITECT_SCAFFOLD_PROMPT, CODER_FILL_PROMPT

__all__ = [
    'ARCHITECT_PROMPT', # Still used for the final REVIEW stage
    'ARCHITECT_SCAFFOLD_PROMPT',
    'CODER_FILL_PROMPT',
]