# src/ava/prompts/planner.py
"""
This file houses the prompts for the multi-agent 'Whiteboard' workflow.

This workflow deconstructs a coding request into a series of micro-tasks that are
executed by specialized AI agents, ensuring a more controlled and accurate generation process.

The workflow consists of three main stages:
1.  Task Planning: A high-level planner breaks the request into a structured list of tasks.
2.  Line Location: A code analyst pinpoints the exact line numbers for each task.
3.  Snippet Generation: A focused coder generates only the specific code snippet for the change.
"""

import textwrap
from .master_rules import JSON_OUTPUT_RULE, RAW_CODE_OUTPUT_RULE

# --- TASK PLANNER PROMPT ---
# This prompt is for the first agent in the "Whiteboard" workflow.
# It takes a user request and the project context and breaks it down into a structured plan of tasks.
TASK_PLANNER_PROMPT = textwrap.dedent(f\"\"\"
You are a master software architect. Your role is to deconstruct a user's request into a series of discrete, actionable tasks for a team of AI agents. You must analyze the existing codebase to determine the most logical and efficient way to implement the changes.

**USER'S REQUEST:**
"{{user_request}}"

**EXISTING PROJECT FILES & CONTENT:**