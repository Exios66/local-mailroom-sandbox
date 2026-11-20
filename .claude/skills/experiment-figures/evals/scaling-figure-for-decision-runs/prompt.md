---
tags: [experiment-figures]
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

we're scaling the decision model sample up in steps. using the items in data/runtime/runs/rb1-r13b-formcal-intact-decision-luna-v4.0.1 (main checkout), make a figure that shows whether the park rate and the subclass accuracy are stable as n grows (take the documents in item order, cumulative). save it as an svg in the output folder with a one-paragraph notes.md on what it shows and how much to trust it
