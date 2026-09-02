<div align="center">

# ⚙️ Sandbox Configuration

**Configuration files for the local-mailroom-sandbox package.**

</div>

---

## Structure

| Path | Contents |
|:---|:---|
| [`profiles/`](profiles/) | Environment profiles |

## Configuration Files

| File | Purpose |
|:---|:---|
| `taxonomy.yaml` | Document classes and agent definitions |
| `env.example` | Environment variables template |

## Usage

Copy `env.example` to `.env` and configure:
- LLM provider settings
- Observability backends
- Storage paths

## Related Files

- `src/` — Source code
- `data/` — Test data
