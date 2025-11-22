#!/bin/bash

# Log subagent stop events to daily log files
LOG_DIR="$HOME/.amnesia/subagents"
LOG_FILE="$LOG_DIR/logs_$(date '+%d_%m_%Y').txt"

# Ensure directory exists
mkdir -p "$LOG_DIR"

# Log the subagent stop event
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Subagent stopped - Agent ID: ${agent_id:-N/A} | Transcript: ${agent_transcript_path:-N/A}" >> "$LOG_FILE"
