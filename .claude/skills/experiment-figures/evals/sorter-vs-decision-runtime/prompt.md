---
tags: [experiment-figures]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

I need figures comparing the LLM sorter with the decision model as sorter for the rb1 r13b smoke runs: rb1-r13b-smoke20b-llm-sorter-qwen3.7-flash is the reference, and rb1-r13b-smoke20b-decision-sorter-luna-v4.0.1 and rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1 are the decision arms. The runs are under data/runtime/runs in the main checkout. Show total run time head to head, and cost per 1,000 documents, plus whatever else you think the H5 decision needs. Save the SVGs to the output folder and write a short notes.md saying what each figure shows.
