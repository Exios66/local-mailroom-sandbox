"""Chunk-window figures (#214): computed titles, house lint and byte-identical rebuilds. Offline."""

from __future__ import annotations

import json

from mailroom_sandbox import figure_style as fs
from mailroom_sandbox import window_figures as wf


def _doc(i: int, quality: float, *, windows: int = 2, failed: int = 0, confidence: float = 0.8) -> dict:
    return {"id": f"d{i}", "chars": 40_000 * windows, "quality": quality, "confidence": confidence,
            "windows": [(confidence + 0.01 * w, 40_000) for w in range(windows)], "failed_windows": failed}


def _runs():
    base = [_doc(i, 0.5 + 0.03 * i, failed=int(i < 3)) for i in range(12)]
    cand = [_doc(i, 0.55 + 0.05 * (i % 6), windows=2 + i % 3, confidence=0.7 + 0.02 * (i % 7)) for i in range(12)]
    return [("Contracts r1", base), ("Contracts r2", cand), ("Merger agreements", [_doc(i, 0.1) for i in range(5)])]


def _title(svg: str) -> str:
    import re

    block = re.search(r'<g id="title"[^>]*>(.*?)</g>', svg, re.S).group(1)
    return " ".join(re.findall(r"<text[^>]*>(.*?)</text>", block, re.S))


def test_window_figures_compute_their_titles_and_pass_the_house_lint():
    figs, table = wf.build(_runs(), base="Contracts r1", cand="Contracts r2", source="Source: fixture")
    assert set(figs) == {"runs", "paired", "window-rules", "confidence", "window-count"}
    assert all(fs.lint_svg(svg) == [] for svg in figs.values())
    assert _title(figs["paired"]).startswith("Documents losing a window fell from 3 to 0; mean quality moved +")
    assert _title(figs["runs"]).endswith("merger agreements scored 0.10")
    assert len(table) == 29 and {"run", "quality", "confidence", "windows", "failed_windows"} <= set(table[0])


def test_window_figures_are_byte_identical_across_builds():
    one, _ = wf.build(_runs(), base="Contracts r1", cand="Contracts r2", source="Source: fixture")
    two, _ = wf.build(_runs(), base="Contracts r1", cand="Contracts r2", source="Source: fixture")
    assert one == two


def test_a_ranking_with_too_few_misses_says_so():
    cand = [_doc(i, 0.9) for i in range(10)] + [_doc(10, 0.2)]
    figs, _ = wf.build([("A", cand), ("B", cand)], base="A", cand="B", source="Source: fixture")
    assert _title(figs["confidence"]) == "Too few documents on one side of the target to judge the confidence"
    assert _title(figs["window-rules"]).startswith("Too few documents")


def test_an_agreement_best_title_names_agreement_not_a_merge_rule():
    # Agreement is the unique top AUROC (1.0) while all three confidence merge
    # rules sit at chance: the title must name agreement, never RULE_LABELS
    # (CodeAnt + CodeRabbit, #402 — the KeyError regression).
    cand = [_doc(i, 0.9, confidence=0.8) for i in range(6)] + [_doc(i, 0.2, confidence=0.8) for i in range(6, 12)]
    for i, d in enumerate(cand):
        d["window_agreement"] = 1.0 if d["quality"] >= 0.7 else 0.2
    figs, _ = wf.build([("A", cand), ("B", cand)], base="A", cand="B", source="Source: fixture")
    assert _title(figs["window-rules"]) == (
        "Cross-window agreement separates good from poor documents best (AUROC 1.00)")


def test_an_agreement_row_plots_only_when_recorded():
    # Without a recorded agreement the figure keeps its three merge-rule rows;
    # with one, a fourth row appears and every label resolves.
    cand = [_doc(i, 0.9 if i < 6 else 0.2) for i in range(12)]
    base_figs, _ = wf.build([("A", cand), ("B", cand)], base="A", cand="B", source="Source: fixture")
    assert "Cross-window agreement" not in base_figs["window-rules"]
    for d in cand:
        d["window_agreement"] = 0.9
    ag_figs, _ = wf.build([("A", cand), ("B", cand)], base="A", cand="B", source="Source: fixture")
    assert "Cross-window agreement" in ag_figs["window-rules"]
    assert all(fs.lint_svg(svg) == [] for svg in ag_figs.values())


def test_load_run_reads_quality_confidence_and_windows_from_an_isolated_run(tmp_path):
    (tmp_path / "dataset.jsonl").write_text(json.dumps({"id": "d1", "expected_doc_class": "contract",
                                                         "doc_text": "x" * 10}) + "\n")
    pred = {"confidence": 0.85, "_window_confidences": [0.85, 0.9], "_window_lengths": [6, 6], "_failed_chunks": 0}
    (tmp_path / "items.jsonl").write_text(json.dumps({"item_id": "d1", "pred": pred,
                                                       "score": {"overall_extraction_score": 0.6}}) + "\n")
    [doc] = wf.load_run(tmp_path)
    assert (doc["quality"], doc["confidence"], len(doc["windows"]), doc["failed_windows"]) == (0.6, 0.85, 2, 0)
