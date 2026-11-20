# Docker offline sandbox

This repo ships **two** Docker surfaces:

| Artifact | Role |
| --- | --- |
| [`deploy/docker-compose.yml`](../../deploy/docker-compose.yml) | Sidecar stack: Langfuse 3, Ollama, optional Phoenix / vLLM / llama.cpp, and **Jupyter Lab** |
| [`deploy/Dockerfile`](../../deploy/Dockerfile) | Offline sandbox image (`mailroom-sandbox:offline`) with the Python harness + notebooks |

The image imports the tracked vendored family pipeline; it does not implement
a second pipeline. It includes the sandbox harness, fixtures, notebooks and
Jupyter, plus the floor builder and template under `reports/dashboard/`.

## Quick start (Jupyter + Ollama + Langfuse)

```bash
pip install -e ".[dev,notebooks]"
cp -n config/.env.example .env
sandbox up -d --compose-profile langfuse --compose-profile ollama --compose-profile jupyter
# Lab: http://127.0.0.1:8888/lab
# Langfuse: http://127.0.0.1:3000  (pk-lf-sandbox / sk-lf-sandbox; sign-in email LANGFUSE_INIT_USER_EMAIL, default sandbox@example.com)
sandbox pull-models --profile ollama
```

Or build the image alone:

```bash
docker build -f deploy/Dockerfile -t mailroom-sandbox:offline .
docker run --rm -p 127.0.0.1:8888:8888 -v "$PWD":/workspace mailroom-sandbox:offline
```

Image hardening (HUB-015): the sandbox image runs as a **non-root user**
(`sandbox`, uid 1000) and carries a **HEALTHCHECK** (`curl /lab`). On hosts
whose first user is not uid 1000, pass `--user "$(id -u):$(id -g)"`. All
compose images are **version-pinned** (ollama `0.33.2`, vllm `v0.29.0`,
phoenix `version-20.4.0`, llama.cpp `full-e95b6554b493e71a0275764342e09bd5784a7026`,
minio `cgr.dev/chainguard/minio@sha256:3b6e40c3…`, langfuse web and worker
`3.225.15`, redis `7`, clickhouse `24-alpine`, pgvector `pg16`) for offline
reproducibility — bump pins deliberately. Every published Compose port binds
`127.0.0.1`, so the services are reachable from the host only.

Upgrading from the old `minio/minio` image: the Chainguard image runs as UID
65532, but a `minio_data` volume created by the old image is root-owned, so
MinIO cannot create `/data/langfuse` and Langfuse loses its event and media
store. Change the volume's owner once:

```bash
docker compose -f deploy/docker-compose.yml --profile langfuse stop minio
volume=$(docker volume ls -q --filter label=com.docker.compose.volume=minio_data)   # e.g. mailroom-sandbox_minio_data
if [ "$(printf '%s\n' "$volume" | grep -c .)" -eq 1 ]; then
  docker run --rm -v "$volume":/data alpine chown -R 65532:65532 /data &&
    docker compose -f deploy/docker-compose.yml --profile langfuse up -d minio
else
  echo "expected exactly one minio_data volume, found: ${volume:-none}; MinIO left stopped"   # chown it by name
fi
```

## Notebooks (dedicated prep path)

| Notebook | Purpose |
| --- | --- |
| [`notebooks/01_offline_environment_setup.ipynb`](../../notebooks/01_offline_environment_setup.ipynb) | Copy `.env`, activate profile, verify Dockerfile/compose/fixtures |
| [`notebooks/02_load_clean_prepare_data.ipynb`](../../notebooks/02_load_clean_prepare_data.ipynb) | Load catalog + HF + agent gold; clean; write `data/runtime/prepared/` |
| [`notebooks/03_offline_sandbox_smoke.ipynb`](../../notebooks/03_offline_sandbox_smoke.ipynb) | Mock pilot / sorter smoke against prepared JSONL (no live LLM) |
| [`notebooks/04_experiment_log_explorer.ipynb`](../../notebooks/04_experiment_log_explorer.ipynb) | Read-only table and charts of experiment-log records |

Run order, outputs and environment switches: [`notebooks/README.md`](../../notebooks/README.md).
Prep helpers live in `mailroom_sandbox.prep` (`prepare_offline_datasets`, `environment_checklist`).
The shared notebook bootstrap (`mailroom_sandbox.notebook.bootstrap`) pins an absolute
`MAILROOM_BASE_DIR`, uses the `ollama` profile unless `SANDBOX_PROFILE` is set, and picks
a notebook log, `runtime/notebooks/experiment_log.jsonl` under `MAILROOM_BASE_DIR`
(`SANDBOX_NOTEBOOK_LOG` overrides it). Eval records go there only inside
`experiment_log_redirect(ctx.experiment_log)`, as notebook 03 does.

## Compose profiles

| Profile | Services |
| --- | --- |
| `langfuse` | postgres, clickhouse, redis, minio, langfuse-web, langfuse-worker |
| `ollama` | `sandbox-ollama` on `:11434` |
| `jupyter` | builds `deploy/Dockerfile`, Lab on `:8888` |
| `phoenix` / `vllm` / `llamacpp` | optional sidecars |
| `pipeline` | CPU graph runner plus the localhost vLLM front door on `:8000` |

`sandbox up` (default `modal-vllm` profile) starts `langfuse` only: the GPU
endpoint lives on Modal, not in compose. For the offline Ollama stack use
`sandbox up --compose-profile ollama`. Explicit compose profiles replace the profile defaults;
select each service you need. To start Jupyter alone:

```bash
sandbox up -d --compose-profile jupyter
sandbox down --compose-profile jupyter
```

The Jupyter service defaults to the `ollama` profile (`SANDBOX_PROFILE` in `deploy/docker-compose.yml`); export `SANDBOX_PROFILE` in the shell that runs `sandbox up` to change it. Inside the Jupyter container, provider URLs point at compose DNS names (`http://ollama:11434/v1`, `http://langfuse-web:3000`). On the host, keep using `localhost` URLs from `config/.env.example`.

## Full pipeline across machines

Specialist cells in the SAND-39 through SAND-42 series ran one GPU call per in-flight document, on one or two L4 machines, admitting 8–16 sequences of those shorter prompts. A full pipeline document still occupies one sequence at a time, then makes the next stage's call. The production OpenRouter slices (`config/runs/production/slice-0100.yaml` and its larger twins) keep concurrency at 10 and send the reviewer to the Decisions API, so the GPU stages are the sorter, the specialist, and the judge.

`mailroom_sandbox.fleet.pipeline_fleet` turns that into a machine count. With the long-prompt cap of 6 sequences per L4:

- 2 GPU machines hold 10 documents in flight. Each document then takes about three sequential GPU calls, so the document rate is about a third of a specialist run at the same concurrency.
- 5 GPU machines is the planning fleet that buys that specialist document rate back, if each stage lasts about as long as one specialist call. That assumption is not a measurement. A smoke run's observed GPU calls per document replaces `gpu_stages`.

The Compose shape matches the OpenRouter path: one CPU process runs the graph, and every LLM call goes to one OpenAI-compatible URL. On the control machine:

```bash
sandbox up -d --compose-profile langfuse --compose-profile pipeline
```

`pipeline` starts `vllm-front` (nginx `1.27.4-alpine` on `127.0.0.1:8000`) and one `pipeline` container whose `VLLM_BASE_URL` is `http://vllm-front:8000/v1`. The container sleeps. It does not start a run. A person launches with `sandbox run preflight` and `sandbox run start --initials`. `vllm` and `pipeline` both bind port 8000, so Compose refuses to start them on the same machine.

Each GPU machine runs only the vLLM profile, still bound to `127.0.0.1:8000`:

```bash
sandbox up -d --compose-profile vllm
```

The control machine reaches those servers with one SSH forward per machine, onto ports 18000–18004. That list is `deploy/pipeline-front/nginx.conf`. The front door uses least-connections and `max_conns=6` on each upstream, so one machine cannot accept more in-flight requests than its sequence cap. `FleetPlan.ssh_forwards` prints the `ssh -N -L` lines once the operator supplies the `user@host` names. `sandbox tunnel` remains the single-host forward.

## Pipeline floor assets

The standalone image copies `reports/dashboard/build_floor_digest.py` and
`floor.template.html`, the replay fixture, and the vendored graph source, so
`sandbox floor --replay` can build its initial digest without a checkout mount.
Resident digest files use per-process temporary storage and are removed on
exit; the replay run stays in `/workspace/data/runtime/runs/`. A bind mount
over `/workspace` replaces the image tree, so it must contain the same assets.

The viewer binds loopback inside its own network namespace. Publishing a
Docker port alone does not expose that container-loopback listener to a host
browser. For normal host browsing, run `sandbox floor` from the host checkout;
keep the loopback binding. See the [floor guide](../floor.md) for options,
snapshot generation and replay provenance. The image's default entry point
remains Jupyter Lab.

## Offline data prep without Docker

```bash
pip install -e ".[dev,notebooks]"
python -c "from mailroom_sandbox.prep import prepare_offline_datasets; print(prepare_offline_datasets())"
jupyter lab notebooks/
```

Prepared artifacts are written under `data/runtime/prepared/` (gitignored with the rest of `data/runtime/`).
