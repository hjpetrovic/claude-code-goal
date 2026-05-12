#!/usr/bin/env bash
# Install /goal — a persistent-objective skill + Stop hook for Claude Code.
# Mirrors Codex's /goal command. Idempotent: safe to re-run.
#
# Usage:
#   ./install.sh                      # install into ~/.claude
#   CLAUDE_HOME=/path ./install.sh    # custom install root
#
# What it does:
#   1. Copies skills/goal/ -> $CLAUDE_HOME/skills/goal/
#   2. Copies hooks/goal_continue.py -> $CLAUDE_HOME/hooks/goal_continue.py (chmod +x)
#   3. Patches $CLAUDE_HOME/settings.json to register the Stop hook
#      (creates the file or merges into existing hooks.Stop without clobbering)
#   4. Backs up settings.json before patching

set -euo pipefail

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">> Installing /goal into $CLAUDE_HOME"

# 1. Skills
mkdir -p "$CLAUDE_HOME/skills/goal"
cp "$SCRIPT_DIR/skills/goal/SKILL.md" "$CLAUDE_HOME/skills/goal/SKILL.md"
cp "$SCRIPT_DIR/skills/goal/continuation_prompt.md" "$CLAUDE_HOME/skills/goal/continuation_prompt.md"
echo "  - skill files: $CLAUDE_HOME/skills/goal/"

# 2. Hook
mkdir -p "$CLAUDE_HOME/hooks"
cp "$SCRIPT_DIR/hooks/goal_continue.py" "$CLAUDE_HOME/hooks/goal_continue.py"
chmod +x "$CLAUDE_HOME/hooks/goal_continue.py"
echo "  - hook: $CLAUDE_HOME/hooks/goal_continue.py"

# 3. Settings patch
SETTINGS="$CLAUDE_HOME/settings.json"
HOOK_CMD="$CLAUDE_HOME/hooks/goal_continue.py"

python3 - <<PY
import json, os, pathlib, sys, time

settings_path = pathlib.Path("$SETTINGS")
hook_cmd = "$HOOK_CMD"

if settings_path.exists():
    backup = settings_path.with_suffix(f".json.bak.{int(time.time())}")
    backup.write_bytes(settings_path.read_bytes())
    print(f"  - settings backup: {backup}")
    try:
        s = json.loads(settings_path.read_text())
    except Exception as e:
        sys.exit(f"ERROR: {settings_path} is not valid JSON ({e}); refusing to clobber")
else:
    s = {}
    print(f"  - creating new settings.json")

hooks = s.setdefault("hooks", {})
stop_hooks = hooks.setdefault("Stop", [])

# already registered?
already = any(
    any(h.get("command") == hook_cmd for h in entry.get("hooks", []))
    for entry in stop_hooks
)
if already:
    print(f"  - hook already registered, leaving settings.json untouched")
else:
    stop_hooks.append({"hooks": [{"type": "command", "command": hook_cmd}]})
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(settings_path)
    print(f"  - registered Stop hook in {settings_path}")
PY

echo
echo "Done. Restart Claude Code for the hook to activate."
echo "Then in any project: /goal <your objective>"
