"""CircleCI diagnostics keep tokens off log downloads and find failed jobs."""
import httpx
import pytest

from mailroom_sandbox import cli
from mailroom_sandbox.services import circleci, doctor
from mailroom_sandbox.services._exec import ServiceError


def test_pipeline_pagination_and_failure_filter(monkeypatch):
    pipeline = "11111111-1111-1111-1111-111111111111"
    workflow = "22222222-2222-2222-2222-222222222222"
    def get(url, **kwargs):
        if url.endswith("/pipeline/" + pipeline):
            return {"project_slug": circleci.DEFAULT_PROJECT}
        if "pipeline/" in url:
            return {"items": [{"id": workflow}]}
        if "page-token=" not in url:
            return {"items": [{"status": "success"}], "next_page_token": "next"}
        return {"items": [{"status": "failed", "job_number": 12}]}
    monkeypatch.setattr(circleci, "_get", get)
    assert circleci.failed_jobs(pipeline)[0]["job_number"] == 12


def test_failed_logs_only_without_token_on_output(monkeypatch, capsys):
    calls = []
    def get(url, **kwargs):
        calls.append(kwargs)
        if "v1.1" in url:
            return {"steps": [{"name": "test", "actions": [
                {"status": "failed", "output_url": "https://logs.example/secret"},
                {"status": "success", "output_url": "https://logs.example/other"}]}]}
        return [{"message": "test failed\n"}]
    monkeypatch.setattr(circleci, "_get", get)
    assert cli.main(["circleci", "logs", "--job", "42"]) == 0
    assert "test failed" in capsys.readouterr().out
    assert calls == [{}, {"authenticated": False}]


def test_output_fetch_does_not_receive_auth_header(monkeypatch):
    monkeypatch.setenv("CIRCLE_TOKEN", "top-secret")
    def get(url, **kwargs):
        assert kwargs["headers"] == {}
        return httpx.Response(200, json=[], request=httpx.Request("GET", url))
    monkeypatch.setattr(circleci.httpx, "get", get)
    assert circleci._get("https://logs.example/path", authenticated=False) == []


def test_invalid_url_and_missing_token_are_safe(monkeypatch):
    monkeypatch.delenv("CIRCLE_TOKEN", raising=False)
    with pytest.raises(ServiceError, match="CIRCLE_TOKEN"):
        circleci._get(circleci.API + "/v2/me")
    monkeypatch.setattr(circleci, "_get", lambda *a, **k: {"steps": [{"actions": [{"status": "failed", "output_url": "http://localhost/"}]}]})
    with pytest.raises(ServiceError, match="invalid output URL"):
        circleci.print_job_logs("gh/owner/repo", 1)


def test_doctor_does_not_probe_without_live(monkeypatch):
    monkeypatch.setenv("CIRCLE_TOKEN", "private")
    monkeypatch.setattr(circleci, "_get", lambda *a: pytest.fail("unexpected network"))
    row = doctor._circleci(live=False)
    assert row.readiness == "configured" and "private" not in row.detail
