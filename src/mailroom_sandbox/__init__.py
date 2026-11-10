"""Offline-first experiment harness with frozen family source selection.

Reviewed vendor snapshots make a fresh checkout self-contained. Bootstrap
selects explicit sources, matching installed releases or verified release
caches before falling back to those tracked trees, without network access.
Source selection stays fixed for the process; new runs record its provenance.
"""

from __future__ import annotations

import os
import sys

from mailroom_sandbox import dojo_source as _dojo_source  # noqa: E402

_dojo_source.choose()

from mailroom_sandbox import pipeline_source as _pipeline_source  # noqa: E402

_pipeline_source.choose()


def prefer_own_venv_tools() -> None:
    """Run this venv's pinned CLIs even when the venv is not activated.

    ``.venv/bin/sandbox`` would otherwise shell out to whichever ``modal`` comes
    first on ``PATH``, which can be a global install on another SDK version.
    """
    if sys.prefix == sys.base_prefix:
        return
    own_bin = os.path.dirname(sys.executable)
    entries = (os.environ.get("PATH") or os.defpath).split(os.pathsep)
    if entries[0] != own_bin:
        os.environ["PATH"] = os.pathsep.join([own_bin, *(e for e in entries if e != own_bin)])


from mailroom_sandbox.runtime import activate

__version__ = "0.3.0"
__all__ = ["activate", "__version__"]
