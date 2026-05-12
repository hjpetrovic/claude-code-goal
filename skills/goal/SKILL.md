---
name: goal
description: Attach a durable, multi-turn objective to the current project. Claude will plan → act → verify → iterate until a stated stopping condition is met. Modeled on Codex's /goal command. Use when the user explicitly invokes /goal — never auto-create goals from ordinary tasks.
---

# /goal — Persistent objective for long-running autonomous work

## Hard rule

**Create a goal only when explicitly requested by the user.** Do not infer a goal from an ordinary task. If the user just asks for a feature, a fix, or a refactor, do the work directly — do not write `.claude/goal.json`. A goal is a long-horizon commitment, not a substitute for taking action now.

## What this skill does

A goal is a persistent objective stored in `<project>/.claude/goal.json`. A registered `Stop` hook reads this file after every turn. If the goal is active and not yet complete, the hook injects a continuation prompt that keeps you iterating. The loop terminates only when one of these stop conditions is hit:

1. The user sets `status` to anything other than `active` (pause/clear/complete).
2. `iterations_used >= max_iterations`.
3. Wall-clock elapsed > `max_wall_clock_seconds`.
4. The `validation_command` exits 0.
5. Three consecutive zero-tool-call turns (zero-progress detection).
6. You write `status = "complete"` directly to `.claude/goal.json`.

This skill defines the subcommands the user invokes; the hook handles the iteration loop. **Do not write to `.claude/goal.json` outside the subcommands documented below.**

## Subcommands

### `/goal <objective>` — set a new goal

When the user types `/goal <objective text>`, **before writing anything to disk**, walk them through filling out the rest of the schema in one short exchange. Ask for, in this order:

1. **Stopping condition** (required) — what does "done" look like? Must be verifiable.
2. **Validation command** (optional) — shell command whose exit-0 means done. e.g. `pnpm test:integration auth`. Leave blank if validation is manual.
3. **Do not change** (optional) — list of paths/files/invariants Claude must not touch.
4. **Reference files / docs** (optional) — what to read for context.
5. **Iteration budget** (default 50) and **wall-clock budget** (default 7200 seconds / 2 hours).

If the user gave you enough in the first invocation, skip the questions and confirm the values you inferred. **Do not invent stopping conditions or budgets** — ask if missing.

Then write the state file using the schema below.

### `/goal` — show status

Read `.claude/goal.json` and report: objective, status, iterations used/max, elapsed/budget, last 3 checkpoints. Be terse — this is a status check, not a summary.

### `/goal pause`

Set `status = "paused"`. The hook will no-op until resumed.

### `/goal resume`

Set `status = "active"`. The hook will re-engage on the next turn.

### `/goal complete`

Set `status = "complete"`. Use this to manually mark done.

### `/goal clear`

Delete `.claude/goal.json`. Confirm with the user first — this is destructive.

## State schema (`.claude/goal.json`)

```json
{
  "goal_id": "uuid-v4-generated-fresh-on-every-set",
  "objective": "string — what to achieve",
  "stopping_condition": "string — what 'done' looks like, must be verifiable",
  "validation_command": "string|null — shell command whose exit 0 means done",
  "do_not_change": ["paths", "or", "invariants"],
  "reference_files": ["docs", "or", "files", "to", "read"],
  "status": "active | paused | budget_limited | complete",
  "created_at": "ISO8601 UTC",
  "started_at": "ISO8601 UTC",
  "ended_at": "ISO8601 UTC (set when status becomes terminal)",
  "iterations_used": 0,
  "max_iterations": 50,
  "max_wall_clock_seconds": 7200,
  "zero_progress_streak": 0,
  "checkpoints": [
    {"at": "ISO8601 UTC", "summary": "one-line progress note"}
  ]
}
```

### Writing the state file (set/resume/pause/complete/clear)

- Use `python3 -c '...'` or the Write tool — never edit by hand and forget to format.
- On `/goal <objective>`: generate a fresh UUID (`python3 -c "import uuid; print(uuid.uuid4())"`), set `created_at` and `started_at` to now (UTC, ISO8601), `status = "active"`, `iterations_used = 0`, `zero_progress_streak = 0`, `checkpoints = []`.
- On `pause/resume/complete`: only flip `status` (and `ended_at` for terminal states). Preserve everything else.
- On `clear`: `rm .claude/goal.json`. Confirm first.

### Appending a checkpoint during iteration

Every continuation turn should append one checkpoint summarising progress. Read the file, append to `checkpoints[]`, write atomically:

```python
import json, datetime
from pathlib import Path
p = Path(".claude/goal.json")
s = json.loads(p.read_text())
s.setdefault("checkpoints", []).append({
    "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "summary": "what you just did, one line"
})
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(s, indent=2))
tmp.replace(p)
```

## How a goal-driven session feels

1. User types `/goal Finish the auth migration so integration tests pass and the legacy path still rolls back cleanly`.
2. You ask for validation command, do-not-change list, budgets. User answers.
3. You write `.claude/goal.json` with `status=active`.
4. You start work, take an action, append a checkpoint.
5. Claude Code reaches end-of-turn. The Stop hook fires.
6. The hook checks the file: not done. Injects a continuation prompt.
7. You receive the prompt, take the next action, append a checkpoint.
8. Loop continues until the validation command exits 0 (or budget hits, or you decide to pause/complete).

## Failure modes to watch for

- **Validation command takes >60s**: hook timeout fires; treated as not-yet-passed. Add a faster check, or accept iteration progress.
- **Zero-progress streak ticking up**: you produced no tool calls. The hook escalates after 3 consecutive zero-tool turns and marks the goal complete. If this isn't what you want, take at least one concrete action per turn.
- **Hook didn't fire**: check `.claude/goal.log` in the project for diagnostics. Check `~/.claude/settings.json` registers `~/.claude/hooks/goal_continue.py` under `hooks.Stop`.
- **Malformed `goal.json`**: hook logs and bails; the loop just stops. Fix the JSON or `/goal clear` and restart.

## What this skill does NOT do

- It does not auto-create goals. The user must type `/goal <objective>`.
- It does not run validation commands itself — that's the hook's job.
- It does not pause/resume automatically. Plan mode entry, for example, requires the user to `/goal pause` first.
- It does not support multiple concurrent goals per project. One goal per `.claude/goal.json`.
