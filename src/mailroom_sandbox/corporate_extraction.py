"""Per-call corporate extraction schemas derived from the selected Dojo registry."""
from __future__ import annotations

import copy
import re
import hashlib
import math
from pathlib import Path
from typing import Any

from llm_dojo_scoring.schemas import corporate_record_schema as registry


def subclass_from_handoff(handoff: str | None) -> str | None:
    """Read only the graph's sorter header; never inspect the document or labels."""
    if not handoff:
        return None
    header = handoff.splitlines()[0]
    if not header.startswith('Sorter classification: '):
        return None
    match = re.search(r'(?:^|\s)doc_subclass=(\S+)', header)
    if not match:
        return None
    subclass = match.group(1).removesuffix('.').lower()
    if subclass not in registry.SUBCLASS_SCHEMAS:
        raise ValueError(f'Unknown corporate subclass: {subclass}')
    return subclass


def request_schema(subclass: str | None, transport_schema: dict[str, Any]) -> dict[str, Any]:
    if subclass is not None and subclass not in registry.SUBCLASS_SCHEMAS:
        raise ValueError(f'Unknown corporate subclass: {subclass}')
    schema = registry.corporate_record_json_schema(subclass)
    # LangChain may use this title as an OpenAI-compatible function name.
    schema['title'] = f"CorporateRecordExtraction_{subclass}" if subclass else "CorporateRecordExtraction"
    # Transport metadata is not part of Dojo's scored field registry.
    for key in ('confidence', 'reasoning'):
        if key in transport_schema.get('properties', {}):
            schema['properties'][key] = copy.deepcopy(transport_schema['properties'][key])
            schema['required'].append(key)
    return schema


def handoff_with_guidance(handoff: str | None, subclass: str | None) -> str | None:
    if subclass is None:
        return handoff
    return f'{handoff}\nCorporate subclass extraction rules: {registry.render_subclass_block(subclass)}'


REGISTRY_FINGERPRINTS = {
    "corporate_record_schema": "2f5a070a3d26b4bde90305d3824443e6c2ef6a55d257e30050eb84b12dd1ab39",
    "doc_classes": "6f6bea610e3850fcd824b6d2414c6e63acdc9547343ab744b06cc86c804cfc2e",
}


def registry_fingerprints() -> dict[str, str]:
    from llm_dojo_scoring.schemas import doc_classes
    return {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for name, module in (("corporate_record_schema", registry), ("doc_classes", doc_classes))}


def registry_matches() -> bool:
    """Fail preflight if either selected Dojo schema source changes."""
    return registry_fingerprints() == REGISTRY_FINGERPRINTS


def validate_response(value: Any, schema: dict[str, Any], *, allow_missing_confidence: bool = False) -> bool:
    """Validate the subset of JSON Schema emitted by the corporate registry/transport."""
    if allow_missing_confidence and isinstance(value, dict) and value.get('confidence') is None:
        # HF-006 keeps LangChain's evidence-derived fallback for omitted/null confidence.
        # This exception never supplies or exempts an extraction field, or a stated zero.
        value = {k: v for k, v in value.items() if k != 'confidence'}
        schema = {**schema, 'properties': {k: v for k, v in schema.get('properties', {}).items()
                                         if k != 'confidence'},
                  'required': [k for k in schema.get('required', []) if k != 'confidence']}
    def valid(item: Any, spec: dict[str, Any]) -> bool:
        if 'enum' in spec and item not in spec['enum']:
            return False
        types = spec.get('type')
        types = [types] if isinstance(types, str) else types
        checks = {'null': lambda x: x is None, 'string': lambda x: isinstance(x, str),
                  'array': lambda x: isinstance(x, list), 'object': lambda x: isinstance(x, dict),
                  'number': lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
                  'integer': lambda x: isinstance(x, int) and not isinstance(x, bool),
                  'boolean': lambda x: isinstance(x, bool)}
        if types and not any(t in checks and checks[t](item) for t in types):
            return False
        if isinstance(item, list):
            if len(item) > spec.get('maxItems', float('inf')):
                return False
            if 'items' in spec and not all(valid(v, spec['items']) for v in item):
                return False
        if isinstance(item, dict):
            props = spec.get('properties', {})
            if any(k not in item for k in spec.get('required', [])):
                return False
            if spec.get('additionalProperties') is False and set(item) - set(props):
                return False
            if any(k in props and not valid(v, props[k]) for k, v in item.items()):
                return False
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if not math.isfinite(item):
                return False
            if item < spec.get('minimum', float('-inf')) or item > spec.get('maximum', float('inf')):
                return False
        return True
    return valid(value, schema)
