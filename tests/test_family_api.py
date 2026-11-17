"""`sandbox api`: mailroom API client + Dojo scoring over API results (httpx.MockTransport, no network)."""

from __future__ import annotations

import json
import re

import httpx
import pytest

from mailroom_sandbox import cli, family_api
from mailroom_sandbox.datasets import load_manifest
from mailroom_sandbox.paths import vendored_mailroom_src

TOKEN = "s3cr3t-token-value"


class FakeMailroom:
    """Answers like the mailroom API: uploads land, then each document finishes after ``ticks`` lookups."""

    def __init__(self, rows, *, ticks=1, wrong=(), never=(), stage="archived", oracle=True, upload_status=()):
        self.by_name: dict[str, str] = {}  # inbox name -> original fixture name
        self.matters: list[str] = []
        self.rows = {r["filename"]: r for r in rows}
        self.ticks, self.wrong, self.never, self.stage, self.oracle = ticks, set(wrong), set(never), stage, oracle
        self.upload_status = list(upload_status)  # statuses returned before uploads succeed
        self.lookup_status: int | None = None
        self.requests: list[httpx.Request] = []
        self.lookups: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "mailroom", "checks": {"watcher": "ok"}})
        if path == "/upload" and request.method == "POST":
            if self.upload_status:
                return httpx.Response(self.upload_status.pop(0), json={"detail": "Too many uploads"})
            sent = re.search(rb'name="file"; filename="([^"]+)"', request.content).group(1).decode()
            self.matters.append(re.search(rb'name="matter_id"\r\n\r\n([^\r]*)', request.content).group(1).decode())
            original = next(f for f in self.rows if sent.endswith("-" + f))
            name, n = sent, 0
            while name in self.by_name:  # the API de-duplicates inbox names like this
                n += 1
                name = f"{sent.rsplit('.', 1)[0]}-{n}.{sent.rsplit('.', 1)[1]}"
            self.by_name[name] = original
            return httpx.Response(202, json={"status": "accepted", "file": name, "upload_id": f"u{len(self.by_name)}"})
        if path == "/lookup":
            if self.lookup_status:
                return httpx.Response(self.lookup_status, json={"detail": "bad gateway"})
            name = request.url.params["filename"]
            seen = self.lookups[name] = self.lookups.get(name, 0) + 1
            if name not in self.by_name:
                return httpx.Response(404, json={"detail": "Document not found"})
            original = self.by_name[name]
            row = self.rows[original]
            doc_id = f"d{list(self.by_name).index(name)}"
            if original in self.never or seen < self.ticks:
                return httpx.Response(200, json={"document": {"doc_id": doc_id, "stage": "processing"}})
            failed = self.stage == "failed"
            doc_type = None if failed else ("correspondence" if original in self.wrong else row["expected_doc_class"])
            fields = json.loads(row["expected_fields"]) if (self.oracle and row.get("expected_fields")) else {}
            return httpx.Response(200, json={"document": {
                "doc_id": doc_id, "original_filename": name, "stage": self.stage,
                "doc_type": doc_type, "classification_confidence": 0.97, "extracted_data": fields,
                "trace_id": "t", "escalation_reason": None,
            }})
        return httpx.Response(404, json={"detail": "not found"})

    @property
    def uploads(self):
        return [r for r in self.requests if r.url.path == "/upload"]


@pytest.fixture
def rows():
    return [r for r in load_manifest() if r.get("expected_fields")][:3]


def _api(fake, token=TOKEN):
    return family_api.MailroomAPI("http://mailroom.test", token, transport=httpx.MockTransport(fake))


def _no_sleep(_):
    return None


def test_eval_scores_api_results_with_the_dojo(rows):
    fake = FakeMailroom(rows, ticks=2)
    report = family_api.run_api_eval(rows, _api(fake), run_tag="t1", sleep=_no_sleep)
    assert report["ok"] is True and report["n"] == 3 and report["completed"] == 3
    assert report["classification"]["accuracy"] == 1.0
    assert report["extraction"]["n"] == 3
    assert report["extraction"]["overall_extraction_score"] == pytest.approx(1.0, abs=0.05)
    assert report["stages"] == {"archived": 3}
    assert report["family"]["dojo"]["pinned"]["commit"]
    assert report["family"]["mailroom"]["pinned"]["commit"]
    # every upload is renamed with the run tag, so an older same-named document is never read back
    assert all(d["file"].startswith("t1-") for d in report["documents"])
    assert all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in fake.requests)
    assert fake.matters == ["SANDBOX-API-EVAL"] * 3
    want = [r["expected_stage"] for r in rows]
    assert report["stage"]["stage_correct"] == pytest.approx(want.count("archived") / 3, abs=1e-3)


def test_eval_counts_a_misclassification(rows):
    fake = FakeMailroom(rows, wrong={rows[0]["filename"]})
    report = family_api.run_api_eval(rows, _api(fake), sleep=_no_sleep)
    assert report["classification"]["accuracy"] == pytest.approx(2 / 3, abs=1e-3)
    assert report["ok"] is True


def test_eval_reports_documents_that_never_finish_and_does_not_score_them(rows):
    fake = FakeMailroom(rows, never={rows[1]["filename"]})
    ticks = iter(range(10_000))
    report = family_api.run_api_eval(rows, _api(fake), doc_timeout=5, poll_seconds=1,
                                     sleep=_no_sleep, clock=lambda: float(next(ticks)))
    assert report["ok"] is False
    assert report["completed"] == 2 and len(report["incomplete"]) == 1
    assert rows[1]["filename"] in report["incomplete"][0]
    assert report["classification"]["n"] == 2


def test_parked_documents_are_classified_but_not_extraction_scored(rows):
    fake = FakeMailroom(rows, stage="review")
    report = family_api.run_api_eval(rows, _api(fake), sleep=_no_sleep)
    assert report["stages"] == {"review": 3}
    assert report["classification"]["n"] == 3
    assert report["extraction"]["n"] == 0 and report["extraction"]["overall_extraction_score"] is None
    want = [r["expected_stage"] for r in rows]
    assert report["stage"]["stage_correct"] == pytest.approx(want.count("review") / 3, abs=1e-3)
    assert report["ok"] is True  # parked is a pipeline outcome, not a run failure


def test_failed_documents_count_as_wrong_and_fail_the_run(rows):
    fake = FakeMailroom(rows, stage="failed")
    report = family_api.run_api_eval(rows, _api(fake), sleep=_no_sleep)
    assert report["ok"] is False and len(report["failed"]) == 3
    assert report["classification"]["n"] == 3 and report["classification"]["accuracy"] == 0.0
    assert all(d["doc_type"] is None for d in report["documents"])


def test_rate_limited_upload_is_retried_after_a_backoff(rows):
    fake = FakeMailroom(rows, upload_status=[429, 429])
    slept = []
    report = family_api.run_api_eval(rows, _api(fake), sleep=slept.append)
    assert report["ok"] is True and report["n"] == 3
    assert slept[:2] == [family_api.RATE_LIMIT_BACKOFF_SECONDS] * 2


def test_a_refused_upload_keeps_the_documents_already_accepted(rows):
    fake = FakeMailroom(rows)
    real = fake.__call__

    def refuse_second_upload(request):
        if request.url.path == "/upload" and len(fake.by_name) == 1:
            return httpx.Response(400, json={"detail": "Unsupported file type"})
        return real(request)

    api = family_api.MailroomAPI("http://mailroom.test", TOKEN, transport=httpx.MockTransport(refuse_second_upload))
    report = family_api.run_api_eval(rows, api, sleep=_no_sleep)
    assert report["ok"] is False and "Unsupported file type" in report["error"]
    assert report["n_rows"] == 3 and report["n"] == 1 and report["completed"] == 1
    assert report["unconfirmed_upload"] is None  # a 4xx refusal stored nothing


def test_an_unanswered_upload_is_named_as_unconfirmed(rows):
    fake = FakeMailroom(rows)
    real = fake.__call__

    def time_out_second_upload(request):
        if request.url.path == "/upload" and len(fake.by_name) == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return real(request)

    api = family_api.MailroomAPI("http://mailroom.test", TOKEN, transport=httpx.MockTransport(time_out_second_upload))
    report = family_api.run_api_eval(rows, api, sleep=_no_sleep, run_tag="t1")
    assert report["ok"] is False and "did not answer" in report["error"]
    assert report["unconfirmed_upload"] == f"t1-{rows[1]['filename']}"
    assert report["completed"] == 1


def test_a_lookup_error_while_polling_returns_a_partial_report(rows):
    fake = FakeMailroom(rows)
    fake.lookup_status = 502
    report = family_api.run_api_eval(rows, _api(fake), sleep=_no_sleep)
    assert report["ok"] is False and "HTTP 502" in report["error"]
    assert report["n"] == 3 and len(report["incomplete"]) == 3
    assert {d["upload_id"] for d in report["documents"]} == {"u1", "u2", "u3"}


def test_same_named_rows_are_tracked_separately(rows):
    twice = [rows[0], dict(rows[0], id="again")]
    fake = FakeMailroom(rows)
    report = family_api.run_api_eval(twice, _api(fake), run_tag="dup", sleep=_no_sleep)
    files = [d["file"] for d in report["documents"]]
    assert len(set(files)) == 2 and report["completed"] == 2


def test_rows_with_only_doc_type_are_scored(rows):
    legacy = [{k: v for k, v in r.items() if k != "expected_doc_class"} | {"doc_type": r["expected_doc_class"]}
              for r in rows]
    fake = FakeMailroom(rows)
    report = family_api.run_api_eval(legacy, _api(fake), sleep=_no_sleep)
    assert report["classification"]["accuracy"] == 1.0 and report["extraction"]["n"] == 3


def test_zero_poll_interval_is_clamped(rows):
    fake = FakeMailroom(rows, never={rows[0]["filename"]})
    slept = []
    ticks = iter(range(10_000))
    family_api.run_api_eval(rows, _api(fake), poll_seconds=0, doc_timeout=100, sleep=slept.append,
                            clock=lambda: float(next(ticks)))
    assert slept and min(slept) >= family_api.MIN_POLL_SECONDS


def test_doc_ids_are_validated_before_they_reach_a_path():
    fake = FakeMailroom([])
    with pytest.raises(ValueError):
        _api(fake).audit("../ops/sweep")
    assert fake.requests == []


def test_errors_never_print_the_token(rows):
    def refuse(request):
        return httpx.Response(500, json={"detail": f"boom {TOKEN}"})

    api = family_api.MailroomAPI("http://mailroom.test", TOKEN, transport=httpx.MockTransport(refuse))
    with pytest.raises(family_api.FamilyAPIError) as exc:
        api.health()
    assert TOKEN not in str(exc.value) and "HTTP 500" in str(exc.value)


def test_unreachable_api_names_the_fix():
    def down(request):
        raise httpx.ConnectError("refused")

    api = family_api.MailroomAPI("http://mailroom.test", None, transport=httpx.MockTransport(down))
    with pytest.raises(family_api.FamilyAPIError, match="sandbox pipeline api"):
        api.health()


def test_lookup_returns_none_while_the_document_is_unknown():
    fake = FakeMailroom([])
    assert _api(fake).lookup(filename="nope.txt") is None


def test_status_offline_reports_both_family_sources(capsys):
    assert cli.main(["api", "status", "--offline"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"mailroom", "dojo"}
    assert re.fullmatch(r"[0-9a-f]{40}", out["dojo"]["pinned"]["commit"])
    assert re.fullmatch(r"[0-9a-f]{40}", out["mailroom"]["pinned"]["commit"])


def test_status_reports_an_unreachable_api_without_failing(monkeypatch, capsys):
    monkeypatch.setenv("MAILROOM_API_URL", "http://mailroom.test")

    def down(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(family_api, "_default_transport", lambda: httpx.MockTransport(down))
    assert cli.main(["api", "status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["api"]["reachable"] is False and "sandbox pipeline api" in out["api"]["error"]


def test_eval_without_submit_only_plans(monkeypatch, capsys):
    monkeypatch.setenv("MAILROOM_API_URL", "http://mailroom.test")
    calls = []
    monkeypatch.setattr(family_api, "_default_transport",
                        lambda: httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))
    assert cli.main(["api", "eval", "--sample", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["submit"] is False and out["n"] == 2
    assert calls == []  # nothing was sent


def test_eval_plan_honours_out(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("MAILROOM_API_URL", "http://mailroom.test")
    out = tmp_path / "plan.json"
    assert cli.main(["api", "eval", "--sample", "1", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["submit"] is False


def test_eval_submit_writes_the_report_and_exits_nonzero_when_unfinished(monkeypatch, tmp_path, capsys, rows):
    monkeypatch.setenv("MAILROOM_API_URL", "http://mailroom.test")
    monkeypatch.setenv("MAILROOM_API_TOKEN", TOKEN)
    fake = FakeMailroom(load_manifest())
    monkeypatch.setattr(family_api, "_default_transport", lambda: httpx.MockTransport(fake))
    out_path = tmp_path / "report.json"
    rc = cli.main(["api", "eval", "--class", "contract", "--sample", "1", "--submit", "--poll", "0.2",
                   "--out", str(out_path)])
    assert rc == 0
    report = json.loads(out_path.read_text())
    assert report["n"] == 1 and report["classification"]["accuracy"] == 1.0
    assert TOKEN not in capsys.readouterr().out

    fake.never = {r["filename"] for r in load_manifest()}
    rc = cli.main(["api", "eval", "--class", "contract", "--sample", "1", "--submit", "--poll", "0.2",
                   "--timeout", "0"])
    assert rc == 1


@pytest.mark.parametrize("flags", [["--poll", "0"], ["--poll", "-1"], ["--timeout", "-5"],
                                   ["--poll", "nan"], ["--poll", "inf"], ["--timeout", "nan"], ["--timeout", "inf"]])
def test_eval_rejects_bad_poll_and_timeout(flags, capsys):
    assert cli.main(["api", "eval", "--submit", *flags]) == 2
    assert "must" in capsys.readouterr().err


def test_eval_rejects_an_empty_selection(capsys):
    assert cli.main(["api", "eval", "--class", "no_such_class"]) == 2
    assert "no fixture rows" in capsys.readouterr().err


# The client depends on these API endpoints and document fields. A vendor refresh that drops
# or renames one must fail here, not at the first deployment eval.
_ROUTES = ('@app.get("/health")', '@app.post("/upload"', '@app.get("/lookup"', '@app.get("/status/{doc_id}"',
           '@app.get("/queue"', '@app.get("/audit/{doc_id}"', '@app.get("/ops/status"')
_DOC_FIELDS = ("doc_id", "stage", "doc_type", "classification_confidence", "extraction_confidence",
               "escalation_reason", "trace_id", "extracted_data")


def test_vendored_api_still_serves_what_the_client_reads():
    src = vendored_mailroom_src()
    assert src is not None
    main = (src / "api" / "main.py").read_text(encoding="utf-8")
    for route in _ROUTES:
        assert route in main, route
    upload = main[main.index('@app.post("/upload"'):]
    assert '"file": dest.name' in upload and '"upload_id"' in upload
    serialize = (src / "pipeline" / "review_resolve.py").read_text(encoding="utf-8")
    body = serialize[serialize.index("def serialize_document"):]
    body = body[: body.index("\ndef ", 1)]
    for field in _DOC_FIELDS:
        assert f'"{field}"' in body, field
    stages = (src / "schemas" / "manifest.py").read_text(encoding="utf-8")
    for stage in family_api.TERMINAL_STAGES:
        assert f'"{stage}"' in stages, stage


def test_mock_and_submit_are_exclusive(capsys):
    assert cli.main(["api", "eval", "--mock", "--submit"]) == 2


def _needs_the_vendored_api():
    # The vendored API imports Langfuse and FastAPI (the `observability` extra), which the
    # CI `[dev]` install does not carry: there these end-to-end tests skip.
    for module in ("langfuse", "fastapi", "starlette.testclient"):
        pytest.importorskip(module)


def test_offline_mock_api_runs_the_real_api_and_pipeline_end_to_end(tmp_path, monkeypatch):
    """Upload through the vendored FastAPI app, run the vendored graph (mock LLM), score with the Dojo."""
    _needs_the_vendored_api()
    import os

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    before = {k: os.environ.get(k) for k in ("MAILROOM_BASE_DIR", "MAILROOM_API_TOKEN", "SANDBOX_RUN_MODE")}
    picked = [r for r in load_manifest() if r["filename"] in {"sample_msa.txt", "sample_claim.txt", "sample_bylaws.txt"}]
    assert len(picked) == 3
    with family_api.offline_mock_api(picked, base_dir=tmp_path) as api:
        assert api.health()["status"] in {"ok", "degraded"}
        report = family_api.run_api_eval(picked, api, poll_seconds=0.2, doc_timeout=60)
    assert report["error"] is None and report["ok"], report
    assert report["completed"] == 3 and not report["incomplete"]
    assert set(report["stages"]) <= family_api.TERMINAL_STAGES
    # The mock LLM answers each row's expected class, so routing through the real API is exact.
    assert report["classification"]["accuracy"] == pytest.approx(1.0)
    by_file = {d["file"].split("-", 2)[-1]: d for d in report["documents"]}
    assert by_file["sample_msa.txt"]["stage"] == "archived"
    assert report["extraction"]["n"] >= 1
    # The documents went through the API's own bins and catalog under base_dir.
    assert any(tmp_path.rglob("*.db"))
    # Everything the context manager set is put back.
    assert {k: os.environ.get(k) for k in before} == before


def test_cli_eval_mock_writes_a_report_without_a_server(tmp_path, monkeypatch, capsys):
    _needs_the_vendored_api()
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # A dead URL proves --mock never reaches a server.
    monkeypatch.setenv("MAILROOM_API_URL", "http://127.0.0.1:9")
    out = tmp_path / "report.json"
    rc = cli.main(["api", "eval", "--mock", "--class", "contract", "--sample", "1", "--poll", "0.2",
                   "--timeout", "60", "--out", str(out)])
    report = json.loads(out.read_text())
    assert rc == 0, report
    assert report["mode"] == "mock" and report["ok"] and report["completed"] == 1
    assert report["classification"]["accuracy"] == pytest.approx(1.0)


@pytest.mark.parametrize("kw", [{"poll_seconds": float("nan")}, {"doc_timeout": float("nan")},
                                {"doc_timeout": float("inf")}])
def test_run_api_eval_refuses_non_finite_timing_before_uploading(kw, rows):
    fake = FakeMailroom(rows)
    api = family_api.MailroomAPI("http://mailroom.test", TOKEN, transport=httpx.MockTransport(fake))
    with pytest.raises(ValueError, match="finite"):
        family_api.run_api_eval(rows, api, **kw)
    assert fake.requests == []


@pytest.mark.parametrize("url", ["http://user:pw@mailroom.test", "https://mailroom.test/?k=v", "ftp://mailroom.test"])
def test_an_explicit_base_url_gets_the_same_check_as_the_env_var(url):
    with pytest.raises(Exception, match="without credentials"):
        family_api.MailroomAPI(url, TOKEN)
