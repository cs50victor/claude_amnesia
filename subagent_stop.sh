#!/bin/bash

LOG_DIR="$HOME/.amnesia/subagents"
LOG_FILE="$LOG_DIR/logs_$(date '+%d_%m_%Y').txt"
DEBUG_FILE="$LOG_DIR/debug_$(date '+%d_%m_%Y').txt"

mkdir -p "$LOG_DIR"

INPUT=$(cat)

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Raw input: $INPUT" >> "$DEBUG_FILE"

SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "N/A"' 2>> "$DEBUG_FILE")
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // "N/A"' 2>> "$DEBUG_FILE")

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Parsed - Session: $SESSION_ID | Transcript: $TRANSCRIPT_PATH" >> "$DEBUG_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Subagent stopped - Session: $SESSION_ID | Transcript: $TRANSCRIPT_PATH" >> "$LOG_FILE"
