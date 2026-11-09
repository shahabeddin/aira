#!/usr/bin/env sh
# uninstall.sh — remove the Claude Code integration for Aira.
#
# This is the precise inverse of setup.md steps 2–3. It removes ONLY the Claude
# Code surface area: the slash-command files and the AGENT_TEAM_TOOLS env var.
# It NEVER touches the repo, the projects/ data, inboxes, tickets, or the board
# server process. Re-run setup.md (or re-export the var) to reinstall.
#
# Usage:  sh uninstall.sh            # remove commands + env var
#         sh uninstall.sh --dry-run  # show what would change, change nothing

set -eu

COMMANDS="team-up.md set-team.md check-inbox.md ticket.md lead.md team-send.md"
GLOBAL_CMD_DIR="$HOME/.claude/commands"
# The repo's own .claude/commands ships the source files setup.md copies FROM.
# Never delete those — only delete installed copies elsewhere.
REPO_CMD_DIR="$(cd "$(dirname "$0")" && pwd)/.claude/commands"
LOCAL_CMD_DIR="$(pwd)/.claude/commands"
MANIFEST="$(cd "$(dirname "$0")" && pwd)/external-skills.txt"
RCS="$HOME/.zshrc $HOME/.bashrc"

# Append external-skill filenames (from external-skills.txt) to the removal set.
# Format: <filename> <url>, # comments. Content isn't vendored, so we just remove the
# installed copies — same dirs as the built-in commands.
EXT_COMMANDS=""
if [ -f "$MANIFEST" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|\#*) continue ;;
        esac
        # first whitespace-separated token is the filename
        fn="${line%%[ 	]*}"
        [ -n "$fn" ] && EXT_COMMANDS="$EXT_COMMANDS $fn"
    done < "$MANIFEST"
fi

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

rm_cmd() {  # rm_cmd <path>
    if [ "$DRY" -eq 1 ]; then echo "  would rm  $1"; else rm -f "$1" && echo "  removed   $1"; fi
}

strip_rc() {  # strip_rc <rcfile> — delete lines exporting AGENT_TEAM_TOOLS
    rc="$1"
    [ -f "$rc" ] || return 0
    if ! grep -q 'AGENT_TEAM_TOOLS' "$rc"; then
        echo "  skip      $rc (no AGENT_TEAM_TOOLS line)"
        return 0
    fi
    if [ "$DRY" -eq 1 ]; then
        echo "  would strip AGENT_TEAM_TOOLS from $rc"
        grep -n 'AGENT_TEAM_TOOLS' "$rc" | sed 's/^/    /'
        return 0
    fi
    cp "$rc" "$rc.bak.aira"
    grep -v 'AGENT_TEAM_TOOLS' "$rc" > "$rc.tmp" && mv "$rc.tmp" "$rc"
    echo "  stripped  $rc (backup: $rc.bak.aira)"
}

echo "Uninstalling Aira Claude Code integration"
[ "$DRY" -eq 1 ] && echo "DRY RUN — nothing will be changed."
echo

echo "1. Slash commands:"
for f in $COMMANDS $EXT_COMMANDS; do
    [ -f "$GLOBAL_CMD_DIR/$f" ] && rm_cmd "$GLOBAL_CMD_DIR/$f"
    # local install: only if present AND NOT the repo's own source dir
    if [ -f "$LOCAL_CMD_DIR/$f" ] && [ "$(cd "$LOCAL_CMD_DIR" && pwd)" != "$(cd "$REPO_CMD_DIR" 2>/dev/null && pwd)" ]; then
        rm_cmd "$LOCAL_CMD_DIR/$f"
    fi
done
echo

echo "2. AGENT_TEAM_TOOLS env var (shell rc files):"
for rc in $RCS; do strip_rc "$rc"; done
echo

echo "Done. Not touched (by design): the repo, projects/, tickets, inboxes, board data."
echo "Leftover runtime state you may want to clean manually:"
echo "  • running board server:  ps aux | grep board_server.py   (kill <pid>)"
echo "  • global team identity:   rm -f ~/.config/aira/current_team"
echo "  • per-cwd team identity:  rm -f ./.current_team"
echo "  • stale shell env in this terminal:  unset AGENT_TEAM_TOOLS  (or open a new terminal)"
[ "$DRY" -eq 0 ] && echo && echo "To reinstall: re-run setup.md (or just: export AGENT_TEAM_TOOLS=$(pwd))"
exit 0
