#!/usr/bin/env bash
# Remove /goal from Claude Code. Leaves any project's .claude/goal.json files
# alone — only removes the skill, hook script, and the Stop hook registration.

set -euo pipefail

CLAUDE_HOME="${CLAUDE_HOME:-$HOME/.claude}"

echo ">> Uninstalling /goal from $CLAUDE_HOME"

rm -rf "$CLAUDE_HOME/skills/goal"
echo "  - removed $CLAUDE_HOME/skills/goal/"

rm -f "$CLAUDE_HOME/hooks/goal_continue.py"
echo "  - removed $CLAUDE_HOME/hooks/goal_continue.py"

SETTINGS="$CLAUDE_HOME/settings.json"
HOOK_CMD="$CLAUDE_HOME/hooks/goal_continue.py"

if [ -f "$SETTINGS" ]; then
python3 - <<PY
import json, pathlib, time
p = pathlib.Path("$SETTINGS")
s = json.loads(p.read_text())
hooks = s.get("hooks", {})
stop_hooks = hooks.get("Stop", [])
new_stop = []
removed = 0
for entry in stop_hooks:
    kept = [h for h in entry.get("hooks", []) if h.get("command") != "$HOOK_CMD"]
    removed += len(entry.get("hooks", [])) - len(kept)
    if kept:
        entry["hooks"] = kept
        new_stop.append(entry)
if removed:
    backup = p.with_suffix(f".json.bak.{int(time.time())}")
    backup.write_bytes(p.read_bytes())
    if new_stop:
        hooks["Stop"] = new_stop
    else:
        hooks.pop("Stop", None)
    if not hooks:
        s.pop("hooks", None)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(p)
    print(f"  - removed {removed} hook registration(s) from settings.json (backup: {backup.name})")
else:
    print("  - no /goal hook registration found in settings.json")
PY
fi

BIN_DIR="${BIN_DIR:-/usr/local/bin}"
for bin_name in goal goal-validate; do
  if [[ -f "$BIN_DIR/$bin_name" ]]; then
    rm -f "$BIN_DIR/$bin_name"
    echo "  - removed $BIN_DIR/$bin_name"
  fi
done

echo
echo "Done. Project-level .claude/goal.json files were NOT touched."
