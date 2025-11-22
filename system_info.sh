#!/bin/bash
set -euo pipefail

# SessionStart hook to provide system information context

# Read stdin payload (optional - can be used for conditional logic)
INPUT=$(cat)

# Gather full system information
SW_VERS_OUTPUT=$(sw_vers 2>/dev/null || echo "sw_vers command failed")
HARDWARE_OUTPUT=$(system_profiler SPHardwareDataType 2>/dev/null || echo "system_profiler command failed")

# Build context message with full dumps
CONTEXT="<user_system_info>
=== sw_vers ===
${SW_VERS_OUTPUT}

=== system_profiler SPHardwareDataType ===
${HARDWARE_OUTPUT}
</user_system_info>"

# Output JSON with additionalContext
jq -n \
  --arg context "$CONTEXT" \
  '{
    "hookSpecificOutput": {
      "hookEventName": "SessionStart",
      "additionalContext": $context
    }
  }'

exit 0
