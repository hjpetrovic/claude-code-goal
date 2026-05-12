You are working toward a persistent goal. Continue until the stopping condition is met or your budget is exhausted.

Objective:           {objective}
Stopping condition:  {stopping_condition}
Validation:          {validation_command}
Iteration:           {iter_used} / {iter_max}
Time used:           {elapsed}s / {budget}s
Do not change:       {do_not_change}
Reference:           {reference_files}

Recent checkpoints:
{checkpoints}

Continue the plan -> act -> verify -> iterate cycle:
1. State the current checkpoint briefly (one line).
2. Take the next concrete action toward the stopping condition.
3. Verify it (run the validation command, or describe how you verified).
4. Append a one-line entry to checkpoints[] in .claude/goal.json with the new timestamp and a summary.

If the stopping condition is met, set status="complete" in .claude/goal.json instead of continuing. If you are blocked, append a checkpoint describing what blocks you and call /goal pause.
