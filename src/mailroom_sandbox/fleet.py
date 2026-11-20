"""GPU-machine count for a full-pipeline Docker fleet.

A specialist run (SAND-39 through SAND-42) holds one GPU call per in-flight
document. A pipeline document also holds one slot at a time — the graph does
not overlap its stages — but each extra stage lengthens the document. Keeping
the specialist document rate means keeping that many more documents in flight,
which is that many more sequence slots.

One L4 serving long pipeline prompts is capped at 6 sequences. The specialist
grid admitted 8–16 because those prompts were shorter. Each machine's proxy
connection cap equals that sequence cap, which is the admission rule from the
Qwen3-8B-AWQ ladder: a router that accepts more than the engine can run piles
every request onto one replica.

These counts are planning figures from that cap and from the stage list in
``job/budget_advice.py``. They are not a measured latency ratio. Replace
``gpu_stages`` with a smoke run's observed GPU calls per document when one exists.
The production OpenRouter slices keep the reviewer on the Decisions API, so the
default stage count is 3 (sorter, specialist, judge), not 4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Long-prompt cap on one L4 (deploy/docker-compose.yml VLLM_MAX_NUM_SEQS).
DEFAULT_SEQS_PER_GPU = 6
# config/runs/production/slice-0100.yaml job.concurrency.
PRODUCTION_DOCUMENT_CONCURRENCY = 10
# Sorter, specialist, judge. The Decisions reviewer is not a GPU stage.
PRODUCTION_GPU_STAGES = 3
# First port matches config/profiles/vllm-remote.yaml. Later machines follow.
TUNNEL_BASE_PORT = 18000


@dataclass(frozen=True)
class FleetPlan:
    """One control machine plus ``machines_for_specialist_rate`` GPU machines."""

    document_concurrency: int
    gpu_stages: int
    seqs_per_gpu: int
    machines_for_inflight: int
    machines_for_specialist_rate: int

    @property
    def tunnel_ports(self) -> tuple[int, ...]:
        """Host ports the control machine forwards to each GPU machine's vLLM."""
        count = self.machines_for_specialist_rate
        return tuple(TUNNEL_BASE_PORT + i for i in range(count))

    def ssh_forwards(self, hosts: list[str]) -> list[str]:
        """One ``ssh -N -L`` per GPU machine. ``hosts`` are ``user@host`` strings the operator supplies."""
        if len(hosts) != len(self.tunnel_ports):
            raise ValueError(
                f"expected {len(self.tunnel_ports)} hosts for this fleet, got {len(hosts)}"
            )
        return [
            f"ssh -N -L {port}:127.0.0.1:8000 {host}"
            for port, host in zip(self.tunnel_ports, hosts, strict=True)
        ]


def pipeline_fleet(
    *,
    document_concurrency: int = PRODUCTION_DOCUMENT_CONCURRENCY,
    gpu_stages: int = PRODUCTION_GPU_STAGES,
    seqs_per_gpu: int = DEFAULT_SEQS_PER_GPU,
) -> FleetPlan:
    """Machines for ``document_concurrency`` documents.

    ``machines_for_inflight`` holds that many documents at once. Each document
    then takes ``gpu_stages`` sequential GPU calls, so the document rate falls
    by about that factor. ``machines_for_specialist_rate`` is the fleet that
    buys the rate back, on the assumption that each stage lasts about as long
    as one specialist call.
    """
    if document_concurrency < 1:
        raise ValueError("document_concurrency must be >= 1")
    if gpu_stages < 1:
        raise ValueError("gpu_stages must be >= 1")
    if seqs_per_gpu < 1:
        raise ValueError("seqs_per_gpu must be >= 1")
    inflight = math.ceil(document_concurrency / seqs_per_gpu)
    rate = math.ceil(document_concurrency * gpu_stages / seqs_per_gpu)
    return FleetPlan(
        document_concurrency=document_concurrency,
        gpu_stages=gpu_stages,
        seqs_per_gpu=seqs_per_gpu,
        machines_for_inflight=inflight,
        machines_for_specialist_rate=rate,
    )


def render_nginx(plan: FleetPlan) -> str:
    """nginx config: least-connections, ``max_conns`` equal to the sequence cap.

    Upstreams are the host's SSH forwards (``host.docker.internal``), so the
    proxy stays on the control machine and each GPU machine keeps vLLM on
    ``127.0.0.1:8000``.
    """
    servers = "\n".join(
        f"    server host.docker.internal:{port} max_conns={plan.seqs_per_gpu};"
        for port in plan.tunnel_ports
    )
    return f"""worker_processes 1;
error_log /var/log/nginx/error.log warn;
pid /tmp/nginx.pid;

events {{
  worker_connections 256;
}}

http {{
  upstream vllm_backends {{
    least_conn;
    zone vllm_backends 64k;
{servers}
  }}

  server {{
    listen 8000;

    location = /healthz {{
      default_type text/plain;
      return 200 "ok\\n";
    }}

    location / {{
      proxy_pass http://vllm_backends;
      proxy_http_version 1.1;
      proxy_set_header Host $host;
      proxy_set_header Authorization $http_authorization;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
    }}
  }}
}}
"""
