#!/usr/bin/env python3
"""
Stop hook for the /goal skill — Claude Code's equivalent of Codex's continuation loop.

Reads <cwd-or-ancestor>/.claude/goal.json. If a goal is active and not yet
finished, emits a 'block' decision with a continuation prompt that keeps Claude
iterating until a stop condition is met.

Stop conditions (first match wins):
  1. Status != active
  2. iterations_used >= max_iterations
  3. Wall-clock elapsed > max_wall_clock_seconds
  4. Validation command exits 0
  5. Zero-progress turn (no tool calls in last assistant message) x3 consecutive
  6. Model wrote status='complete' to the state file (handled by case 1)

On any exception: log to .claude/goal.log and exit 0 (never block the user).
"""
import json
import os
import sys
import subprocess
import fcntl
import traceback
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = "goal.json"
LOCK_FILE = "goal.lock"
LOG_FILE = "goal.log"
TEMPLATE = Path.home() / ".claude" / "skills" / "goal" / "continuation_prompt.md"
VALIDATION_TIMEOUT = 60
LOG_MAX_LINES = 1000
ZERO_PROGRESS_THRESHOLD = 3


def find_state_dir(start: Path):
    """Walk up from start dir looking for .claude/goal.json. Return the .claude dir."""
    p = start.resolve()
    while True:
        if (p / ".claude" / STATE_FILE).exists():
            return p / ".claude"
        if p.parent == p:
            return None
        p = p.parent


def log(claude_dir: Path, msg: str):
    try:
        log_path = claude_dir / LOG_FILE
        ts = datetime.now(timezone.utc).isoformat()
        with open(log_path, "a") as f:
            f.write(f"[{ts}] {msg}\n")
        with open(log_path) as f:
            lines = f.readlines()
        if len(lines) > LOG_MAX_LINES:
            with open(log_path, "w") as f:
                f.writelines(lines[-LOG_MAX_LINES:])
    except Exception:
        pass


def atomic_write(path: Path, data: dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def read_last_assistant(transcript_path: str):
    if not transcript_path or not Path(transcript_path).exists():
        return None
    try:
        with open(transcript_path) as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") == "assistant":
                return obj
        return None
    except Exception:
        return None


def turn_had_tools(msg) -> bool:
    if not msg:
        return False
    content = msg.get("message", {}).get("content", [])
    if isinstance(content, str):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return True
    return False


def run_validation(cmd: str, cwd: Path) -> bool:
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd, timeout=VALIDATION_TIMEOUT,
            capture_output=True, text=True,
        )
        return r.returncode == 0
    except Exception:
        return False


DEFAULT_TEMPLATE = """You are working toward a persistent goal. Continue until the stopping condition is met.

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
1. State the current checkpoint briefly.
2. Take the next concrete action toward the stopping condition.
3. Verify it.
4. Append a one-line entry to checkpoints[] in .claude/goal.json.

If the stopping condition is met, set status="complete" in .claude/goal.json instead of continuing.
"""


def build_prompt(state: dict) -> str:
    template = TEMPLATE.read_text() if TEMPLATE.exists() else DEFAULT_TEMPLATE
    started = datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
    elapsed = int((datetime.now(timezone.utc) - started).total_seconds())
    cps = state.get("checkpoints", [])[-5:]
    cp_text = "\n".join(f"- {c.get('at','?')}: {c.get('summary','?')}" for c in cps) or "(none yet)"
    return template.format(
        objective=state.get("objective", ""),
        stopping_condition=state.get("stopping_condition", ""),
        validation_command=state.get("validation_command") or "model-declared",
        do_not_change=", ".join(state.get("do_not_change", [])) or "(unspecified)",
        reference_files=", ".join(state.get("reference_files", [])) or "(none)",
        iter_used=state.get("iterations_used", 0),
        iter_max=state.get("max_iterations", 50),
        elapsed=elapsed,
        budget=state.get("max_wall_clock_seconds", 7200),
        checkpoints=cp_text,
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # Claude Code passes this when we're already in a stop-hook continuation —
    # don't recurse, let the model speak.
    if payload.get("stop_hook_active"):
        sys.exit(0)

    cwd = Path(payload.get("cwd") or os.getcwd())
    transcript_path = payload.get("transcript_path", "")

    claude_dir = find_state_dir(cwd)
    if not claude_dir:
        sys.exit(0)

    state_path = claude_dir / STATE_FILE
    lock_path = claude_dir / LOCK_FILE

    try:
        with open(lock_path, "w") as lock_f:
            try:
                fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                log(claude_dir, "lock contended, skipping")
                sys.exit(0)

            try:
                state = json.loads(state_path.read_text())
            except Exception as e:
                log(claude_dir, f"goal.json malformed: {e}")
                sys.exit(0)

            goal_id = state.get("goal_id")
            status = state.get("status")

            if status != "active":
                log(claude_dir, f"status={status}, no-op")
                sys.exit(0)

            now = datetime.now(timezone.utc)
            started = datetime.fromisoformat(state["started_at"].replace("Z", "+00:00"))
            elapsed = (now - started).total_seconds()
            iter_used = state.get("iterations_used", 0)
            iter_max = state.get("max_iterations", 50)
            budget = state.get("max_wall_clock_seconds", 7200)

            if iter_used >= iter_max:
                state["status"] = "budget_limited"
                state["ended_at"] = now.isoformat()
                atomic_write(state_path, state)
                log(claude_dir, f"budget_limited: iterations {iter_used}/{iter_max}")
                sys.exit(0)

            if elapsed > budget:
                state["status"] = "budget_limited"
                state["ended_at"] = now.isoformat()
                atomic_write(state_path, state)
                log(claude_dir, f"budget_limited: wall-clock {int(elapsed)}s>{budget}s")
                sys.exit(0)

            val_cmd = state.get("validation_command")
            if val_cmd:
                if run_validation(val_cmd, claude_dir.parent):
                    state["status"] = "complete"
                    state["ended_at"] = now.isoformat()
                    state.setdefault("checkpoints", []).append({
                        "at": now.isoformat(),
                        "summary": f"validation passed: {val_cmd}",
                    })
                    atomic_write(state_path, state)
                    log(claude_dir, "complete: validation passed")
                    sys.exit(0)

            last = read_last_assistant(transcript_path)
            if last is not None and not turn_had_tools(last):
                zp = state.get("zero_progress_streak", 0) + 1
                state["zero_progress_streak"] = zp
                if zp >= ZERO_PROGRESS_THRESHOLD:
                    state["status"] = "complete"
                    state["ended_at"] = now.isoformat()
                    state.setdefault("checkpoints", []).append({
                        "at": now.isoformat(),
                        "summary": f"stopped: {zp} consecutive zero-progress turns",
                    })
                    atomic_write(state_path, state)
                    log(claude_dir, f"complete: zero-progress x{zp}")
                    sys.exit(0)
                log(claude_dir, f"zero-progress streak={zp}, continuing")
            else:
                state["zero_progress_streak"] = 0

            # detect external replacement before writing iteration counter
            try:
                fresh = json.loads(state_path.read_text())
                if fresh.get("goal_id") != goal_id:
                    log(claude_dir, "goal_id changed mid-flight, bailing")
                    sys.exit(0)
            except Exception:
                sys.exit(0)

            state["iterations_used"] = iter_used + 1
            atomic_write(state_path, state)

            prompt = build_prompt(state)
            print(json.dumps({"decision": "block", "reason": prompt}))
            log(claude_dir, f"continuation injected, iter {iter_used+1}/{iter_max}")
            sys.exit(0)

    except Exception:
        try:
            log(claude_dir, f"exception: {traceback.format_exc()}")
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    main()
