"""Read-only, source-bound annotation coverage for the offline EDA notebook.

Coverage counts document/field pairs, not model scores. Overlay application delegates to
exactly the preparation functions used by runs; no label values are inferred from filenames.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from mailroom_sandbox import gold_labels as gl
from mailroom_sandbox import interim_labels as il
from mailroom_sandbox.paths import repo_root


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshots() -> tuple[dict, dict, list[dict]]:
    """Read and validate fresh overlay snapshots; refuse mixed or invalid exports."""
    interim, isha, problems = il.overlay_snapshot()
    if problems:
        raise ValueError(f"Interim overlay invalid: {problems[0]}")
    near, nsha, problems = gl.near_gold_snapshot()
    if problems:
        raise ValueError(f"Near-gold overlay invalid: {problems[0]}")
    sources = []
    for folder, sha in ((il.overlay_dir(), isha), (gl.gold_overlay_dir(), nsha)):
        manifest = folder / 'MANIFEST.json'
        data = json.loads(manifest.read_bytes())
        if digest(manifest) != sha:
            raise ValueError('Overlay changed during inspection; rerun the notebook')
        if folder == gl.gold_overlay_dir():
            catalog_manifest = gl.gold_dir() / 'MANIFEST.json'
            if data.get('catalog_manifest_sha256') != digest(catalog_manifest):
                raise ValueError('Near-gold export is stale relative to the catalog; rebuild the overlay')
        sources.append({'path': str(manifest.relative_to(repo_root())), 'sha256': sha})
        for name, expected in sorted((data.get('files') or {}).items()):
            path = folder / name
            if digest(path) != expected:
                raise ValueError('Overlay changed during inspection; rerun the notebook')
            sources.append({'path': str(path.relative_to(repo_root())), 'sha256': expected})
        for entry in data.get('reviews') or []:
            path = repo_root() / entry['path']
            if digest(path) != entry['sha256']:
                raise ValueError('Overlay review changed during inspection; rerun the notebook')
            sources.append({'path': entry['path'], 'sha256': entry['sha256']})
    return interim, near, sources


def catalog(store: str = "gold") -> tuple[list[dict], list[dict]]:
    """Read current catalog and supplementary store for status/evidence inspection."""
    if store not in ('gold', 'gold-supplementary'):
        raise ValueError('Unknown label store')
    folder = repo_root() / 'data/labels' / store
    manifest_path = folder / 'MANIFEST.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    problems = gl.verify_catalog(folder)
    if problems:
        raise ValueError(f'{store} catalog invalid: {problems[0]}')
    records = []
    sources = [{'path': str(manifest_path.relative_to(repo_root())),
                'sha256': hashlib.sha256(manifest_bytes).hexdigest()}]
    for name, expected in sorted((manifest.get('files') or {}).items()):
        path = folder / name
        blob = path.read_bytes()
        if hashlib.sha256(blob).hexdigest() != expected:
            raise ValueError('Catalog changed during inspection; rerun the notebook')
        sources.append({'path': str(path.relative_to(repo_root())),
                        'sha256': hashlib.sha256(blob).hexdigest()})
        if path.suffix == '.jsonl':
            records.extend(json.loads(line) for line in blob.splitlines() if line.strip())
    if manifest_path.read_bytes() != manifest_bytes:
        raise ValueError('Catalog changed during inspection; rerun the notebook')
    return records, sources


def cached_corpus() -> tuple[list[dict], list[dict], str | None]:
    """Read pinned Hub shards strictly from the local HF cache, or explain the prerequisite."""
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return [], [], 'huggingface_hub is unavailable; install the notebook dependencies to read a pinned cache.'
    from mailroom_sandbox import corpus
    from mailroom_sandbox.job.spec import DatasetSpec, FAMILY_HF_REVISION

    spec = DatasetSpec(provider='huggingface', revision=FAMILY_HF_REVISION, split='all')
    parts, sources = {}, []
    for split in ('train', 'test'):
        for config in ('default', 'ground_truth'):
            name = f'parquet/{config}/{split}/{split}-00000-of-00001.parquet'
            try:
                path = Path(hf_hub_download(spec.repo, name, revision=FAMILY_HF_REVISION,
                                            repo_type='dataset', local_files_only=True))
            except Exception:  # cache miss: repository-only analysis remains available
                return [], [], (f'Pinned corpus cache unavailable: {spec.repo}@{FAMILY_HF_REVISION}; '
                                'populate all default and ground_truth train/test shards beforehand '
                                'with sandbox datasets pull. This notebook never downloads.')
            parts[(config, split)] = corpus._read_parquet(path)
            sources.append({'path': f'{spec.repo}@{FAMILY_HF_REVISION}/{name}', 'sha256': digest(path)})
    rows = []
    for split in ('train', 'test'):
        merged = corpus.merge_default_and_gt(parts[('default', split)], parts[('ground_truth', split)])
        for row in merged:
            row['split'] = split
        rows.extend(merged)
    ids = [str(r.get('document_id') or r.get('id')) for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate corpus document IDs; refusing ambiguous coverage')
    return corpus.normalize_rows(rows), sources, None


def stages(rows: list[dict], interim: Mapping, near: Mapping, isha: str, nsha: str) -> dict[str, list[dict]]:
    """Apply each layer once, preserving the actual correction and SHF-010 rules."""
    mid = [il.apply_overlay(row, interim, overlay_sha=isha) for row in rows]
    final = [gl.apply_near_gold(row, near, overlay_sha=nsha, interim=interim) for row in mid]
    return {'hub': rows, 'interim': mid, 'near_gold': final}


def presence(exp: Mapping, field: str) -> str:
    code = il._presence(exp).get(field)
    if code and code != 'populated':
        return 'absence' if code == 'schema_documented_absence' else 'other_presence'
    value = exp.get(field)
    if value in (None, '', [], {}, '[]', '{}', 'nan'):
        return 'missing'
    return 'populated'


def schema_fields(cls: str, subclass: str) -> dict[str, dict[str, Any]]:
    """Registered fields and actual request-schema intersection, including mismatches."""
    from llm_dojo_scoring.schemas.extraction_schemas import extraction_schema
    from schemas.documents import get_extraction_schema
    from mailroom_sandbox.subclass_schemas import _subclass_of

    sub = _subclass_of(cls, subclass)
    registered = extraction_schema(cls, sub).fields
    if cls == 'corporate_record':
        from llm_dojo_scoring.schemas import corporate_record_schema as crs
        from mailroom_sandbox.corporate_extraction import request_schema
        corp = crs.subclass_schema(sub)
        output = set(request_schema(sub, {})['properties'])
        entities = {e.key for e in corp.entities}
        applicable = lambda f: f in entities or f in corp.core_applicable or f not in crs.CORE_FIELDS  # noqa: E731
    else:
        output = set(get_extraction_schema(cls).model_fields) - {'confidence', 'reasoning'}
        applicable = lambda f: True  # noqa: E731
    return {f: {'dojo_status': registered[f].status if f in registered else 'unregistered',
                'applicable': applicable(f) and (f not in registered or registered[f].status != 'not_applicable'),
                'emittable': f in output, 'registered': f in registered}
            for f in sorted(set(registered) | output)}


def coverage_rows(stage_rows: Mapping[str, list[dict]]) -> list[dict]:
    """One row per registered document/field; counts are unique by construction."""
    from mailroom_sandbox.subclass_schemas import CLASSES

    output = []
    schemas = {}
    for stage, rows in stage_rows.items():
        for row in rows:
            cls = row.get('expected_doc_class')
            if cls not in CLASSES:
                continue
            sub = row.get('expected_subclass') or 'other'
            key = (cls, sub)
            if key not in schemas:
                schemas[key] = schema_fields(cls, sub)
            exp = il._expected(row)
            for field, flags in schemas[key].items():
                near_fields = (row.get('near_gold_labels') or {}).get('fields') or []
                interim_fields = (row.get('interim_labels') or {}).get('fields') or []
                state = presence(exp, field)
                source = ('near_gold' if field in near_fields else 'interim' if field in interim_fields
                          else 'none' if state == 'missing' else 'hub')
                output.append({'stage': stage, 'doc_id': row['id'], 'class': cls, 'subclass': sub,
                               'field': field, 'presence': state, 'source': source, **flags})
    return output


def overlay_inventory(overlay: Mapping, source: str) -> list[dict]:
    """Include non-admitted/disputed labels as inventory, never as effective truth."""
    result = []
    for doc_id, rec in sorted(overlay.items()):
        for field, lab in sorted((rec.get('labels') or {}).items()):
            result.append({'source': source, 'doc_id': doc_id, 'class': rec.get('doc_class'),
                           'subclass': rec.get('doc_subclass'), 'field': field,
                           'status': lab.get('status'), 'basis': lab.get('basis'),
                           'presence': lab.get('presence'), 'use_as_truth': lab.get('use_as_truth'),
                           'evidence': lab.get('evidence'), 'doc_sha256': rec.get('doc_sha256'),
                           'value': lab.get('value')})
    return result


def inventory_summary(records: list[dict]) -> list[dict]:
    counts = Counter((r.get('source'), r.get('status'), r.get('presence'), r.get('basis')) for r in records)
    return [{'source': s, 'status': st, 'presence': p, 'basis': b, 'fields': n}
            for (s, st, p, b), n in sorted(counts.items(), key=lambda item: str(item[0]))]
