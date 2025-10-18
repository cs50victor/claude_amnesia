#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "openai>=1.0.0",
#   "pyyaml>=6.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
Context Injector Hook for Claude Code
Intelligently selects and injects plugin context using Cerebras inference
"""

import json
import os
import sys
import hashlib
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import yaml
from openai import OpenAI
from pydantic import BaseModel, Field

VERSION = "0.1.0"
# .........
AMNESIA_DIRECTORY = "~/.amnesia"
REPO_URL = "https://api.github.com/repos/cs50victor/claude_amnesia/releases/latest"
RAW_FILE_URL = "https://raw.githubusercontent.com/cs50victor/claude_amnesia/main/ctx.py"
# .........
CONFIG_FILE = f"{AMNESIA_DIRECTORY}/config.yaml"
LOCAL_ERROR_LOGFILE = f"{AMNESIA_DIRECTORY}/error.log"
TRACE_LOG_FILE = f"{AMNESIA_DIRECTORY}/trace.log"
CACHE_DIR = f"{AMNESIA_DIRECTORY}/cache"
# .........
CLAUDE_HISTORY_FILE = "~/.claude/history.jsonl"
AUTO_UPDATE_INTERVAL  = 86400

class HistoryConfig(BaseModel):
    window_size: int = Field(default=5)
    max_tokens_per_message: int = Field(default=500)
    pattern_analysis_window: int = Field(default=100)
    pattern_refresh_interval: int = Field(default=3600)

class PluginsConfig(BaseModel):
    max_selected: int = Field(default=3)
    excerpt_tokens: int = Field(default=300)
    full_content_tokens: int = Field(default=4000)
    directories: List[str] = Field(default_factory=lambda: [
        "~/.claude/plugins/marketplaces/claude-code-workflows/agents",
        "~/.claude/plugins/marketplaces/claude-code-workflows/workflows",
        "~/.claude/plugins/marketplaces/claude-code-workflows/tools",
        "~/.claude/plugins/marketplaces/claude-code-plugins/plugins",
    ])

class CerebrasConfig(BaseModel):
    model: str = Field(default="qwen-3-32b")
    base_url: str = Field(default="https://api.cerebras.ai/v1")
    temperature: float = Field(default=0.6)
    max_tokens: int = Field(default=2000)
    timeout: int = Field(default=30)

class CacheConfig(BaseModel):
    enabled: bool = Field(default=False)
    directory: str = Field(default=f"{CACHE_DIR}")

class CatalogConfig(BaseModel):
    rebuild_interval_seconds: int = Field(default=86400)
    file_path: str = Field(default=f"{CACHE_DIR}/plugin_catalog.json")

class PatternsConfig(BaseModel):
    enabled: bool = Field(default=True)
    cache_file: str = Field(default=f"{CACHE_DIR}/detected_patterns.json")
    min_occurrences: int = Field(default=2)
    max_patterns: int = Field(default=10)

class DebugConfig(BaseModel):
    enabled: bool = Field(default=True)
    log_file: str = Field(default=TRACE_LOG_FILE)

class Config(BaseModel):
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    cerebras: CerebrasConfig = Field(default_factory=CerebrasConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    catalog: CatalogConfig = Field(default_factory=CatalogConfig)
    patterns: PatternsConfig = Field(default_factory=PatternsConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            return cls.model_validate(data)
        except Exception:
            return cls()

class ContextInjector:
    def __init__(self, config_path: str = CONFIG_FILE):
        if not (api_key := os.environ.get("CEREBRAS_API_KEY")):
            raise ValueError("CEREBRAS_API_KEY not set")

        self.client = OpenAI(
            base_url=self.config.cerebras.base_url,
            api_key=api_key,
            timeout=self.config.cerebras.timeout,
        )
        self.config_path = Path(config_path).expanduser()
        self.config = Config.from_yaml(self.config_path)
        self.cache_dir = Path(self.config.cache.directory).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = Path(self.config.catalog.file_path).expanduser()

    def _log(self, message: str):
        if self.config.debug.enabled:
            log_file = Path(self.config.debug.log_file).expanduser()
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] {message}\n")

    def _extract_plugin_excerpt(self, file_path: Path, max_tokens: int = 300) -> Optional[Dict[str, str]]:
        try:
            content = file_path.read_text()
            lines = content.split("\n")

            frontmatter = {}
            # plugin md file yml
            if lines[0].strip() == "---":
                end_idx = 1
                while end_idx < len(lines) and lines[end_idx].strip() != "---":
                    end_idx += 1
                frontmatter_lines = lines[1:end_idx]
                for line in frontmatter_lines:
                    if ":" in line:
                        key, val = line.split(":", 1)
                        frontmatter[key.strip()] = val.strip()
                lines = lines[end_idx + 1 :]

            excerpt_lines = []
            char_count = 0
            max_chars = max_tokens * 4  # Rough estimate

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    excerpt_lines.append(line)
                elif line.startswith("-") or line.startswith("*"):
                    excerpt_lines.append(line)
                else:
                    excerpt_lines.append(line)

                char_count += len(line)
                if char_count > max_chars:
                    break

            excerpt = "\n".join(excerpt_lines[:50])

            type = "unknown"
            parts = file_path.parts
            if "commands" in parts:
                type = "command"
            if "agents" in parts:
                type = "agent"
            if "workflows" in parts:
                type = "workflow"
            if "tools" in parts:
                type = "tool"
            return {
                "name": frontmatter.get("name", file_path.stem),
                "description": frontmatter.get("description", ""),
                "excerpt": excerpt[:max_chars],
                "path": str(file_path),
                "type": type,
            }
        except Exception as e:
            self._log(f"Error extracting from {file_path}: {e}")
            return None

    def _build_plugin_catalog(self) -> List[Dict[str, Any]]:
        self._log("Building plugin catalog...")
        catalog = []

        for dir_path in self.config.plugins.directories:
            dir_path = Path(dir_path).expanduser()
            if not dir_path.exists():
                continue

            for md_file in dir_path.rglob("*.md"):
                if md_file.name in ["README.md", "CHANGELOG.md", "LICENSE.md"]:
                    continue

                excerpt_data = self._extract_plugin_excerpt(
                    md_file, self.config.plugins.excerpt_tokens
                )
                if excerpt_data:
                    catalog.append(excerpt_data)

        self._log(f"Built catalog with {len(catalog)} plugins")
        return catalog

    def _get_or_build_catalog(self) -> List[Dict[str, Any]]:
        if self.catalog_path.exists():
            catalog_age = time.time() - self.catalog_path.stat().st_mtime
            if catalog_age < self.config.catalog.rebuild_interval_seconds:
                with open(self.catalog_path) as f:
                    return json.load(f)

        catalog = self._build_plugin_catalog()
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.catalog_path, "w") as f:
            json.dump(catalog, f, indent=2)

        return catalog

    def _extract_full_history(self, history_path: Path, max_messages: int) -> List[Dict[str, str]]:
        if not history_path.exists():
            return []

        messages = []
        with open(history_path) as f:
            for line in f.readlines()[-max_messages:]:
                try:
                    entry = json.loads(line)
                    msg_text = entry.get("display", "")
                    max_tokens = 1000
                    if len(msg_text) > max_tokens * 4:
                        msg_text = msg_text[: max_tokens * 4] + "..."
                    messages.append(
                        {"timestamp": entry.get("timestamp"), "content": msg_text}
                    )
                except (json.JSONDecodeError, KeyError):
                    continue

        return messages

    def _extract_chat_history(self, history_path: Path, window_size: int) -> List[Dict[str, str]]:
        if not history_path.exists():
            return []

        messages = []
        with open(history_path) as f:
            for line in f.readlines()[-window_size:]:
                try:
                    entry = json.loads(line)
                    msg_text = entry.get("display", "")
                    max_tokens = self.config.history.max_tokens_per_message
                    if len(msg_text) > max_tokens * 4:
                        msg_text = msg_text[: max_tokens * 4] + "..."
                    messages.append(
                        {"timestamp": entry.get("timestamp"), "content": msg_text}
                    )
                except (json.JSONDecodeError, KeyError):
                    continue

        return messages

    def _get_cache_key(self, user_message: str, history: List[Dict]) -> str:
        """Generate cache key from message and history."""
        history_summary = "\n".join([h["content"][:100] for h in history[-3:]])
        content = f"{user_message}\n{history_summary}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_cached_decision(self, cache_key: str) -> Optional[List[str]]:
        if not self.config.cache.enabled:
            return None

        cache_file = self.cache_dir / "decisions" / f"{cache_key}.json"
        if not cache_file.exists():
            return None

        cache_age = time.time() - cache_file.stat().st_mtime
        if cache_age > self.config.cache.ttl_seconds:
            cache_file.unlink()
            return None

        with open(cache_file) as f:
            return json.load(f).get("plugins", [])

    def _save_cached_decision(self, cache_key: str, plugins: List[str]):
        if not self.config.cache.enabled:
            return

        cache_dir = self.cache_dir / "decisions"
        cache_dir.mkdir(parents=True, exist_ok=True)

        with open(cache_dir / f"{cache_key}.json", "w") as f:
            json.dump({"plugins": plugins, "timestamp": time.time()}, f)

    def _select_plugins_with_cerebras(
        self, user_message: str, history: List[Dict], full_history: List[Dict], catalog: List[Dict[str, Any]]
    ) -> Optional[str]:
        if not self.client:
            self._log("Cerebras client not initialized, skipping plugin selection")
            return None

        # Format catalog for Cerebras
        catalog_text = []
        for plugin in catalog:
            catalog_text.append(
                f"- **{plugin['name']}** ({plugin['type']}): {plugin['description']}\n"
                f"  Excerpt: {plugin['excerpt'][:200]}..."
            )

        catalog_str = "\n".join(catalog_text[:100])
        history_str = "\n".join([f"[{h['timestamp']}] {h['content'][:200]}" for h in history[-3:]])
        pattern_history_str = "\n".join([f"{h['content'][:300]}" for h in full_history[-30:]])

        prompt = f"""You are a context assistant for Claude Code. Your job is to analyze the user's message, conversation history, and detect recurring patterns/preferences to generate helpful context.

RECENT CONVERSATION HISTORY (last 3 messages):
{history_str}

BROADER CONVERSATION HISTORY (for pattern detection):
{pattern_history_str}

CURRENT USER MESSAGE:
{user_message}

AVAILABLE PLUGIN KNOWLEDGE (for your reference):
{catalog_str}

First, analyze the BROADER CONVERSATION HISTORY to detect:
1. Recurring preferences (languages, frameworks, tools, coding styles)
2. Common corrections or emphasis (things user repeatedly mentions)
3. Workflow patterns (repeated commands, typical workflows)
4. Communication preferences (how they want responses)
5. Domain context (projects, technologies they work with)

Then, based on the current message, reason about what context would help Claude:
- What programming language/framework is involved?
- What type of task is this?
- What best practices or patterns would be relevant?
- How do the detected patterns apply to this specific task?

After reasoning, wrap your generated context in <ctx>...</ctx> tags. Inside the tags, provide plain text guidance including:
- Detected user patterns/preferences that apply to this task
- Key approaches or methodologies to use
- Important considerations or best practices
- Relevant prompting techniques from the available plugins
- Any specific instructions that would help Claude complete this task

IMPORTANT: Incorporate detected patterns naturally into the guidance. If you notice the user frequently emphasizes something, include it. Write helpful, actionable guidance in plain text.

Example format:
<ctx>
For this task, consider the following approaches:

[Write specific guidance here based on the plugins and detected patterns]

Key principles to follow:
- [Include detected user preferences]
- [Specific actionable guidance]
- [Best practices relevant to this task]

[Any other helpful context from patterns or plugin knowledge]
</ctx>"""

        try:
            self._log("Querying Cerebras for plugin context...")
            response = self.client.chat.completions.create(
                model=self.config.cerebras.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful context assistant for Claude Code. Generate plain text guidance and context wrapped in <ctx></ctx> tags to help Claude complete the user's task effectively.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self.config.cerebras.temperature,
                max_tokens=self.config.cerebras.max_tokens,
                stream=False,
            )

            message_content = response.choices[0].message.content
            if message_content is None:
                self._log("Warning: Cerebras returned None content")
                return None

            import re

            content = message_content.strip()
            self._log(f"Cerebras response (full):\n{content}")
            self._log(f"Content length: {len(content)}, has <ctx>: {'<ctx>' in content}")

            ctx_match = re.search(r"<ctx>(.*?)</ctx>", content, re.DOTALL | re.IGNORECASE)
            if ctx_match:
                self._log("Extracted context from <ctx> tags")
                return ctx_match.group(1).strip()

            self._log("No <ctx> tags found in response")
            return None

        except Exception as e:
            self._log(f"Error querying Cerebras: {e}")
            return None

    def run(self, user_message: str) -> str:
        self._log(f"Processing message: {user_message[:100]}...")

        history_path = Path(CLAUDE_HISTORY_FILE).expanduser()
        history = self._extract_chat_history(history_path, self.config.history.window_size)
        full_history = self._extract_full_history(history_path, self.config.history.pattern_analysis_window)

        self._log(f"Analyzing {len(full_history)} messages for patterns")

        catalog = self._get_or_build_catalog()
        context = self._select_plugins_with_cerebras(user_message, history, full_history, catalog)

        if not context:
            self._log("No context generated")
            return ""

        self._log("Injecting context from Cerebras")
        return f"<relevant-context>\n\n{context}\n\n</relevant-context>\n\n"


def get_timestamp_metadata() -> str:
    utc_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"<metadata>\n  <utc_timestamp>{utc_time}</utc_timestamp>\n  <local_timestamp>{local_time}</local_timestamp>\n</metadata>"


def handle_user_prompt_submit(user_input: str) -> str:
    output = [get_timestamp_metadata(), "\n"]

    try:
        hook_data = json.loads(user_input)
        user_message = hook_data.get("prompt", "")
    except (json.JSONDecodeError, ValueError):
        user_message = user_input

    if user_message:
        try:
            context = ContextInjector().run(user_message)
            if context:
                output.append(context)
        except Exception as e:
            log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] Context injection error: {e}\n")

    return "".join(output)


def auto_update(current_version: str,current_file_path: Path, logger=None) -> bool:
    try:
        latest_version : str | None = None
        req = urllib.request.Request(
            REPO_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())
            latest_version = data.get("tag_name", "").lstrip("v")

            if latest_version and latest_version != current_version:
                if logger:
                    logger(f"Update available: {current_version} -> {latest_version}")

        if not latest_version:
            return False

        if logger:
            logger(f"Downloading version {latest_version}")

        req = urllib.request.Request(RAW_FILE_URL)
        with urllib.request.urlopen(req, timeout=10) as response:
            new_content = response.read()

        temp_file = current_file_path.with_suffix(".tmp")
        temp_file.write_bytes(new_content)

        temp_file.chmod(current_file_path.stat().st_mode)

        os.replace(str(temp_file), str(current_file_path))

        if logger:
            logger(f"Updated to version {latest_version}")

        return True

    except Exception as e:
        if logger:
            logger(f"Update failed: {e}")
        if temp_file and temp_file.exists():
            temp_file.unlink()
        return False

def handle_session_start(user_input: str) -> str:
    output = []
    
    cache_dir = Path(CACHE_DIR).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    last_check_file = cache_dir / "last_version_check.txt"

    should_check = True
    if last_check_file.exists():
        last_check_time = last_check_file.stat().st_mtime
        time_since_check = time.time() - last_check_time
        if time_since_check < AUTO_UPDATE_INTERVAL:
            should_check = False

    if should_check:
        current_file = Path(__file__).resolve()

        def logger(msg: str):
            log_path = cache_dir / "context_injector.log"
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] [amnesia] {msg}\n")

        updated = auto_update(VERSION, current_file, logger)

        last_check_file.write_text(str(time.time()))

        if updated:
            output.append("[amnesia] Updated to latest version\n")

    return "".join(output)


def handle_post_tool_use() -> str:
    metadata = get_timestamp_metadata()

    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": metadata,
            }
        }
    )


def main():
    start_time = time.time()
    try:
        hook_type = os.environ.get("CLAUDE_CODE_HOOK_TYPE", "UserPromptSubmit")

        try:
            user_input = sys.stdin.read()
            data = json.loads(user_input)
            hook_event_name = data.get("hook_event_name")
            
            if hook_event_name == "PostToolUse" or hook_event_name == "SessionStart":
                hook_type = hook_event_name
        except (json.JSONDecodeError, ValueError):
            pass

        if hook_type == "PostToolUse":
            print(handle_post_tool_use())
        elif hook_type == "SessionStart":
            print(handle_session_start(user_input), end="")
        else:
            print(handle_user_prompt_submit(user_input), end="")

        elapsed = time.time() - start_time
        log_path = Path(TRACE_LOG_FILE).expanduser()
        if log_path.exists():
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] Execution time: {elapsed:.3f}s\n")

        sys.exit(0)

    except Exception as e:
        log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Hook error: {e}\n")
        sys.exit(0)

if __name__ == "__main__":
    main()
