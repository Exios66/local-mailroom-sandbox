"""Parse the per-document tables out of tracked run reports and build the scorecard.

Writes per_doc.json and specialist-scorecard.html (scorecard.template.html with the
per-document rows injected). Run from the repo root:

    python reports/dashboard/extract_per_doc.py
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = {
    "insurance": "insurance/RUN-20-INSURANCE-CLAIMS-SPECIALIST-AWQ-REPORT.md",
    "correspondence_a": "correspondence/RUN-20-CORRESPONDENCE-SPECIALIST-AWQ-REPORT.md",
    "correspondence_b": "correspondence/RUN-50-CORRESPONDENCE-SPECIALIST-AWQ-REPORT.md",
    "contracts_c8": "contract/RUN-20-CONTRACTS-AWQ-C8-REPORT.md",
}
ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*`(DOC-[0-9a-f]+)`\s*\|(.*)\|\s*$")


def num(s):
    s = s.strip()
    return None if s in ("None", "") else float(s)


def parse(path):
    rows = []
    in_section = False
    for line in (ROOT / path).read_text().splitlines():
        if line.startswith("## "):
            in_section = line.startswith("## Per-document")
        m = ROW.match(line) if in_section else None
        if not m:
            continue
        subclass, overall, f1, lat, ptok, ctok, err = [c.strip() for c in m.group(3).split("|")]
        rows.append({
            "doc": m.group(2), "subclass": subclass, "overall": num(overall),
            "f1": num(f1), "latency": num(lat), "prompt": num(ptok),
            "completion": num(ctok), "error": None if err == "None" else err,
        })
    return rows


out = {k: parse(v) for k, v in RUNS.items()}
for k, v in out.items():
    print(k, len(v))
HERE = pathlib.Path(__file__).parent
payload = json.dumps(out, separators=(",", ":"))
(HERE / "per_doc.json").write_text(payload)
template = (HERE / "scorecard.template.html").read_text()
(HERE / "specialist-scorecard.html").write_text(template.replace("/*__PER_DOC__*/", payload))
