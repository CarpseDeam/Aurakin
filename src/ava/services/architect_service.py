# src/ava/services/architect_service.py
from __future__ import annotations
import asyncio
import json
import re
import os
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from src.ava.core.event_bus import EventBus
from src.ava.core.llm_client import LLMClient
from src.ava.core.project_manager import ProjectManager
from src.ava.prompts import (
    HIERARCHICAL_PLANNER_PROMPT,
    MODIFICATION_PLANNER_PROMPT,
    SCAFFOLDER_PROMPT
)
from src.ava.services.rag_service import RAGService
from src.ava.services.project_indexer_service import ProjectIndexerService
from src.ava.services.import_fixer_service import ImportFixerService
from src.ava.services.generation_coordinator import GenerationCoordinator
from src.ava.services.context_manager import ContextManager
from src.ava.services.dependency_planner import DependencyPlanner
from src.ava.services.integration_validator import IntegrationValidator
from src.ava.utils.code_summarizer import CodeSummarizer

if TYPE_CHECKING:
    from src.ava.core.managers import ServiceManager


class ArchitectService:
    def __init__(self, service_manager: 'ServiceManager', event_bus: EventBus,
                 llm_client: LLMClient, project_manager: ProjectManager,
                 rag_service: RAGService, project_indexer: ProjectIndexerService,
                 import_fixer: ImportFixerService):
        self.service_manager = service_manager
        self.event_bus = event_bus
        self.llm_client = llm_client
        self.project_manager = project_manager
        self.rag_service = rag_service
        self.project_indexer = project_indexer
        self.import_fixer = import_fixer
        self.context_manager = ContextManager(service_manager)
        self.dependency_planner = DependencyPlanner(service_manager)
        self.integration_validator = IntegrationValidator(service_manager)
        self.generation_coordinator = GenerationCoordinator(
            service_manager, event_bus, self.context_manager,
            self.dependency_planner, self.integration_validator
        )

    async def _get_combined_rag_context(self, prompt: str) -> str:
        project_rag_context = await self.rag_service.query(prompt, target_collection="project")
        global_rag_context = await self.rag_service.query(prompt, target_collection="global")

        valid_project_context = project_rag_context if "no relevant documents found" not in project_rag_context.lower() and "not running or is unreachable" not in project_rag_context.lower() else ""
        valid_global_context = global_rag_context if "no relevant documents found" not in global_rag_context.lower() and "not running or is unreachable" not in global_rag_context.lower() else ""

        combined_context_parts = []
        if valid_project_context:
            combined_context_parts.append(
                f"PROJECT-SPECIFIC CONTEXT (e.g., GDD, existing project files):\n{valid_project_context}")
        if valid_global_context:
            combined_context_parts.append(
                f"GENERAL PYTHON EXAMPLES & BEST PRACTICES (GLOBAL CONTEXT):\n{valid_global_context}")

        if not combined_context_parts:
            return "No specific RAG context found for this query."

        return "\n\n---\n\n".join(combined_context_parts)

    async def generate_or_modify(self, prompt: str, existing_files: dict | None) -> bool:
        self.log("info", f"Architect task received: '{prompt}'")
        self.event_bus.emit("agent_status_changed", "Architect", "Planning project...", "fa5s.pencil-ruler")
        plan = None

        self.log("info", "Fetching combined RAG context...")
        combined_rag_context = await self._get_combined_rag_context(prompt)
        self.log("info", f"Combined RAG context length: {len(combined_rag_context)} chars.")

        if not existing_files:
            self.log("info", "No existing project detected. Generating new project plan...")
            plan = await self._generate_hierarchical_plan(prompt, combined_rag_context)
        else:
            self.log("info", "Existing project detected. Using default modification plan...")
            plan = await self._generate_modification_plan(prompt, existing_files, combined_rag_context)

        if plan:
            success = await self._execute_coordinated_generation(plan, combined_rag_context, existing_files)
        else:
            self.log("error", "Failed to generate a valid plan. Aborting generation.")
            success = False

        if success:
            self.log("success", "Code generation complete.")
        else:
            self.handle_error("coder", "Code generation failed.")
        return success

    async def _generate_hierarchical_plan(self, prompt: str, rag_context: str) -> dict | None:
        self.log("info", "Designing project structure...")
        plan_prompt = HIERARCHICAL_PLANNER_PROMPT.format(prompt=prompt, rag_context=rag_context)
        initial_plan = await self._get_plan_from_llm(plan_prompt)

        if not initial_plan:
            return None

        self.log("info", "Initial plan created. Now scaffolding files...")
        augmented_plan = await self._scaffold_plan_files(initial_plan, rag_context, existing_files=None)
        return augmented_plan

    async def _generate_modification_plan(self, prompt: str, existing_files: dict, rag_context: str) -> dict | None:
        self.log("info", "Analyzing existing files to create a modification plan...")
        prompt_template = MODIFICATION_PLANNER_PROMPT
        try:
            full_code_context_json = json.dumps(existing_files, indent=2)
            enhanced_prompt_for_llm = f"{prompt}\n\nADDITIONAL CONTEXT FROM KNOWLEDGE BASE:\n{rag_context}"
            plan_prompt = prompt_template.format(
                prompt=enhanced_prompt_for_llm,
                full_code_context=full_code_context_json
            )
            initial_plan = await self._get_plan_from_llm(plan_prompt)
            if initial_plan:
                initial_plan = self._sanitize_plan_paths(initial_plan)
            else:
                return None

            self.log("info", "Initial modification plan created. Now scaffolding files...")
            augmented_plan = await self._scaffold_plan_files(initial_plan, rag_context, existing_files=existing_files)
            return augmented_plan
        except Exception as e:
            self.handle_error("architect", f"An unexpected error during modification planning: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _scaffold_plan_files(self, initial_plan: dict, rag_context: str,
                                   existing_files: Optional[Dict[str, str]]) -> dict | None:
        if not initial_plan or not initial_plan.get("files"):
            return None

        total_files = len(initial_plan["files"])
        self.log("info", f"Scaffolding {total_files} file(s)...")

        tasks = [
            self._scaffold_single_file(file_info, initial_plan, rag_context, existing_files, i + 1, total_files)
            for i, file_info in enumerate(initial_plan["files"])
        ]
        scaffolded_results = await asyncio.gather(*tasks)

        augmented_files = []
        for result in scaffolded_results:
            if result:
                augmented_files.append(result)
            else:
                self.log("error", "A file failed to scaffold. Aborting plan.")
                return None

        initial_plan["files"] = augmented_files
        return initial_plan

    async def _scaffold_single_file(self, file_info: Dict[str, str], full_plan: Dict, rag_context: str,
                                    existing_files: Optional[Dict[str, str]], current_num: int,
                                    total_num: int) -> Optional[Dict[str, str]]:
        filename = file_info["filename"]
        self.log("info", f"({current_num}/{total_num}) Scaffolding {filename}...")
        self.event_bus.emit("agent_status_changed", "Scaffolder", f"Scaffolding {filename}...", "fa5s.drafting-compass")

        is_modification = existing_files is not None and filename in existing_files
        original_code_section = ""
        if is_modification:
            original_code = existing_files.get(filename, "")
            original_code_section = f"\n---\n**ORIGINAL CODE OF `{filename}` (You are modifying this file):**\n```python\n{original_code}\n```"

        symbol_index = {}
        if existing_files:
            for rel_path, content in existing_files.items():
                if rel_path.endswith(".py"):
                    module_path_str = rel_path.replace('.py', '').replace('/', '.')
                    symbols_in_file = self.project_indexer.get_symbols_from_content(content, module_path_str)
                    symbol_index.update(symbols_in_file)

        code_context = existing_files.copy() if existing_files else {}
        if filename in code_context:
            del code_context[filename]

        scaffold_prompt = SCAFFOLDER_PROMPT.format(
            filename=filename,
            purpose=file_info.get("purpose", ""),
            original_code_section=original_code_section,
            file_plan_json=json.dumps(full_plan, indent=2),
            symbol_index_json=json.dumps(symbol_index, indent=2),
            code_context_json=json.dumps(code_context, indent=2),
        )

        provider, model = self.llm_client.get_model_for_role("scaffolder")
        if not provider or not model:
            self.handle_error("scaffolder", "No model configured for scaffolder role.")
            return None

        raw_scaffold_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, scaffold_prompt, "scaffolder"):
                raw_scaffold_response += chunk

            scaffold_json = self._parse_json_response(raw_scaffold_response)
            scaffold_code = scaffold_json.get("scaffold_code")

            if not scaffold_code or not isinstance(scaffold_code, str):
                self.log("error", "Scaffolder AI's response was invalid or missing 'scaffold_code'.",
                         raw_scaffold_response)
                raise ValueError("AI did not return valid scaffold_code in JSON format.")

            file_info["scaffold_code"] = scaffold_code
            return file_info
        except (json.JSONDecodeError, ValueError) as e:
            self.handle_error("scaffolder", f"Scaffold creation failed for {filename}: {e}", raw_scaffold_response)
            return None
        except Exception as e:
            self.handle_error("scaffolder", f"An unexpected error during scaffolding for {filename}: {e}",
                              raw_scaffold_response)
            return None

    async def _get_plan_from_llm(self, plan_prompt: str) -> dict | None:
        provider, model = self.llm_client.get_model_for_role("architect")
        if not provider or not model:
            self.handle_error("architect", "No model configured for architect role.")
            return None
        raw_plan_response = ""
        try:
            async for chunk in self.llm_client.stream_chat(provider, model, plan_prompt, "architect"):
                raw_plan_response += chunk
            plan = self._parse_json_response(raw_plan_response)
            if not plan or not isinstance(plan.get("files"), list):
                self.log("error", "The AI's plan was invalid or missing the 'files' list.", raw_plan_response)
                raise ValueError("AI did not return a valid file plan in JSON format.")
            self.log("success", f"Plan created: {len(plan['files'])} file(s).")
            return plan
        except (json.JSONDecodeError, ValueError) as e:
            self.handle_error("architect", f"Plan creation failed: {e}", raw_plan_response)
            return None
        except Exception as e:
            self.handle_error("architect", f"An unexpected error during planning: {e}", raw_plan_response)
            return None

    async def _execute_coordinated_generation(self, plan: dict, rag_context: str,
                                              existing_files: Optional[Dict[str, str]]) -> bool:
        try:
            is_modification = existing_files is not None
            files_to_generate = plan.get("files", [])
            if not files_to_generate:
                self.log("warning", "Architect created an empty plan. Nothing to generate.")
                return True
            project_root = self.project_manager.active_project_path
            all_filenames = [f['filename'] for f in files_to_generate]
            self.event_bus.emit("prepare_for_generation", all_filenames, str(project_root), is_modification)
            await self._create_package_structure(files_to_generate)
            await asyncio.sleep(0.1)
            self.log("info", "Handing off to unified Generation Coordinator...")
            generated_files = await self.generation_coordinator.coordinate_generation(plan, rag_context,
                                                                                      existing_files)
            if not generated_files:
                self.log("error", "Generation coordinator returned no files.")
                return False
            first_purpose = plan["files"][0].get("purpose", "AI-driven changes")
            commit_message = f"feat: {first_purpose[:50]}..."
            self.project_manager.save_and_commit_files(generated_files, commit_message)
            self.log("success", "Project changes committed successfully.")
            self.event_bus.emit("code_generation_complete", generated_files)
            return True
        except Exception as e:
            self.handle_error("coder", f"Coordinated generation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _sanitize_plan_paths(self, plan: dict) -> dict:
        if not plan or 'files' not in plan: return plan
        sanitized_files = []
        for file_entry in plan.get('files', []):
            original_filename_str = file_entry.get('filename')
            if not original_filename_str: continue
            p = Path(original_filename_str.replace('\\', '/'))
            parts = p.parts
            if len(parts) > 1 and parts[0] == parts[1]:
                corrected_path = Path(*parts[1:])
                corrected_path_str = corrected_path.as_posix()
                self.log("warning",
                         f"FIXED DUPLICATE PATH: Corrected '{original_filename_str}' to '{corrected_path_str}'")
                file_entry['filename'] = corrected_path_str
            sanitized_files.append(file_entry)
        plan['files'] = sanitized_files
        return plan

    async def _create_package_structure(self, files: list):
        if not self.project_manager.active_project_path:
            return

        is_python_project = any(f['filename'].endswith('.py') for f in files)
        if not is_python_project:
            self.log("info", "Non-Python project detected. Skipping __init__.py creation.")
            return

        dirs_that_need_init = {str(Path(f['filename']).parent) for f in files if
                               '/' in f['filename'] or '\\' in f['filename']}
        init_files_to_create = {}
        for d_str in dirs_that_need_init:
            d = Path(d_str)
            if d.name == '.' or not d_str: continue
            init_path = d / "__init__.py"
            is_planned = any(f['filename'] == init_path.as_posix() for f in files)
            exists_on_disk = (self.project_manager.active_project_path / init_path).exists()
            if not is_planned and not exists_on_disk:
                init_files_to_create[init_path.as_posix()] = "# This file makes this a Python package\n"

        if init_files_to_create:
            self.log("info", f"Creating missing __init__.py files: {list(init_files_to_create.keys())}")
            self.project_manager.save_and_commit_files(init_files_to_create, "chore: add package markers")
            await asyncio.sleep(0.1)

    def _parse_json_response(self, response: str) -> dict:
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in the response.")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to decode JSON. Error: {e}. Content: '{match.group(0)[:200]}...'")

    def handle_error(self, agent: str, error_msg: str, response: str = ""):
        self.log("error", f"{agent} failed: {error_msg}\nResponse: {response}")
        self.event_bus.emit("ai_response_ready", f"Sorry, the {agent} failed.")

    def log(self, level: str, message: str):
        self.event_bus.emit("log_message_received", "ArchitectService", level, message)