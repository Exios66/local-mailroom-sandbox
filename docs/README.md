<div align="center">

# 📚 Sandbox Documentation

**Documentation for the local-mailroom-sandbox package.**

</div>

---

## Purpose

Documentation for the local-mailroom-sandbox package, covering:
- Local development setup
- Configuration guide
- Testing procedures
- **[Agent environment and dispatch](agent-dispatch.md)** — execution identity, delegation contracts, recovery, evidence and durable handoffs
- **[Agent instruction maintenance](agent-instruction-maintenance.md)** — routine validation of instructions, versions, releases, references and experiment status
- **[Mailroom themed logging & live watch](pretty-logging/mailroom-themed-logging.md)** — `sandbox watch` / `--web`, Modal dispatch log tail, SAND-032 operator paths
- **[Pipeline floor viewer](floor.md)** — live run history, offline replay, digest semantics and troubleshooting
- **[Named datasets](datasets/named-datasets.md)** — registry fields, environment paths, source/subset identity and migration
- **[Job lifecycle](jobs.md)** — preflight, immutable generations, execution and resume
- **[CI verification](../.circleci/README.md)** — required checks, artifacts, cache/worker configuration and runtime comparison

## Related Files

- `README.md` — Package overview
- [`runbooks/README.md`](runbooks/README.md) — operator runbooks (singular L4 Qwen3-8B + improved configs)
- [`setting-up/QUICKSTART.md`](setting-up/QUICKSTART.md) — install + full CLI reference
- [`setting-up/LAYOUT.md`](setting-up/LAYOUT.md) — which folder owns what
- [`pretty-logging/mailroom-watch-web.md`](pretty-logging/mailroom-watch-web.md) — browser watch cheat sheet
- [`benchmark-l4.md`](modal/benchmark-l4.md) — catalog pointer
- `src/` — Source code
- `config/` — Configuration
