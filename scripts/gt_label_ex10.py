"""Label the v9.1 SEC EDGAR EX-10 gap in CUAD span form.

One invocation sends one chunk (at most 40 documents) to the deployed
``sandbox-vllm-gt-labeler`` app. Re-running continues the unfinished
filenames in the output JSONL. Spans that are not verbatim slices of the
filing are dropped. A document with fewer than four recovered categories
is retried once, then held out of the accepted file.

    VLLM_API_KEY=... python scripts/gt_label_ex10.py \\
        --queue ../Mailroom-Corpus-EDA/docs/reports/audits/gt_backfill_queue.jsonl \\
        --parquet ../Mailroom-Corpus-EDA/data/parquet \\
        --out reports/gt-labeler/ex10-cuad-labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mailroom_sandbox.gt_labeler import (  # noqa: E402
    CHUNK_DOC_CAP,
    CHUNK_USD_CAP,
    DATASET_REVISION,
    DATASET_TAG,
    MAX_NUM_SEQS,
    POSTURE,
    accepted_ids,
    build_cuad_messages,
    cuad_label_problems,
    cuad_span_schema,
    fold_label_journal,
    gpu_rate_usd_per_hour,
    label_evidence_for,
    loads_response,
    next_chunk,
    normalize_cuad_labels,
)

_WRITE_LOCK = threading.Lock()

# Leave room under the 32k window for the instruction and a 4k decode.
_WINDOW_TOKEN_FLOOR = 24_000
_MAX_TOKENS = 4096
_HTTP_TIMEOUT = 1800
_WALL_CAP_SECONDS = 45 * 60


def _load_queue(path: Path) -> list[dict]:
    """Read the labeling queue JSONL into a list of row dicts."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _read_config(parquet_dir: Path, cfg: str):
    """Concatenate one parquet config's train and test files; an empty frame if none exist."""
    import pandas as pd

    frames = []
    for split in ("train", "test"):
        folder = parquet_dir / cfg / split
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.parquet")):
            frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _clean_cell(value: object) -> str:
    """A parquet cell as a stripped string, with None/NaN/``nan``/``None``/``null`` as ``""``
    and integral floats without a trailing ``.0``.
    """
    if value is None:
        return ""
    if isinstance(value, float):
        if value != value:
            return ""
        if value.is_integer():
            return str(int(value))
    text = str(value).strip()
    if text in ("nan", "None", "null"):
        return ""
    return text


def _load_texts(parquet_dir: Path, filenames: set[str]) -> dict[str, dict]:
    """Map each queued filename to its doc_text, token estimate, document_id and split.

    Reads ``gt_fields`` from the ground_truth config and doc_text from the blind
    config when present. Raises ``FileNotFoundError`` without a ground_truth
    snapshot and ``RuntimeError`` when a queued filename has no text or an
    empty one.
    """
    ground = _read_config(parquet_dir, "ground_truth")
    blind = _read_config(parquet_dir, "default")
    if ground.empty or "gt_fields" not in ground.columns:
        raise FileNotFoundError(f"ground_truth snapshot missing under {parquet_dir}")
    parsed = ground["gt_fields"].apply(
        lambda value: json.loads(value) if isinstance(value, str) and value.strip() else {}
    )
    expanded = __import__("pandas").DataFrame(parsed.tolist(), index=ground.index)
    flat = __import__("pandas").concat(
        [ground.drop(columns=["gt_fields"]), expanded], axis=1
    )
    flat = flat.loc[:, ~flat.columns.duplicated(keep="last")]
    if not blind.empty:
        flat = flat.drop(columns=[c for c in ("doc_text", "metadata") if c in flat.columns])
        flat = flat.merge(
            blind[["filename", "doc_text", "metadata"]],
            on="filename",
            how="left",
        )
    wanted = flat[flat["filename"].isin(filenames)]
    out: dict[str, dict] = {}
    for row in wanted.to_dict("records"):
        name = _clean_cell(row.get("filename"))
        if name not in filenames:
            continue
        out[name] = {
            "doc_text": "" if row.get("doc_text") is None else str(row.get("doc_text")),
            "token_estimate": _clean_cell(row.get("token_estimate")),
            "document_id": _clean_cell(row.get("document_id")),
            "split": _clean_cell(row.get("split")),
        }
    missing = filenames - set(out)
    if missing:
        raise RuntimeError(f"{len(missing)} queue filenames have no filing text")
    empty = [name for name, info in out.items() if not info["doc_text"].strip()]
    if empty:
        raise RuntimeError(f"{len(empty)} filings have empty doc_text")
    return out


def _read_journal(path: Path) -> list[dict]:
    """Every record in the append-only journal, in write order; ``[]`` if it does not exist."""
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append_journal(path: Path, record: dict) -> None:
    """Append one finished document and fsync before returning.

    The journal is append-only. A killed process keeps every line that
    reached this function. Resume reads the same file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _write_checkpoint(path: Path, journal: Path, queue_ids: list[str]) -> None:
    """Atomically replace the checkpoint after every saved document."""
    folded = fold_label_journal(_read_journal(journal))
    done = [key for key in queue_ids if folded.get(key, {}).get("accepted")]
    remaining = [key for key in queue_ids if key not in set(done)]
    payload = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "journal": journal.name,
        "queue": len(queue_ids),
        "accepted": len(done),
        "remaining": len(remaining),
        "next_filenames": remaining[:CHUNK_DOC_CAP],
        "documents": {
            key: {
                "accepted": bool(row.get("accepted")),
                "present_categories": row.get("present_categories"),
                "span_count": row.get("span_count"),
                "problems": row.get("problems") or [],
            }
            for key, row in folded.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _save(out: Path, checkpoint: Path, queue_ids: list[str], record: dict) -> None:
    """Append one finished record and refresh the checkpoint, under the write lock."""
    with _WRITE_LOCK:
        _append_journal(out, record)
        _write_checkpoint(checkpoint, out, queue_ids)


def _post(url: str, api_key: str, body: dict) -> dict:
    """POST ``body`` to ``<url>/chat/completions`` with the bearer key; return the JSON reply.

    Raises ``ValueError`` for a non-http(s) URL; HTTP errors propagate.
    """
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError(f"base URL must be http(s), got {url!r}")
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url.rstrip("/") + "/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def _complete(url: str, api_key: str, messages: list[dict], schema: dict) -> str:
    """One deterministic chat completion constrained to the CUAD span schema.

    Temperature 0, thinking off, served model pinned to the posture. On an HTTP
    400/422 (schema not accepted) it retries once with plain JSON mode. Other
    HTTP errors become ``RuntimeError``, and so does a reply cut off at
    ``max_tokens``. Returns the message content.
    """
    body = {
        "model": POSTURE["MODAL_VLLM_MODEL"],
        "messages": messages,
        "temperature": 0,
        "max_tokens": _MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "cuad_spans", "strict": True, "schema": schema},
        },
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        payload = _post(url, api_key, body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in (400, 422):
            body.pop("response_format", None)
            body["response_format"] = {"type": "json_object"}
            payload = _post(url, api_key, body)
        else:
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    choice = payload["choices"][0]
    finish = choice.get("finish_reason")
    content = choice["message"]["content"]
    if finish == "length":
        raise RuntimeError("decode hit max_tokens")
    return content


def _annotate(target: dict, url: str, api_key: str, schema: dict) -> dict:
    """Label one target and return its journal record.

    Up to two attempts: spans are normalized to verbatim document slices, and if
    the quality floor fails the model is told the problems and asked again. The
    record is ``accepted`` only when the final attempt clears the floor.
    """
    document = str(target.get("doc_text") or "")
    messages = build_cuad_messages(target)
    last_dropped: list[str] = []
    last_problems: list[str] = []
    labels: dict = {}
    for attempt in (1, 2):
        content = _complete(url, api_key, messages, schema)
        payload = loads_response(content)
        labels, last_dropped = normalize_cuad_labels(document, payload)
        last_problems = cuad_label_problems(labels)
        if not last_problems:
            break
        messages = messages + [
            {"role": "assistant", "content": content},
            {
                "role": "user",
                "content": (
                    "Those spans were not accepted. "
                    + "; ".join(last_problems)
                    + ". Return only short excerpts copied from the filing, "
                    "and include Document Name and Parties when they are printed."
                ),
            },
        ]
    present = sum(1 for spans in labels.values() if spans)
    accepted = not last_problems
    return {
        "id": target["id"],
        "filename": target["filename"],
        "document_id": target.get("document_id") or "",
        "split": target.get("split") or "",
        "doc_class": "contract",
        "expected_subclass": target.get("expected_subclass") or "",
        "source_dataset": "sec_edgar",
        "dataset_tag": DATASET_TAG,
        "dataset_revision": DATASET_REVISION,
        "model": POSTURE["MODAL_VLLM_MODEL"],
        "windowed": bool(target.get("_windowed")),
        "accepted": accepted,
        "present_categories": present,
        "span_count": sum(len(spans) for spans in labels.values()),
        "dropped": len(last_dropped),
        "problems": last_problems,
        "cuad_clause_labels": labels,
        "label_evidence": label_evidence_for(labels),
        "clause_count": "41" if accepted else "",
        "attempts": attempt,
    }


def _prepare(queue: list[dict], texts: dict[str, dict]) -> list[dict]:
    """Join queue rows with their texts into label targets.

    Every target is shaped as a SEC EDGAR EX-10 ``cuad_clause_labels`` target
    (``source_dataset = sec_edgar``), so the golden-field guard does not block
    it. The calibration queue relies on this: its golden CUAD rows are labeled
    into a separate journal that the EDA side scores and never ingests. A
    target whose token estimate exceeds the window floor is marked ``>32k`` and
    windowed.
    """
    prepared = []
    for row in queue:
        name = row["filename"]
        info = texts[name]
        estimate = info.get("token_estimate") or ""
        band = str(row.get("context_window_band") or "")
        windowed = False
        try:
            if float(estimate) > _WINDOW_TOKEN_FLOOR:
                band = ">32k"
                windowed = True
        except ValueError:
            pass
        if band == ">32k":
            windowed = True
        prepared.append({
            **row,
            "doc_text": info["doc_text"],
            "document_id": info.get("document_id") or "",
            "split": row.get("split") or info.get("split") or "",
            "context_window_band": band,
            "fields": ["cuad_clause_labels"],
            "doc_class": "contract",
            "source_corpus": "sec_edgar",
            "source_dataset": "sec_edgar",
            "_windowed": windowed,
        })
    return prepared


def main() -> int:
    """Label one chunk (by default) of the queue and append the results to ``--out``.

    Resumes using accepted journal records and refreshes a checkpoint beside
    the journal. Estimated GPU spend and the 45-minute wall limit are checked
    between chunks, so a running chunk can exceed either limit. Individual
    annotation errors are saved as rejected records; input, planning, and
    journal errors can propagate.

    Returns 2 if the base URL (``--base-url`` or ``VLLM_BASE_URL``) or
    ``VLLM_API_KEY`` is missing, or if ``--replicas`` is less than 1; otherwise
    returns 0, including when records are rejected.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--limit-chunks", type=int, default=1)
    parser.add_argument("--max-docs", type=int, default=0, help="slice the chunk; 0 sends the whole chunk")
    parser.add_argument(
        "--replicas",
        type=int,
        default=1,
        help="GPUs to keep busy. The posture deploys one H100 (8 sequences); keep 1",
    )
    parser.add_argument(
        "--usd-cap",
        type=float,
        default=CHUNK_USD_CAP,
        help="stop before the next chunk when estimated GPU spend reaches this",
    )
    args = parser.parse_args()
    import os

    base = (args.base_url or os.environ.get("VLLM_BASE_URL") or "").rstrip("/")
    api_key = os.environ.get("VLLM_API_KEY") or ""
    if not base or not api_key:
        print("VLLM_BASE_URL and VLLM_API_KEY are required", file=sys.stderr)
        return 2
    if not base.endswith("/v1"):
        base += "/v1"

    queue = _load_queue(args.queue)
    texts = _load_texts(args.parquet, {row["filename"] for row in queue})
    prepared = _prepare(queue, texts)
    queue_ids = [row["id"] for row in prepared]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.out.with_name(args.out.stem + "-checkpoint.json")
    schema = cuad_span_schema()
    if args.replicas < 1:
        print("replicas must be >= 1", file=sys.stderr)
        return 2
    in_flight = args.replicas * MAX_NUM_SEQS
    already = accepted_ids(_read_journal(args.out))
    print(
        f"resume journal={args.out} accepted={len(already)} "
        f"remaining={len(queue_ids) - len(already)} "
        f"replicas={args.replicas} in_flight={in_flight} "
        f"usd_cap={args.usd_cap:.2f}",
        flush=True,
    )
    _write_checkpoint(checkpoint, args.out, queue_ids)
    started = time.time()
    written = 0
    for _ in range(args.limit_chunks):
        elapsed = time.time() - started
        spent = elapsed / 3600.0 * gpu_rate_usd_per_hour() * args.replicas
        if elapsed > _WALL_CAP_SECONDS or spent >= args.usd_cap:
            print(
                f"stopping before the next chunk: est ${spent:.2f} "
                f"after {elapsed:.0f}s (cap ${args.usd_cap:.2f})",
                flush=True,
            )
            break
        done = accepted_ids(_read_journal(args.out))
        chunk = next_chunk(prepared, done)
        if chunk is None:
            print("queue empty")
            break
        print(
            f"chunk {chunk.index} docs={chunk.doc_count} "
            f"projected_usd={chunk.projected_usd:.2f} cap={CHUNK_DOC_CAP}",
            flush=True,
        )
        targets = list(chunk.targets)
        if args.max_docs > 0:
            targets = targets[:args.max_docs]

        def _safe(target: dict) -> dict:
            """Run :func:`_annotate`, turning any exception into a rejected record so one
            failure never sinks the chunk.
            """
            try:
                return _annotate(target, base, api_key, schema)
            except Exception as exc:
                return {
                    "id": target["id"],
                    "filename": target["filename"],
                    "document_id": target.get("document_id") or "",
                    "split": target.get("split") or "",
                    "accepted": False,
                    "present_categories": 0,
                    "span_count": 0,
                    "dropped": 0,
                    "problems": [f"{type(exc).__name__}: {exc}"[:400]],
                    "cuad_clause_labels": {},
                    "label_evidence": "",
                    "clause_count": "",
                    "attempts": 0,
                    "dataset_tag": DATASET_TAG,
                    "model": POSTURE["MODAL_VLLM_MODEL"],
                }

        with ThreadPoolExecutor(max_workers=in_flight) as pool:
            futures = [pool.submit(_safe, target) for target in targets]
            for future in as_completed(futures):
                record = future.result()
                record["saved_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                _save(args.out, checkpoint, queue_ids, record)
                written += 1
                print(
                    f"  saved {record['filename']} accepted={record['accepted']} "
                    f"present={record['present_categories']} "
                    f"spans={record['span_count']} dropped={record['dropped']}",
                    flush=True,
                )
    folded = fold_label_journal(_read_journal(args.out))
    ok = sum(1 for row in folded.values() if row.get("accepted") and row.get("filename"))
    print(f"wrote {written} this run; journal has {ok}/{len(queue_ids)} accepted")
    print(f"checkpoint {checkpoint}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
