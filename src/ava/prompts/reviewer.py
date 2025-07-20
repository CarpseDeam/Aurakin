# src/ava/prompts/reviewer.py
"""
This file defines the prompt for the 'Reviewer' agent.

The Reviewer agent is responsible for the final pass over the generated code.
It acts as an automated code review tool, identifying bugs, style violations,
and integration issues, and reporting them in a structured JSON format.
"""

import textwrap
from .master_rules import JSON_OUTPUT_RULE

REVIEWER_PROMPT = textwrap.dedent(f"""
You are an expert automated code review AI. Your sole purpose is to meticulously analyze a set of newly generated Python files and report any bugs, errors, or violations of best practices. You must be strict and thorough.

**CONTEXT:**
You will be provided with a JSON object containing the filenames and the complete source code for all files generated in the current session.

**CODE TO REVIEW:**