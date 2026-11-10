"""Default port for the pipeline-floor viewer.

Kept here so the CLI parser help can render ``sandbox floor --port`` without
importing ``tui.floor_app`` (which reaches ``job.checkpoint`` and its unix-only
``fcntl`` import — building ``sandbox --help`` must stay native-Windows-safe).
"""

from __future__ import annotations

DEFAULT_VIEWER_PORT = 8769  # 8765 web, 8766 watch-live, 8767 board, 8768 board-demo — all claimed
