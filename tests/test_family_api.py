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

    def __init__(self, rows, *, ticks=1, wrong=(), never=(), stage="archived", oracle=True):
        self.by_name = {}
        self.rows = {r["filename"]: r for r in rows}
        self.ticks, self.wrong, self.never, self.stage, self.oracle = ticks, set(wrong), set(never), stage, oracle
        self.requests: list[httpx.Request] = []
        self.lookups: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok", "service": "mailroom", "checks": {"watcher": "ok"}})
        if path == "/upload" and request.method == "POST":
            m = re.search(rb'filename="([^"]+)"', request.content)
            name = m.group(1).decode()
            self.by_name[name] = len(self.by_name)
            return httpx.Response(202, json={"status": "accepted", "file": name, "upload_id": f"u{len(self.by_name)}"})
        if path == "/lookup":
            name = request.url.params["filename"]
            seen = self.lookups[name] = self.lookups.get(name, 0) + 1
            if name not in self.by_name:
                return httpx.Response(404, json={"detail": "Document not found"})
            original = name.split("-", 2)[-1]
            row = self.rows[original]
            if original in self.never or seen < self.ticks:
                return httpx.Response(200, json={"document": {"doc_id": f"d{self.by_name[name]}", "stage": "processing"}})
            doc_type = "correspondence" if original in self.wrong else row["expected_doc_class"]
            fields = json.loads(row["expected_fields"]) if (self.oracle and row.get("expected_fields")) else {}
            return httpx.Response(200, json={"document": {
                "doc_id": f"d{self.by_name[name]}", "original_filename": name, "stage": self.stage,
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
    assert b"SANDBOX-API-EVAL" in fake.uploads[0].content


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
    assert report["extraction"] == {"n": 0, "overall_extraction_score": None}


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


def test_eval_submit_writes_the_report_and_exits_nonzero_on_incomplete(monkeypatch, tmp_path, capsys, rows):
    monkeypatch.setenv("MAILROOM_API_URL", "http://mailroom.test")
    monkeypatch.setenv("MAILROOM_API_TOKEN", TOKEN)
    fake = FakeMailroom(load_manifest())
    monkeypatch.setattr(family_api, "_default_transport", lambda: httpx.MockTransport(fake))
    out_path = tmp_path / "report.json"
    rc = cli.main(["api", "eval", "--class", "contract", "--sample", "1", "--submit", "--poll", "0",
                   "--out", str(out_path)])
    assert rc == 0
    report = json.loads(out_path.read_text())
    assert report["n"] == 1 and report["classification"]["accuracy"] == 1.0
    assert TOKEN not in capsys.readouterr().out

    fake.never = {r["filename"] for r in load_manifest()}
    rc = cli.main(["api", "eval", "--class", "contract", "--sample", "1", "--submit", "--poll", "0",
                   "--timeout", "0"])
    assert rc == 1


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
