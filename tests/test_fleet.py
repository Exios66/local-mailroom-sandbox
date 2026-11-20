"""Pipeline fleet size. No Docker and no GPU."""

from __future__ import annotations

from pathlib import Path

from mailroom_sandbox.fleet import pipeline_fleet, render_nginx

NGINX = Path(__file__).resolve().parents[1] / "deploy" / "pipeline-front" / "nginx.conf"


def test_production_slice_needs_five_machines_to_match_specialist_rate():
    plan = pipeline_fleet()
    assert plan.document_concurrency == 10
    assert plan.gpu_stages == 3
    assert plan.seqs_per_gpu == 6
    assert plan.machines_for_inflight == 2
    assert plan.machines_for_specialist_rate == 5
    assert plan.rate_concurrency == 30
    assert plan.tunnel_ports == (18000, 18001, 18002, 18003, 18004)


def test_sand42_saturation_cell_is_two_machines_at_specialist_depth():
    """2×L4 C32 admitted 16 sequences per replica, one specialist call."""
    plan = pipeline_fleet(document_concurrency=32, gpu_stages=1, seqs_per_gpu=16)
    assert plan.machines_for_inflight == 2
    assert plan.machines_for_specialist_rate == 2


def test_same_cell_at_pipeline_depth_and_the_long_prompt_cap():
    plan = pipeline_fleet(document_concurrency=32, gpu_stages=3, seqs_per_gpu=6)
    assert plan.machines_for_inflight == 6
    assert plan.machines_for_specialist_rate == 16


def test_committed_front_door_matches_the_production_plan():
    assert NGINX.read_text(encoding="utf-8") == render_nginx(pipeline_fleet())


def test_ssh_forwards_follow_the_rate_fleet():
    plan = pipeline_fleet(document_concurrency=6, gpu_stages=2, seqs_per_gpu=6)
    assert plan.machines_for_specialist_rate == 2
    lines = plan.ssh_forwards(["gpu@a.example", "gpu@b.example"])
    assert len(lines) == 2
    assert "127.0.0.1:8000" in lines[0] and lines[0].endswith("gpu@a.example")
    assert ":18000:" in lines[0] and ":18001:" in lines[1]
    assert "Darwin" in lines[0] and "docker network inspect bridge" in lines[0]
    assert not lines[0].startswith("ssh -N -L 18000:127.0.0.1:8000")


def test_ssh_forwards_reject_a_short_host_list():
    try:
        pipeline_fleet().ssh_forwards(["gpu@a.example"])
    except ValueError as exc:
        assert "5 hosts" in str(exc)
    else:
        raise AssertionError("expected ValueError")
