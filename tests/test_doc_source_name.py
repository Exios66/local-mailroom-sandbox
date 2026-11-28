"""The inbox name of a pipeline document is unique per document and readable.

Every pipeline document is written into the one shared inbox, and the vendored claim registry
(``pipeline.bins._remember_claim``) and the trace seed (``graph.build_graph.run_pipeline``) key on
that name. live-smoke-rc11-0100 draws two Enron messages both named ``30.`` (different mailboxes):
at concurrency 4 one could overwrite the other's text in the inbox, or be archived from the other's
claimed file. The name also came out as ``30..txt`` / ``30..json`` in the archive.
"""
from __future__ import annotations

from mailroom_sandbox.eval import runners


def test_same_basename_rows_get_distinct_inbox_names():
    a = {"id": "DOC-aaaaaaaaaaaaaaaa", "filename": "crandell-s/inbox/30.", "doc_text": "first"}
    b = {"id": "DOC-bbbbbbbbbbbbbbbb", "filename": "lay-k/sent/30.", "doc_text": "second"}
    assert runners._inbox_name(a) != runners._inbox_name(b)


def test_maildir_name_keeps_its_folders_and_drops_the_trailing_dot():
    row = {"id": "DOC-ed8721660c7317e7", "filename": "crandell-s/inbox/30.", "doc_text": "x"}
    assert runners._inbox_name(row) == "crandell-s_inbox_30__DOC-ed8721660c7317e7"


def test_named_file_keeps_its_name_and_suffix():
    row = {"id": "DOC-e63259fddf5b43a5", "filename": "CARDAX,INC_08_19_2014-EX-10.1-COLLABORATION AGREEMENT.PDF"}
    assert runners._inbox_name(row) == "CARDAX,INC_08_19_2014-EX-10.1-COLLABORATION AGREEMENT__DOC-e63259fddf5b43a5.PDF"


def test_row_without_a_filename_or_id():
    assert runners._inbox_name({"id": "DOC-1"}) == "DOC-1.txt"
    assert runners._inbox_name({}) == "doc.txt"
    assert runners._inbox_name({"filename": "notes.md"}) == "notes.md"


def test_materialized_text_rows_do_not_collide(tmp_path):
    a = {"id": "DOC-aaaaaaaaaaaaaaaa", "filename": "crandell-s/inbox/30.", "doc_text": "first"}
    b = {"id": "DOC-bbbbbbbbbbbbbbbb", "filename": "lay-k/sent/30.", "doc_text": "second"}
    qa, qb = runners._materialize_row(a, tmp_path, unique=True), runners._materialize_row(b, tmp_path, unique=True)
    assert qa != qb
    assert (qa.name, qa.read_text()) == ("crandell-s_inbox_30__DOC-aaaaaaaaaaaaaaaa.txt", "first")
    assert (qb.name, qb.read_text()) == ("lay-k_sent_30__DOC-bbbbbbbbbbbbbbbb.txt", "second")
    pdf = runners._materialize_row({"id": "DOC-c", "filename": "deal/EX-10.1 AGREEMENT.PDF", "doc_text": "t"}, tmp_path, unique=True)
    assert pdf.name == "EX-10.1 AGREEMENT__DOC-c.txt"


def test_family_api_staging_keeps_the_plain_basename(tmp_path):
    row = {"id": "DOC-a", "filename": "crandell-s/inbox/30.", "doc_text": "x"}
    assert runners._doc_source_name(row) == "30."
    assert runners._materialize_row(row, tmp_path).name == "30..txt"
