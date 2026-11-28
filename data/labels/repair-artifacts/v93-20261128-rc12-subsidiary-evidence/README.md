# Subsidiary evidence correction (2026-11-28)

Review bots on mailroom-issues #254 and sandbox #473 reported that `DOC-91af5bdd6f0ad4bb`'s
`subsidiaries` value lists `Motor Cargo` twice, because its evidence span (512–523) sat inside the
span of `Motor Cargo Industries, Inc.` (512–540). A full read of the 866-character exhibit shows the
value is right. The exhibit lists ten subsidiaries, one per line, including both:

```text
Motor Cargo Industries, Inc., a Utah corporation      (offset 512)
Motor Cargo, a Utah corporation                       (offset 562)
```

Only the evidence was wrong. The label quoted `Motor Cargo`, which the gate locates at its first
occurrence, inside the longer name.

[`review.jsonl`](review.jsonl) holds the one correction: a `correct` with the same ten values. The
fifth quote is now `Motor Cargo, a Utah corporation`, which can only match the entry's own line
(562–593). The record had no earlier review, and `decisions.jsonl` does not settle it, so no
`supersedes` is needed. The command was:

```bash
scripts/gold_labels.py review --corpus <pinned corpus dir> --review review.jsonl
```

Scoring reads values, not spans, so no score changes. The immutable cut `9.3.1-rc.11` keeps the old
span; the next cut carries the corrected one.
