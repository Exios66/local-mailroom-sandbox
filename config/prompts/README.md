# Local prompt variants

These templates override mailroom's Langfuse-managed prompts (`get_managed_prompt`)
for a single experiment cell. They are shorter and more JSON-strict than the
production templates — local 7B/8B models need the literal token `json` and a
tighter schema reminder.

Register a variant by filename stem (`sorter_local_v0`). Pass `--prompt sorter_local_v0`
to `sandbox eval` / `sandbox matrix`. Unset = mailroom in-code fallbacks.
