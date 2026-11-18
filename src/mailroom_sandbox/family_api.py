"""One programmatic surface over the two family packages: the mailroom HTTP API and the Dojo.

``sandbox api status`` and ``sandbox api eval`` are thin wrappers over this module, and
notebooks or scripts can import it directly:

- :class:`MailroomAPI` is a typed client for a running mailroom API (the vendored
  ``sandbox pipeline api`` on loopback, or a deployed instance named by
  ``MAILROOM_API_URL``). It covers the endpoints an evaluation needs: ``/health``,
  ``/upload``, ``/lookup``, ``/status``, ``/queue``, ``/audit`` and ``/ops/status``.
  URL validation and the bearer token come from :mod:`mailroom_sandbox.review_cli`, so
  ``sandbox review`` and this client accept the same settings and never print the token.
- :func:`family_status` reports which mailroom and Dojo the sandbox resolves (pinned
  snapshot versus the selected source) next to what the API answers.
- :func:`run_api_eval` drives documents through a running API and scores what comes
  back with the selected Dojo, through the same scorers as ``sandbox eval pipeline``
  (:func:`mailroom_sandbox.eval.scoring.score_classification` and the per-row
  extraction scorer). Classification is comparable with an in-process run; extraction is
  scored on archived documents only (see :func:`run_api_eval`).

The client only uploads and reads. Model calls happen inside the API process, which
holds its own provider settings and spend; this module cannot see or cap that spend, so
``sandbox api eval`` plans by default and submits only with ``--submit``.
"""

from __future__ import annotations

import math
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx

from mailroom_sandbox import review_cli
from mailroom_sandbox.services._exec import ServiceError

TERMINAL_STAGES = frozenset({"archived", "review", "failed"})
HEALTH_TIMEOUT = 15.0
READ_TIMEOUT = 30.0
UPLOAD_TIMEOUT = 120.0
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_DOC_TIMEOUT = 600.0
DEFAULT_MATTER_ID = "SANDBOX-API-EVAL"
MIN_POLL_SECONDS = 0.2
# The API's /upload is rate limited (MAILROOM_UPLOAD_RATE per 60 s window, audit L-18).
RATE_LIMIT_BACKOFF_SECONDS = 30.0
RATE_LIMIT_RETRIES = 4
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class FamilyAPIError(ServiceError):
    """The mailroom API was unreachable, refused a request, or answered off-contract."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _default_transport() -> httpx.BaseTransport | None:
    """None means httpx's own transport; tests patch this to route CLI calls to a fake API."""
    return None


class MailroomAPI:
    """Client for one mailroom API instance.

    ``base_url`` and ``token`` default to ``MAILROOM_API_URL`` / ``MAILROOM_API_TOKEN``
    (the same validation as ``sandbox review``). ``transport`` exists for tests
    (``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # An explicit URL gets the same check as MAILROOM_API_URL: no embedded credentials,
        # query or fragment, so nothing secret can reach an error message or a report.
        self.base_url = review_cli.check_api_url(base_url) if base_url else review_cli.api_url()
        self._token = token if token is not None else review_cli._token()
        self._transport = transport if transport is not None else _default_transport()

    def _client(self, timeout: float) -> httpx.Client:
        review_cli._warn_plain_http_token(self.base_url, self._token)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        return httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout, transport=self._transport)

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float = READ_TIMEOUT,
        params: Mapping[str, Any] | None = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        try:
            with self._client(timeout) as client:
                resp = client.request(method, path, params=params, files=files, data=data)
        except httpx.TimeoutException:
            raise FamilyAPIError(f"the mailroom API at {self.base_url} did not answer {method} {path} "
                                 f"within {timeout:g}s") from None
        except httpx.HTTPError:
            raise FamilyAPIError(f"cannot reach the mailroom API at {self.base_url}; start it with "
                                 "`sandbox pipeline api` or set MAILROOM_API_URL") from None
        if allow_404 and resp.status_code == 404:
            return None
        if resp.status_code == 401:
            hint = "check MAILROOM_API_TOKEN" if self._token else "set MAILROOM_API_TOKEN"
            raise FamilyAPIError(f"the API rejected {method} {path} (HTTP 401): {hint}", status_code=401)
        if resp.status_code >= 400:
            detail = review_cli._detail(resp, self._token)
            raise FamilyAPIError(review_cli._scrub(
                f"HTTP {resp.status_code} from {self.base_url} for {method} {path}: {detail}", self._token),
                status_code=resp.status_code)
        try:
            return resp.json()
        except ValueError:
            raise FamilyAPIError(f"{self.base_url} returned a non-JSON response for {method} {path}") from None

    def health(self) -> dict[str, Any]:
        body = self._request("GET", "/health", timeout=HEALTH_TIMEOUT)
        if not isinstance(body, dict) or "status" not in body:
            raise FamilyAPIError("unexpected /health response: no 'status'")
        return body

    def upload(self, path: Path, *, matter_id: str = DEFAULT_MATTER_ID, filename: str | None = None) -> dict[str, Any]:
        """Queue one file. Returns the API's 202 payload; ``file`` is the inbox name it was given."""
        name = filename or path.name
        with path.open("rb") as fh:
            body = self._request("POST", "/upload", timeout=UPLOAD_TIMEOUT,
                                 files={"file": (name, fh)}, data={"matter_id": matter_id})
        if not isinstance(body, dict) or not body.get("file"):
            raise FamilyAPIError("unexpected /upload response: no 'file'")
        return body

    def lookup(self, *, doc_id: str | None = None, filename: str | None = None,
               trace_id: str | None = None) -> dict[str, Any] | None:
        """The catalog document for one id/filename, or None while the API has not seen it yet."""
        params = {k: v for k, v in (("doc_id", doc_id), ("filename", filename), ("trace_id", trace_id)) if v}
        if not params:
            raise ValueError("lookup needs doc_id, filename or trace_id")
        body = self._request("GET", "/lookup", params=params, allow_404=True)
        if body is None:
            return None
        doc = body.get("document") if isinstance(body, dict) else None
        if not isinstance(doc, dict):
            raise FamilyAPIError("unexpected /lookup response: no 'document'")
        return doc

    def status(self, doc_id: str) -> dict[str, Any]:
        return self._request("GET", f"/status/{_doc_id(doc_id)}")

    def queue(self) -> dict[str, Any]:
        return self._request("GET", "/queue")

    def audit(self, doc_id: str) -> dict[str, Any]:
        return self._request("GET", f"/audit/{_doc_id(doc_id)}")

    def ops_status(self) -> dict[str, Any]:
        return self._request("GET", "/ops/status")


def _doc_id(doc_id: str) -> str:
    """The API's own doc_id rule; refuse anything else before it reaches a URL path."""
    if not _DOC_ID_RE.match(doc_id or ""):
        raise ValueError("doc_id must match [A-Za-z0-9_-]")
    return doc_id


# --------------------------------------------------------------------------- status


def family_status(api: MailroomAPI | None = None) -> dict[str, Any]:
    """What the sandbox resolves for each family package, plus the API's health when reachable.

    Nothing here imports pipeline modules or changes ``sys.path`` beyond the source
    selection the sandbox already performs for every run.
    """
    from mailroom_sandbox import dojo_source, pipeline_source

    out: dict[str, Any] = {
        "mailroom": {"pinned": pipeline_source.pinned(), "selected": _as_dict(_safe(pipeline_source.choose))},
        "dojo": {"pinned": dojo_source.pinned(), "selected": _as_dict(_safe(dojo_source.choose))},
    }
    if api is not None:
        try:
            health = api.health()
            out["api"] = {"url": api.base_url, "reachable": True, "status": health.get("status"),
                          "checks": health.get("checks", {})}
        except FamilyAPIError as exc:
            out["api"] = {"url": api.base_url, "reachable": False, "error": str(exc)}
    return out


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — a status report must not die on one probe
        return {"error": f"{type(exc).__name__}: {exc}"}


def _as_dict(value: Any) -> Any:
    return value.as_dict() if hasattr(value, "as_dict") else value


# --------------------------------------------------------------------------- eval


def _expected_class(row: Mapping[str, Any]) -> str:
    return str(row.get("expected_doc_class") or row.get("doc_type") or "")


def plan_api_eval(rows: Sequence[Mapping[str, Any]], *, base_url: str) -> dict[str, Any]:
    from mailroom_sandbox.datasets import dataset_fingerprint

    return {
        "task": "api_eval",
        "api_url": base_url,
        "n": len(rows),
        "fingerprint": dataset_fingerprint(list(rows)),
        "classes": sorted({_expected_class(r) for r in rows}),
        "submit": False,
        "note": "plan only: pass --submit to upload. Model calls run inside the API process "
                "and spend with its provider settings, which this client cannot cap.",
    }


def _normalized_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """A copy whose expected class sits under ``expected_doc_class`` (the scorers index it)."""
    out = dict(row)
    out["expected_doc_class"] = _expected_class(row)
    return out


#: Text suffixes the mailroom API's ``/upload`` accepts by default (``file_extensions``).
_UPLOAD_TEXT_SUFFIXES = frozenset({".txt", ".md"})


def _upload_ready(path: Path, row: Mapping[str, Any]) -> Path:
    """Give an inline-text row a suffix the API accepts.

    Corpus rows carry the extracted text inline under their source name (``x.htm``,
    ``y.html``, ``.eml``, ``.json``, ``.csv``); the in-process runner reads those as text,
    but the API's upload allow list refuses every one of them (HTTP 400), which stopped
    the eval at the first such document.
    The bytes are already plain text, so they are uploaded as ``.txt``.
    """
    if (row.get("doc_text") or row.get("text")) and path.suffix.lower() not in _UPLOAD_TEXT_SUFFIXES:
        renamed = path.with_name(path.name + ".txt")
        path.rename(renamed)
        return renamed
    return path


def _upload_with_backoff(api: MailroomAPI, path: Path, *, matter_id: str, filename: str,
                         sleep: Callable[[float], None]) -> dict[str, Any]:
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        try:
            return api.upload(path, matter_id=matter_id, filename=filename)
        except FamilyAPIError as exc:
            if exc.status_code != 429 or attempt == RATE_LIMIT_RETRIES:
                raise
            sleep(RATE_LIMIT_BACKOFF_SECONDS)
    raise AssertionError("unreachable")  # pragma: no cover


def run_api_eval(
    rows: Sequence[Mapping[str, Any]],
    api: MailroomAPI,
    *,
    matter_id: str = DEFAULT_MATTER_ID,
    doc_timeout: float = DEFAULT_DOC_TIMEOUT,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    run_tag: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Upload ``rows``, wait for each to reach a terminal stage, and score the results.

    Each upload is renamed ``<run_tag>-<name>`` so a document from an earlier run with
    the same file name is never mistaken for this run's result (the API looks up by
    inbox name, and Langfuse trace ids are deterministic per file name).

    What is scored, and how it differs from ``sandbox eval pipeline``:

    - classification covers every document that reached a terminal stage; a ``failed``
      document with no class counts as ``unknown`` (wrong), never as skipped;
    - stage correctness (``score_stage``) covers terminal documents whose row names an
      ``expected_stage``;
    - extraction covers ``archived`` documents only (a parked or failed document has no
      final extraction to read back), so its mean is over archived documents, unlike the
      in-process run, which scores every row with field ground truth.

    Documents still unfinished ``doc_timeout`` seconds after the last upload are listed
    under ``incomplete`` and are not scored. ``ok`` is False when any document is
    incomplete or failed, or when the API errored mid-run; then ``error`` says why and
    the report still lists every document that was accepted, so nothing uploaded is lost.
    An upload refused with HTTP 429 (the API's upload rate limit) is retried after a
    back-off.
    """
    from mailroom_sandbox.eval import scoring
    from mailroom_sandbox.eval.runners import _materialize_row, _score_pipeline_extraction

    poll_seconds, doc_timeout = float(poll_seconds), float(doc_timeout)
    if not (math.isfinite(poll_seconds) and math.isfinite(doc_timeout)):
        # NaN slips past max() and every deadline comparison; inf would sleep forever.
        raise ValueError("poll_seconds and doc_timeout must be finite numbers")
    poll_seconds = max(poll_seconds, MIN_POLL_SECONDS)
    doc_timeout = max(doc_timeout, 0.0)
    tag = run_tag or f"apieval-{uuid.uuid4().hex[:8]}"
    started = clock()
    health = api.health()
    error: str | None = None
    pending: dict[str, dict[str, Any]] = {}
    per_doc: list[dict[str, Any]] = []
    unconfirmed: str | None = None
    with tempfile.TemporaryDirectory(prefix="sandbox-api-eval-") as tmp:
        used_names: set[str] = set()
        for index, raw in enumerate(rows):
            row = _normalized_row(raw)
            local = _upload_ready(_materialize_row(row, Path(tmp)), row)
            if local.name in used_names:
                # ``filing.htm`` and ``filing.htm.txt`` both upload as ``filing.htm.txt``; the API
                # answers by inbox name, so a repeat would overwrite the first row's pending entry.
                local = local.rename(local.with_name(f"{index:04d}-{local.name}"))
            used_names.add(local.name)
            try:
                accepted = _upload_with_backoff(api, local, matter_id=matter_id,
                                                filename=f"{tag}-{local.name}", sleep=sleep)
            except FamilyAPIError as exc:
                error = f"upload of {local.name} failed; later rows were not sent: {exc}"
                if exc.status_code is None or exc.status_code >= 500:
                    # No answer (timeout, dropped connection) or a server error: the API may still
                    # have stored the file, so name it rather than lose track of it.
                    unconfirmed = f"{tag}-{local.name}"
                break
            entry = {"id": row.get("id"), "file": accepted["file"], "upload_id": accepted.get("upload_id"),
                     "expected_doc_class": row["expected_doc_class"], "row": row}
            pending[accepted["file"]] = entry
            per_doc.append(entry)

    deadline = clock() + doc_timeout
    lookup_failed = False
    while pending and not lookup_failed:
        for name in list(pending):
            if clock() >= deadline:
                break
            try:
                doc = api.lookup(filename=name)
            except FamilyAPIError as exc:
                lookup_error = f"lookup failed while waiting for results: {exc}"
                error = f"{error}; {lookup_error}" if error else lookup_error
                lookup_failed = True
                break
            if doc and str(doc.get("stage") or "").lower() in TERMINAL_STAGES:
                pending.pop(name)["document"] = doc
        if not pending or lookup_failed or clock() >= deadline:
            break
        sleep(poll_seconds)

    expected: list[str] = []
    predicted: list[str] = []
    stage_expected: list[str] = []
    stage_actual: list[str] = []
    extraction: list[dict[str, Any]] = []
    stages: dict[str, int] = {}
    results: list[dict[str, Any]] = []
    for entry in per_doc:
        row = entry.pop("row")
        doc = entry.pop("document", None)
        if doc is None:
            entry["stage"] = None
            results.append(entry)
            continue
        stage = str(doc.get("stage") or "").lower()
        stages[stage] = stages.get(stage, 0) + 1
        entry.update({
            "doc_id": doc.get("doc_id"),
            "stage": stage,
            "doc_type": doc.get("doc_type"),
            "classification_confidence": doc.get("classification_confidence"),
            "extraction_confidence": doc.get("extraction_confidence"),
            "escalation_reason": doc.get("escalation_reason"),
            "trace_id": doc.get("trace_id"),
        })
        expected.append(entry["expected_doc_class"])
        predicted.append(str(doc.get("doc_type") or "unknown"))
        if row.get("expected_stage"):
            stage_expected.append(str(row["expected_stage"]).lower())
            stage_actual.append(stage)
        if stage == "archived":
            score = _score_pipeline_extraction(row, {"extracted_data": doc.get("extracted_data")})
            if score is not None:
                entry["extraction"] = score
                extraction.append(score)
        results.append(entry)

    incomplete = [r["file"] for r in results if r.get("stage") is None]
    failed = [r["file"] for r in results if r.get("stage") == "failed"]
    overall = [s["overall_extraction_score"] for s in extraction
               if isinstance(s.get("overall_extraction_score"), (int, float))]
    return {
        "task": "api_eval",
        "run_tag": tag,
        "api_url": api.base_url,
        "api_health": health.get("status"),
        "family": family_status(),
        "n_rows": len(rows),
        "n": len(per_doc),
        "completed": len(per_doc) - len(incomplete),
        "incomplete": incomplete,
        "failed": failed,
        "stages": stages,
        "classification": scoring.score_classification(expected, predicted) if expected else None,
        "stage": scoring.score_stage(stage_expected, stage_actual) if stage_expected else None,
        "extraction": {"n": len(extraction), "scope": "archived documents with field ground truth",
                       "overall_extraction_score": scoring.mean_or_zero(overall) if overall else None},
        "documents": results,
        "error": error,
        "unconfirmed_upload": unconfirmed,
        "wall_seconds": round(clock() - started, 3),
        "ok": error is None and not incomplete and not failed and len(per_doc) == len(rows),
    }


# --------------------------------------------------------------------------- offline mock API


class _DrainingTransport(httpx.BaseTransport):
    """Forward to the in-process API; after each accepted upload, run that document through
    the vendored pipeline under the sandbox's mock LLM, the way the API's watcher would.

    The mock LLM answers from the row's ground truth (as in ``sandbox eval pipeline --mock``),
    so an offline run proves the wiring: client -> real API -> real graph -> catalog ->
    ``/lookup`` -> Dojo scoring. It says nothing about model quality.
    """

    def __init__(self, inner: httpx.BaseTransport, rows: Sequence[Mapping[str, Any]]) -> None:
        from mailroom_sandbox.eval.runners import _doc_source_name

        self._inner = inner
        # run_api_eval uploads the rows one at a time, in order, so the n-th accepted upload is
        # the n-th row. Matching by order (not by name) keeps duplicate names and renamed
        # suffixes on the right row; the stem check below catches a caller that passed
        # different rows here and to run_api_eval.
        self._queue = [(Path(_doc_source_name(dict(r))).stem, dict(r)) for r in rows]
        self.processed: list[dict[str, Any]] = []

    def _row_for(self, inbox_name: str) -> dict[str, Any]:
        if not self._queue:
            raise FamilyAPIError(f"mock API: upload {inbox_name!r} has no fixture row left")
        stem, row = self._queue.pop(0)
        if stem not in inbox_name:
            raise FamilyAPIError(f"mock API: upload {inbox_name!r} is not the next fixture row ({stem!r}); "
                                 "pass the same rows to offline_mock_api and run_api_eval")
        return row

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        raw = self._inner.handle_request(request)
        # Re-wrap: the test client's stream type is not the one httpx.Client accepts.
        response = httpx.Response(raw.status_code, headers=raw.headers, content=raw.read(), request=request)
        if request.method == "POST" and request.url.path == "/upload" and response.status_code == 202:
            body = response.json()
            row = self._row_for(str(body.get("file") or ""))
            self.processed.append(_mock_process(body["file"], body.get("matter_id") or DEFAULT_MATTER_ID, row))
        return response

    def close(self) -> None:
        self._inner.close()


def _mock_process(inbox_name: str, matter_id: str, row: dict[str, Any]) -> dict[str, Any]:
    from contextlib import ExitStack
    from unittest.mock import patch

    from graph.build_graph import run_pipeline  # type: ignore
    from pipeline.bins import inbox_dir, read_inbox_meta  # type: ignore
    from pipeline.config import oracle_routing_override  # type: ignore

    from mailroom_sandbox.eval.runners import _expect_from_row, _langchain_mock_patches
    from mailroom_sandbox.mock_llm import fake_client

    expect = _expect_from_row(row)
    path = inbox_dir() / inbox_name

    def _mock_get_llm(agent_name: str):
        return fake_client(expect), "mock-model"

    with ExitStack() as stack:
        # Production-like: no labels in the graph's state, no oracle routing.
        stack.enter_context(oracle_routing_override(False))
        stack.enter_context(patch("llm.client.get_llm", side_effect=_mock_get_llm))
        stack.enter_context(patch("agents.base.get_llm", side_effect=_mock_get_llm))
        for lc_patch in _langchain_mock_patches(expect):
            stack.enter_context(lc_patch)
        result = run_pipeline(path, matter_id, source="sandbox-api-eval-mock",
                              intake_meta=read_inbox_meta(path) or None)
    return {"file": inbox_name, "stage": result.get("stage"), "doc_type": result.get("doc_type")}


@contextmanager
def offline_mock_api(rows: Sequence[Mapping[str, Any]], *, base_dir: str | Path | None = None) -> Iterator[MailroomAPI]:
    """A :class:`MailroomAPI` bound to the vendored API app, in process, with no network and no spend.

    The vendored ``api.main`` app runs under Starlette's test client with its embedded watcher
    off; :class:`_DrainingTransport` processes each upload synchronously under the mock LLM.
    Pass the same ``rows`` to :func:`run_api_eval`. The API's bins and catalog
    (``MAILROOM_BASE_DIR``) go to ``base_dir``, or to a fresh temporary directory that is
    removed afterwards, so a mock run never touches real bins. Tracing, Langfuse prompt
    fetches and score writes are switched off, even when keys are configured. The whole
    ``os.environ`` and ``sys.path`` are restored on exit. Needs the ``observability`` extra
    (the API imports Langfuse).
    """
    import os
    import secrets
    import sys

    from mailroom_sandbox.runtime import activate

    saved_env, saved_path = dict(os.environ), list(sys.path)
    scratch = None if base_dir is not None else tempfile.TemporaryDirectory(prefix="sandbox-api-mock-")
    # The API serves a non-loopback client (the test client) only with a token: mint a throwaway one.
    token = secrets.token_urlsafe(24)
    os.environ["MAILROOM_BASE_DIR"] = str(base_dir if base_dir is not None else scratch.name)  # type: ignore[union-attr]
    os.environ["MAILROOM_EMBED_WATCHER"] = "0"
    os.environ["SANDBOX_RUN_MODE"] = "mock"
    os.environ["MAILROOM_API_TOKEN"] = token
    os.environ.pop("MAILROOM_API_TOKENS", None)
    try:
        activate(None)  # may load .env, so hosted-sink keys are dropped after it
        _offline_observability(os.environ)
        try:
            from starlette.testclient import TestClient

            from api.main import app  # type: ignore
        except ImportError as exc:
            raise FamilyAPIError(
                f"the offline mock API needs the vendored API's dependencies ({exc.name}): "
                "pip install -e '.[pipeline,observability]'"
            ) from None
        # A loopback base URL: the throwaway token never triggers the plain-HTTP warning.
        with TestClient(app, base_url="http://127.0.0.1") as client:
            transport = _DrainingTransport(client._transport, rows)
            yield MailroomAPI("http://127.0.0.1", token, transport=transport)
    finally:
        os.environ.clear()
        os.environ.update(saved_env)
        sys.path[:] = saved_path
        if scratch is not None:
            scratch.cleanup()


_HOSTED_SINK_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_INIT_PROJECT_PUBLIC_KEY",
                     "LANGFUSE_INIT_PROJECT_SECRET_KEY", "BRAINTRUST_API_KEY")


def _offline_observability(environ: Any) -> None:
    """Keep a mock run off every trace sink: no spans, scores or prompt fetches leave the process."""
    for key in _HOSTED_SINK_KEYS:
        environ.pop(key, None)
    environ["OBSERVABILITY_PROVIDER"] = "none"
    environ["PHOENIX_TRACING"] = "disabled"
