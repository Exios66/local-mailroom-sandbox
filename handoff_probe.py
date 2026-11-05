#!/bin/bash
cd /mnt/c/Users/grant/sandbox-clone
/home/gemooslin/sandbox-venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "vendor/llm-mailroom/src")
sys.path.insert(0, "vendor/llm-dojo-scoring/src")
sys.path.insert(0, "src")
from mailroom_sandbox.runtime import activate
activate("lmstudio")  # sets DEFAULT_PROVIDER/generic base url exactly as pilot does
from agents.base import BaseAgent

# Capture what the LLM WOULD see; return a valid empty extraction.
captured = {}
def fake_call(self, user_message, **kw):
    captured.setdefault("msgs", []).append(user_message)
    return '{"confidence": 0.9}'
BaseAgent._call_llm = fake_call

from agents.corporate_records_specialist import CorporateRecordsSpecialist
handoff = "SORTER HANDOFF: doc_subclass=bylaws; subtype cue sentinel XYZ123"
agent = CorporateRecordsSpecialist()
# replicate _instantiate_specialist's except-branch exactly:
try:
    a = CorporateRecordsSpecialist(handoff_context=handoff)
except TypeError:
    a = CorporateRecordsSpecialist()
    a.handoff_context = handoff
a.extract("Entity bylaws text here.", pages=None, handoff_context=None)  # rely on attr
a2 = CorporateRecordsSpecialist()
a2.extract("Entity bylaws text here.", pages=None, handoff_context=handoff)

for i, m in enumerate(captured["msgs"]):
    print(f"call{i}: sentinel-in-prompt:", "XYZ123" in m)
PY
