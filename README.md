# /goal for Claude Code

A persistent-objective skill and Stop hook that gives [Claude Code](https://claude.com/claude-code) something close to OpenAI Codex's `/goal` command: a durable, multi-turn loop that keeps Claude iterating until a stated stopping condition is met.

> **Status:** experimental. POSIX-only (uses `fcntl`). Tested on macOS.

## What it does

Codex's `/goal` attaches a durable objective to a thread; Codex then runs `plan → act → verify → iterate` across many turns until the goal is done or a budget is hit. Claude Code doesn't have that loop natively. This repo adds it via:

- A **skill** at `~/.claude/skills/goal/SKILL.md` defining `/goal` and its subcommands.
- A **Stop hook** at `~/.claude/hooks/goal_continue.py` that fires after every Claude turn, reads `<project>/.claude/goal.json`, and either re-injects a continuation prompt or marks the goal complete.
- A **`goal` CLI wrapper** (`bin/goal`) that pre-arms `goal.json` before invoking `claude --print`, making the loop work in non-interactive mode.
- A **`goal-validate` helper** (`bin/goal-validate`) with richer stopping conditions than bare `test -f`.

## Install

```bash
git clone https://github.com/hjpetrovic/claude-code-goal.git
cd claude-code-goal
./install.sh
```

Then restart Claude Code so it picks up the new hook.

Custom install root:

```bash
CLAUDE_HOME=/path/to/.claude ./install.sh
```

## Uninstall

```bash
./uninstall.sh
```

Project-level `.claude/goal.json` files are left in place.

## Usage

### Interactive mode (Claude Code terminal)

In any project, after restarting Claude Code:

```
/goal Migrate auth middleware to compliance spec — done when integration tests pass and legacy path still rolls back cleanly
```

Claude will ask for:
- A validation command (shell command whose exit 0 means done)
- A do-not-change list
- Iteration and wall-clock budgets

Then it writes `.claude/goal.json` and starts iterating. After every turn, the Stop hook decides whether to keep going.

### Non-interactive / `--print` mode

When calling `claude --print` (e.g. from scripts or orchestrators like OpenClaw), use the `goal` wrapper instead. It pre-arms `goal.json` before handing off to Claude, so the loop is engaged from the first turn:

```bash
goal "Migrate auth middleware — done when integration tests pass" \
  --validation "pnpm test:integration" \
  --no-change "src/legacy/**" \
  --max-iterations 20
```

> **Why this matters:** in `--print` mode, `/goal` passed as a prompt string is treated as plain text — the SKILL.md slash-command logic never runs and `goal.json` is never written. The `goal` wrapper solves this by writing the state file directly.

### Richer validation with `goal-validate`

Instead of `test -f file.md` (just checks existence), use the `goal-validate` helper:

```bash
# All files exist
goal-validate files chart_heavy_template.md narrative_template.md

# Word count within budget
goal-validate words narrative_template.md 400

# Required sections present
goal-validate sections narrative_template.md HOOK CHART

# Chart marker count in range
goal-validate charts chart_heavy_template.md 4 8

# Compose with &&
goal-validate files narrative.md && goal-validate words narrative.md 400
```

Pass any of these as `--validation` to `goal`:

```bash
goal "Write two Monday Data templates" \
  --validation "goal-validate files chart_heavy_template.md narrative_template.md && goal-validate words narrative_template.md 400"
```

### Subcommands

| Command | Effect |
|---|---|
| `/goal <objective>` | Set a new goal |
| `/goal` | Show status, iterations used, last checkpoint |
| `/goal pause` | Pause the continuation loop |
| `/goal resume` | Resume |
| `/goal complete` | Manually mark done |
| `/goal clear` | Delete the goal |

## Stop conditions

The hook stops the loop when **any** of these fire:

1. Status is not `active` (paused/cleared/complete).
2. `iterations_used >= max_iterations` (default 50).
3. Wall-clock elapsed > `max_wall_clock_seconds` (default 7200, i.e. 2 hours).
4. The configured `validation_command` exits 0 within 60 seconds.
5. Three consecutive zero-tool-call turns.
6. Claude writes `status = "complete"` to `.claude/goal.json`.

All five are mirrored from Codex's `/goal` implementation.

## State file (`<project>/.claude/goal.json`)

```json
{
  "goal_id": "uuid-v4",
  "objective": "what to achieve",
  "stopping_condition": "what 'done' looks like",
  "validation_command": "pnpm test:integration auth",
  "do_not_change": ["src/legacy/**"],
  "reference_files": ["docs/migration.md"],
  "status": "active",
  "created_at": "ISO8601 UTC",
  "started_at": "ISO8601 UTC",
  "iterations_used": 0,
  "max_iterations": 50,
  "max_wall_clock_seconds": 7200,
  "checkpoints": [
    {"at": "ISO8601 UTC", "summary": "one-line progress note"}
  ]
}
```

## Diagnostics

Every hook decision is logged to `<project>/.claude/goal.log` (rotated to last 1000 lines). If the loop doesn't fire when you expect it to, check that log first.

## Limitations

- **`/goal` in `--print` mode won't arm the loop** — use the `goal` CLI wrapper instead (see above). In `--print` mode, slash commands are plain text in the prompt; SKILL.md logic is never invoked.
- **Single-turn tasks bypass iteration entirely** — the Stop hook fires once, sees the validation command pass immediately, and marks complete. The loop only adds value when a task genuinely requires multiple attempts to pass validation. Design your validation commands to be initially failing.
- **POSIX-only**: uses `fcntl` for lock files; won't work on Windows without a port.
- **One goal per project**: same as Codex.
- **Zero-progress detection** depends on Claude Code's transcript JSONL format being stable.
- **Plan mode**: not auto-detected — call `/goal pause` before entering plan mode.
- **Validation timeout** is 60 seconds; slower commands won't pass.

## Credits

Modeled on the [Codex `/goal` command](https://developers.openai.com/codex/use-cases/follow-goals); architecture inspired by [Pat Leeman's writeup](https://gist.github.com/patleeman/b1b5768393f9bf2f60865b1defeeb819) of the upstream implementation.

## License

MIT.
