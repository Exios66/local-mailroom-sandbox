# HTCondor / CHTC integration (HUB-026)

Run the sandbox's serving + evals on the Center for High Throughput
Computing (CHTC, UW–Madison) or any HTCondor pool. Two paths, chosen by
one question: **can you reach the job over SSH?**

| Path | Works on | Mechanism | Files |
| --- | --- | --- | --- |
| **Batch eval** (recommended) | CHTC shared GPU Lab + any pool | The job hosts vLLM itself for its lifetime, runs the evals in-process, transfers `results/` back — no server, no tunnel | `vllm_batch_eval.sub` + `run_batch_eval.sh` |
| **Server** | Researcher-**owned** GPU machines only | Long-lived vLLM server job + `condor_ssh_to_job` forward → `vllm-remote` profile | `vllm_serve.sub` + `serve_vllm.sh` |

> CHTC removed `condor_ssh_to_job` from the **shared** GPU Lab machines
> (it remains allowed on owned/prioritized machines). A tunnel-based server
> on the shared pool is structurally impossible — that is why the batch
> path exists.

## One-time setup (access point)

```bash
ssh <you>@ap2001.chtc.wisc.edu        # your CHTC access point
# 1. sandbox package tarball (from a monorepo checkout you push/copy over)
git archive --format=tar.gz -o mailroom-sandbox.tar.gz HEAD packages/local-mailroom-sandbox
#    (or archive just the package subtree; run_batch_eval.sh expects the
#     tarball to contain a mailroom-sandbox/ directory)
# 2. portable conda env from deploy/conda/environment.yml
conda env create -f deploy/conda/environment.yml
pip install -e ".[deploy]"            # inside the env, package root
conda pack -n mailroom-sandbox -o env-mailroom-sandbox.tar.gz
# 3. stage + submit
mkdir -p logs
condor_submit vllm_batch_eval.sub
```

`run_batch_eval.sh` unpacks the env, serves `Qwen/Qwen3-8B` (override with
`MODEL=...` in the submit file's `environment = "MODEL=..."`), waits for
`/v1/models`, then runs `sandbox eval sorter --local` / `eval extract
--local` with `SANDBOX_PROFILE=vllm-local` — identical scoring surfaces to
your local GPU box. Results land in `results/` next to the job's logs.

Submit-file knobs follow CHTC's GPU guide: `request_gpus`,
`gpus_minimum_memory`, `+GPUJobLength` (`short` < 4–6 h jobs may also set
`+is_resumable = true`), `container_image` (Docker Hub pull or a staged
`.sif` via `osdf:///chtc/staging/...`).

## Server path (owned GPUs)

```bash
condor_submit vllm_serve.sub
condor_q -long <cluster> | grep -E 'RemoteHost|Owner'   # find the job
condor_ssh_to_job <cluster>.<proc>
# inside the job:
echo $PORT_x8000 2>/dev/null; ss -ltn | grep 8000 || true
```

`condor_ssh_to_job` lands you on the execute node; from your **laptop**,
layer a local forward through it (two hops: submit node → job), or run the
forward from the access point:

```bash
# from the machine where condor_ssh_tojob works:
ssh -N -L 18000:localhost:8000 <you>@<execute-node-hostname>
```

Then point the sandbox at it from the same machine (or chain the forward
home) — this is exactly what the `vllm-remote` profile + `sandbox tunnel`
automate:

```bash
export SANDBOX_TUNNEL_HOST=<jump-host>      # machine that can reach the job
export SANDBOX_TUNNEL_USER=<you>
# optional: SANDBOX_TUNNEL_PORT / SANDBOX_TUNNEL_KEY
sandbox tunnel --profile vllm-remote plan   # print the exact ssh command
sandbox tunnel --profile vllm-remote up     # detached forward, pidfile in data/runtime/
sandbox health --profile vllm-remote        # /v1/models + json_object probe
sandbox eval sorter --local                 # against the remote weights
sandbox tunnel --profile vllm-remote down
```

`VLLM_API_KEY` (if you set one on the server) is picked up by both the
health probe and the tunnel'd profile via the `api_key_env` contract.

## Same tunnel, any GPU box

The CHTC server path is just one instance: `vllm-remote` + `sandbox tunnel`
works unchanged for a lab GPU box, a cloud VM, or a labmate's machine —
anything that can run `vllm serve` and that you can SSH to. CHTC is not
special here; only the job submission is.
