# src/ava/services/response_validator_service.py
import json
import re
from typing import Dict, Any, Optional, Union, List

class ResponseValidatorService:
    """
    A dedicated service to parse, clean, and validate responses from LLMs.
    Its single responsibility is to turn raw, unpredictable LLM string
    output into a predictable, usable Python object (dict or list).
    """

    def extract_and_parse_json(self, raw_response: str) -> Optional[Union[Dict, List]]:
        """
        Extracts a JSON object or list from a raw string and parses it.
        This function is robust against conversational text or markdown code fences.
        """
        if not raw_response or not isinstance(raw_response, str):
            return None
        match = re.search(r'(\{.*\}|\[.*\])', raw_response, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _clean_scaffold_paths(self, scaffold: Dict[str, str]) -> Dict[str, str]:
        """
        Detects and removes a spurious common base directory from scaffold keys.
        e.g., {"AppName/main.py": "..."} becomes {"main.py": "..."}
        """
        if not scaffold:
            return scaffold

        paths = list(scaffold.keys())
        paths_in_dirs = [p for p in paths if '/' in p.replace('\\', '/')]
        if not paths_in_dirs:
            return scaffold

        path_parts = [p.replace('\\', '/').split('/') for p in paths_in_dirs]
        first_part = path_parts[0][0]
        if not first_part:
            return scaffold

        if all(p[0] == first_part for p in path_parts):
            cleaned_scaffold = {}
            for original_path, content in scaffold.items():
                parts = original_path.replace('\\', '/').split('/')
                if len(parts) > 1 and parts[0] == first_part:
                    new_path = '/'.join(parts[1:])
                    cleaned_scaffold[new_path] = content
                else:
                    cleaned_scaffold[original_path] = content
            return cleaned_scaffold

        return scaffold

    def validate_and_flatten_scaffold(self, parsed_json: Optional[Union[Dict, List]]) -> Optional[Dict[str, str]]:
        """
        Validates and flattens a scaffold response into a clean Dict[str, str].
        This handles various formats the LLM might return and cleans the paths.
        """
        if not parsed_json or not isinstance(parsed_json, dict):
            return None

        flat_scaffold: Optional[Dict[str, str]] = None

        # Case 1: The response is already in the correct flat format.
        if all(isinstance(v, str) for v in parsed_json.values()):
            flat_scaffold = parsed_json
        # Case 2: Files are nested under a 'files' key as a dictionary.
        elif "files" in parsed_json and isinstance(parsed_json["files"], dict):
            flat_scaffold = parsed_json["files"]
        # Case 3: Files are nested under a 'files' key as a list of dicts.
        elif "files" in parsed_json and isinstance(parsed_json["files"], list):
            temp_scaffold = {}
            for item in parsed_json["files"]:
                if isinstance(item, dict) and "filename" in item and "content" in item:
                    temp_scaffold[item["filename"]] = item["content"]
                else:
                    return None  # Malformed item in the list
            flat_scaffold = temp_scaffold

        if flat_scaffold:
            return self._clean_scaffold_paths(flat_scaffold)

        return None