# src/ava/prompts/__init__.py

# This file acts as the public API for the prompts module.

# --- DEPRECATED PROMPTS (can be removed later) ---
from .coder import CODER_PROMPT, SURGICAL_MODIFICATION_PROMPT, SIMPLE_FILE_PROMPT

# --- CORE PROMPTS ---
from .creative import CREATIVE_ASSISTANT_PROMPT, AURA_REFINEMENT_PROMPT
from .planner import TASK_PLANNER_PROMPT, LINE_LOCATOR_PROMPT
from .reviewer import REVIEWER_PROMPT
from .finisher import FINISHER_PROMPT
from .scaffolder import SCAFFOLDER_PROMPT
from .completer import COMPLETER_PROMPT
from .dependency_analyzer import DEPENDENCY_ANALYZER_PROMPT


__all__ = [
    # Planner, Scaffolder, Completer & Analyzer Prompts
    'TASK_PLANNER_PROMPT',
    'LINE_LOCATOR_PROMPT',
    'SCAFFOLDER_PROMPT',
    'COMPLETER_PROMPT',
    'DEPENDENCY_ANALYZER_PROMPT',

    # Creative Assistant Prompt
    'CREATIVE_ASSISTANT_PROMPT',
    'AURA_REFINEMENT_PROMPT',

    # Reviewer & Finisher Prompts
    'REVIEWER_PROMPT',
    'FINISHER_PROMPT',

    # Deprecated - For reference until fully phased out
    'CODER_PROMPT',
    'SURGICAL_MODIFICATION_PROMPT',
    'SIMPLE_FILE_PROMPT',
]