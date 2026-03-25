#!/usr/bin/env bash
#
# Ask Claude a question and get a response via iMessage.
# Designed to be called by an Apple Shortcut.
#
# Usage:
#   ./ask_claude.sh "What's on my calendar today?"
#   ./ask_claude.sh --send "What's on my calendar today?"   # also sends reply via iMessage
#
set -euo pipefail

export PATH="/Users/andychiu/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Parse args
SEND_IMESSAGE=false
QUESTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --send) SEND_IMESSAGE=true; shift ;;
        *) QUESTION="$*"; break ;;
    esac
done

# If no question from args, read from stdin (Apple Shortcuts passes input this way)
if [[ -z "$QUESTION" ]]; then
    QUESTION="$(cat)"
fi

if [[ -z "$QUESTION" ]]; then
    echo "Usage: ask_claude.sh [--send] 'your question'" >&2
    exit 1
fi

# Load API key
export ANTHROPIC_API_KEY
ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w 2>/dev/null)" || {
    echo "ERROR: No Anthropic API key in Keychain." >&2
    exit 1
}

# Refresh OAuth tokens
uv run "$SCRIPT_DIR/shared/refresh_tokens.py" >/dev/null 2>&1 || true

# Load tokens
export GCAL_TOKEN GMAIL_TOKEN
GCAL_TOKEN="$(security find-generic-password -a "$USER" -s "morning-brief-gcal-token" -w 2>/dev/null)" || GCAL_TOKEN=""
GMAIL_TOKEN="$(security find-generic-password -a "$USER" -s "morning-brief-gmail-token" -w 2>/dev/null)" || GMAIL_TOKEN=""

# Ask Claude
ANSWER="$(uv run --with anthropic "$SCRIPT_DIR/ask_claude.py" "$QUESTION")"

echo "$ANSWER"

# Send via iMessage if requested
if [[ "$SEND_IMESSAGE" == "true" ]]; then
    IMESSAGE_TARGET="$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
        echo "WARNING: No iMessage target set. Skipping send." >&2
        exit 0
    }

    # Truncate if needed
    TRUNCATED="${ANSWER:0:1200}"

    # Escape for AppleScript
    ESCAPED="${TRUNCATED//\\/\\\\}"
    ESCAPED="${ESCAPED//\"/\\\"}"

    osascript -e "
    tell application \"Messages\"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService
        send \"$ESCAPED\" to targetBuddy
    end tell
    " 2>/dev/null || echo "WARNING: Failed to send iMessage" >&2
fi
