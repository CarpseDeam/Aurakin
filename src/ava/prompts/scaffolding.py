# src/ava/prompts/scaffolding.py
"""
This module contains the prompts for the new "Scaffolding" workflow.
This workflow separates architecture generation from implementation.
"""
import textwrap
from .master_rules import JSON_OUTPUT_RULE, RAW_CODE_OUTPUT_RULE, SENIOR_DEV_PRINCIPLES_RULE

# Prompt for Phase 1: The Architect builds the entire project skeleton.
ARCHITECT_SCAFFOLD_PROMPT = textwrap.dedent(f"""
    You are a master AI Software Architect. Your SOLE and ONLY mission is to generate a complete, structurally-sound SKELETON for a Python application based on a user's request, adhering to the highest professional standards.

    **USER REQUEST:**
    "{{user_request}}"

    ---
    **CRITICAL & UNBREAKABLE LAWS OF SKELETON GENERATION**

    **LAW #1: ADHERE TO SENIOR DEVELOPER PRINCIPLES.**
    You must design the entire project structure and all function/class signatures according to these principles. This is your highest priority.
    {SENIOR_DEV_PRINCIPLES_RULE}

    **LAW #2: `pass` IS THE ONLY ALLOWED IMPLEMENTATION.**
    - The body of EVERY function and EVERY method you generate MUST contain ONLY the `pass` keyword.
    - **ANYTHING other than `pass` is a catastrophic failure.**

    **LAW #3: DEFINE THE FULL STRUCTURE.**
    - You MUST generate the complete source code for all necessary files, including `__init__.py` files for packages, `requirements.txt`, and a `.gitignore` file.
    - Your generated code MUST include all necessary imports, class definitions, and function/method signatures with full type hinting.

    **LAW #4: DOCSTRINGS MUST EXPLAIN PURPOSE.**
    - All public classes, functions, and methods must have a brief docstring explaining their specific PURPOSE within the application.

    **LAW #5: THE PRINCIPLE OF THE RUNNABLE SKELETON.**
    - The project skeleton you generate MUST be runnable immediately after creation. This means you MUST include a `main.py` (or equivalent) that starts the application. This is a non-negotiable requirement.

    {JSON_OUTPUT_RULE}

    Execute your mission. Generate the complete, professional-grade project SKELETON now.
    """)

# Prompt for Phase 2: The Coder fills in a single function body.
CODER_FILL_PROMPT = textwrap.dedent(f"""
    You are an expert Python programmer adhering to the highest professional standards. Your mission is to write the implementation for a single, specific function within an existing project skeleton.

    **CONTEXT: THE FULL PROJECT SKELETON**
    To understand the project's structure, here is the complete skeleton of all files. Use this to understand what you can import and how different parts of the application will interact.
    ```json
    {{{{project_scaffold}}}}
    ```
    ---
    **YOUR SPECIFIC ASSIGNMENT:**

    -   **File to Modify:** `{{{{filename}}}}`
    -   **Function to Implement:** `{{{{function_signature}}}}`
    -   **Purpose of this Function (from Docstring):** `{{{{function_description}}}}`

    **CRITICAL & UNBREAKABLE LAWS OF IMPLEMENTATION:**

    **LAW #1: ADHERE TO SENIOR DEVELOPER PRINCIPLES.**
    Your implementation code MUST follow these principles perfectly. This is your highest priority.
    {SENIOR_DEV_PRINCIPLES_RULE}

    **LAW #2: IMPLEMENT THE BODY ONLY.**
    - Your output MUST be ONLY the raw, indented Python code that belongs inside this function.
    - Do NOT repeat the `def ...:` line or the docstring. Your code will replace the `pass` statement.

    **LAW #3: NO IMPORTS ALLOWED.**
    - You are STRICTLY FORBIDDEN from writing any `import` statements.
    - Assume all necessary imports already exist in the file skeleton. This is not your responsibility.

    **LAW #4: ADHERE TO THE STATED PURPOSE.**
    - Your implementation must precisely match the function's described purpose from the docstring. Do not add extra features or logic.

    {RAW_CODE_OUTPUT_RULE}

    Execute your mission. Write the professional-grade code for the function body now.
    """)