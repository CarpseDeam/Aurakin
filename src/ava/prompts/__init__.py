# src/ava/prompts/__init__.py

# This file acts as the public API for the prompts module.

# --- DEPRECATED PROMPTS (can be removed later) ---
from .architect import HIERARCHICAL_PLANNER_PROMPT, MODIFICATION_PLANNER_PROMPT
from .coder import CODER_PROMPT, SURGICAL_MODIFICATION_PROMPT, SIMPLE_FILE_PROMPT

# --- CORE PROMPTS ---
from .creative import CREATIVE_ASSISTANT_PROMPT, AURA_REFINEMENT_PROMPT
from .planner import TASK_PLANNER_PROMPT, LINE_LOCATOR_PROMPT, CODE_SNIPPET_GENERATOR_PROMPT
from .reviewer import REVIEWER_PROMPT

__all__ = [
    # Planner Prompts (Whiteboard Workflow)
    'TASK_PLANNER_PROMPT',
    'LINE_LOCATOR_PROMPT',
    'CODE_SNIPPET_GENERATOR_PROMPT',

    # Creative Assistant Prompt
    'CREATIVE_ASSISTANT_PROMPT',
    'AURA_REFINEMENT_PROMPT',

    # Reviewer Prompt
    'REVIEWER_PROMPT',

    # Deprecated - For reference until fully phased out
    'HIERARCHICAL_PLANNER_PROMPT',
    'MODIFICATION_PLANNER_PROMPT',
    'CODER_PROMPT',
    'SURGICAL_MODIFICATION_PROMPT',
    'SIMPLE_FILE_PROMPT',
]