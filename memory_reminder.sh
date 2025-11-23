#!/bin/bash

cat << 'EOF'
<memory_system_reminder>
AMNESIA MEMORY SYSTEM AVAILABLE:

You have access to semantic + text search across ALL past conversations via:
  amnesia-cli search [--include-grep] "query terms"

Use this to:
- Recall past corrections and anti-patterns
- Find successful interaction patterns
- Remember project-specific preferences
- Avoid repeating mistakes

Search triggers:
- Before proposing solutions in familiar projects
- When user mentions "like before" or "remember"
- After user corrections (mark with <ANTI_PATTERN> tags)
- When uncertain about user preferences

Tag your learnings in responses for future recall:
- <SELF_REMINDER>Never do X, always do Y</SELF_REMINDER>
- <SUCCESSFUL_INTERACTION>What worked well</SUCCESSFUL_INTERACTION>
- <ANTI_PATTERN>What failed, why it failed</ANTI_PATTERN>
- <PROJECT_CONVENTION project="name">Specific rules</PROJECT_CONVENTION>
- <USER_PREFERENCE>Communication style, tool choices</USER_PREFERENCE>

Your ability to LEARN and IMPROVE depends on using this system proactively.
</memory_system_reminder>
EOF
