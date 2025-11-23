#!/bin/bash
# Background indexing for amnesia memory system
# Called by Claude Code SessionStart hook

LOG_FILE="$HOME/.amnesia/index.log"

# Run indexing in background, redirect output to log
{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting background index..."
  ~/.amnesia/bin/amnesia-cli index
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Index complete"
} >> "$LOG_FILE" 2>&1 &

# Don't wait for completion - let it run async
