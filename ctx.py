#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
#   "pydantic>=2.0.0",
# ]
# ///
"""
Anti-Convergence Hook for Claude Code
Enhances user prompts to overcome distributional convergence (mode collapse)
"""

import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime

import yaml
from pydantic import BaseModel, Field

VERSION = "0.2.0"
PAUSE = os.getenv("PAUSE_AMNESIA_CLAUDE_HOOK", "False").lower() in ("true", "1", "t")
AMNESIA_DIRECTORY = "~/.amnesia"
REPO_URL = "https://api.github.com/repos/cs50victor/claude_amnesia/releases/latest"
RAW_FILE_URL = "https://raw.githubusercontent.com/cs50victor/claude_amnesia/main/ctx.py"
CONFIG_FILE = f"{AMNESIA_DIRECTORY}/config.yaml"
LOCAL_ERROR_LOGFILE = f"{AMNESIA_DIRECTORY}/error.log"
TRACE_LOG_FILE = f"{AMNESIA_DIRECTORY}/trace.log"
CACHE_DIR = f"{AMNESIA_DIRECTORY}/cache"
AMNESIA_PROMPTS_DIRECTORY = "~/.amnesia/prompts"
DISTRIBUTION_PROMPT_FILE = Path(AMNESIA_PROMPTS_DIRECTORY).expanduser() / "distribution_divergence.txt"

AUTO_UPDATE_INTERVAL = 86400


class AntiConvergenceConfig(BaseModel):
    model: str = Field(default="claude-haiku-4-5")
    timeout: int = Field(default=120)
    enabled: bool = Field(default=True)


class DebugConfig(BaseModel):
    enabled: bool = Field(default=True)
    log_file: str = Field(default=TRACE_LOG_FILE)


class Config(BaseModel):
    anti_convergence: AntiConvergenceConfig = Field(default_factory=AntiConvergenceConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            return cls.model_validate(data)
        except Exception:
            return cls()


def _log(message: str, config: Config):
    if config.debug.enabled:
        log_file = Path(config.debug.log_file).expanduser()
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {message}\n")


_distribution_prompt_cache: str | None = None


def get_distribution_prompt() -> str:
    global _distribution_prompt_cache
    if _distribution_prompt_cache is None:
        try:
            _distribution_prompt_cache = DISTRIBUTION_PROMPT_FILE.read_text()
        except Exception as e:
            raise RuntimeError(f"Failed to read distribution divergence prompt from {DISTRIBUTION_PROMPT_FILE}: {e}")
    return _distribution_prompt_cache


async def get_file_info(filepath: str, is_deleted: bool) -> Dict[str, Any]:
    if is_deleted:
        return {"file": filepath, "mtime": 0, "display": "X"}
    try:
        stat_result = await asyncio.to_thread(Path(filepath).stat)
        return {
            "file": filepath,
            "mtime": stat_result.st_mtime,
            "display": datetime.fromtimestamp(stat_result.st_mtime).isoformat()
        }
    except (FileNotFoundError, PermissionError):
        return {"file": filepath, "mtime": 0, "display": "X"}


async def get_git_status_with_mtimes() -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            "git status -s",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            timeout=6
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0 or not stdout:
            return ""

        file_tasks = []
        for line in stdout.decode().strip().split('\n'):
            if len(line) < 3:
                continue
            status = line[:2]
            filepath = line[2:].strip()
            if ' -> ' in filepath:
                filepath = filepath.split(' -> ')[1]
            is_deleted = 'D' in status
            file_tasks.append(get_file_info(filepath, is_deleted))

        if not file_tasks:
            return ""

        results = await asyncio.gather(*file_tasks)
        output = ["<git-status>", "Files with last modified time (X = deleted):"]
        for item in sorted(results, key=lambda x: x["mtime"], reverse=True):
            output.append(f"{item['file']}: {item['display']}")
        output.append("</git-status>")

        return "\n".join(output)
    except Exception as e:
        log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Git status error: {e}\n")
        return ""


def get_timestamp_metadata() -> str:
    local_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    return f"<metadata>\n  <local_timestamp>{local_time}</local_timestamp>\n</metadata>"


def _parse_frontmatter(text: str) -> Dict[str, str]:
    if not text.startswith("---"):
        return {}

    closing_index = text.find("\n---", 3)
    if closing_index == -1:
        return {}

    block = text[3:closing_index]
    data: Dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _discover_command_dirs(cwd: str) -> List[Path]:
    dirs: List[Path] = []
    seen: set[str] = set()

    def add_directory(path: Path):
        resolved = str(path.resolve()) if path.exists() else str(path)
        if path.is_dir() and resolved not in seen:
            dirs.append(path)
            seen.add(resolved)

    global_commands = Path("~/.claude/commands").expanduser()
    add_directory(global_commands)

    local_commands = Path(cwd).expanduser() / ".claude" / "commands"
    add_directory(local_commands)

    claude_root = Path("~/.claude").expanduser()
    if claude_root.is_dir():
        for child in claude_root.iterdir():
            if child.is_dir():
                add_directory(child / "commands")

    extra_paths = os.getenv("CLAUDE_COMMAND_PATHS", "")
    if extra_paths:
        for entry in extra_paths.split(os.pathsep):
            if not entry:
                continue
            add_directory(Path(entry).expanduser())

    return dirs


def load_command_metadata(cwd: str) -> List[Dict[str, str]]:
    commands: List[Dict[str, str]] = []
    seen_names: set[str] = set()

    for directory in _discover_command_dirs(cwd):
        if not directory.is_dir():
            continue
        try:
            files = sorted(directory.glob("*.md"))
        except OSError:
            continue

        for file_path in files:
            name = file_path.stem
            if not name or name in seen_names:
                continue
            try:
                text = file_path.read_text()
            except (OSError, UnicodeDecodeError):
                continue

            metadata = _parse_frontmatter(text)
            description = metadata.get("description", "")
            commands.append(
                {
                    "name": name,
                    "description": description,
                }
            )
            seen_names.add(name)

    return commands


def detect_slash_command(user_message: str, cwd: str) -> str | None:
    trimmed = user_message.strip()
    if not trimmed.startswith("/") or len(trimmed) <= 1:
        return None

    commands = load_command_metadata(cwd)
    for cmd in commands:
        if trimmed == f"/{cmd['name']}":
            return cmd["name"]

    return None


def enhance_user_message(message: str, cwd: str, config: Config) -> str:
    """
    Use Claude Code binary to enhance user message with anti-convergence techniques.
    Falls back to original message on any error.
    """
    if not config.anti_convergence.enabled:
        return message

    system_prompt = get_distribution_prompt()

    try:
        import subprocess

        prompt = f"User message (cwd: {cwd}):\n{message}"

        result = subprocess.run(
            [
                "claude",
                "-p",
                "--model", config.anti_convergence.model,
                "--dangerously-skip-permissions",
                "--tools", "",
                "--system-prompt", system_prompt,
                "--setting-sources", "local",
                "--output-format", "json",
            ],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=config.anti_convergence.timeout
        )

        if result.returncode != 0:
            return message

        response_data = json.loads(result.stdout)
        enhanced = response_data.get("result", "").strip()

        if not enhanced or enhanced == "ORIGINAL" or "ORIGINAL" in enhanced[:20]:
            return message

        return enhanced

    except Exception as e:
        log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Anti-convergence enhancement error: {e}\n")
        return message


def handle_user_prompt_submit(user_input: str, config: Config) -> str:
    output = [get_timestamp_metadata(), "\n"]
    
    try:
        if git_status := asyncio.run(get_git_status_with_mtimes()):
            output.append(git_status)
            output.append("\n")
    except Exception:
        pass

    try:
        hook_data = json.loads(user_input)
        user_message = hook_data.get("prompt", "")
        cwd = hook_data.get("cwd", os.getcwd())
        _log(f"Parsed JSON: user_message='{user_message[:100]}'", config)
    except (json.JSONDecodeError, ValueError):
        user_message = user_input
        cwd = os.getcwd()
        _log(f"Not JSON, using raw input: '{user_message[:100]}'", config)

    slash_command: str | None = None
    if user_message:
        try:
            slash_command = detect_slash_command(user_message, cwd)
            if slash_command:
                _log(f"Detected slash command: /{slash_command}", config)
        except Exception as e:
            _log(f"Slash command detection failed: {e}", config)

    if slash_command:
        result = "".join(output)
        _log("Returning early for slash command", config)
        _log(f"Hook output preview: {result[:200]}...", config)
        return result

    if user_message and not PAUSE:
        try:
            enhanced_message = enhance_user_message(user_message, cwd, config)
            _log(f"Enhancement returned {len(enhanced_message)} chars", config)
            output.append(f"<anti-convergence-guidance>\n{enhanced_message}\n</anti-convergence-guidance>\n\n")
            _log(f"Enhanced message: {user_message[:250]}... -> {enhanced_message[:250]}...", config)
        except Exception as e:
            log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] Anti-convergence enhancement error: {e}\n")
    else:
        _log(f"Skipping enhancement: user_message={bool(user_message)}, PAUSE={PAUSE}", config)

    result = "".join(output)
    _log(f"Hook returning {len(result)} characters", config)
    _log(f"Hook output preview: {result[:200]}...", config)
    return result


def auto_update(current_version: str, current_file_path: Path, logger=None) -> bool:
    try:
        latest_version: str | None = None
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
        if 'temp_file' in locals() and temp_file.exists():
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


def handle_post_tool_use(user_input: str) -> str:
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
        config_path = Path(CONFIG_FILE).expanduser()
        config = Config.from_yaml(config_path)

        hook_type = os.environ.get("CLAUDE_CODE_HOOK_TYPE", "UserPromptSubmit")
        user_input = sys.stdin.read()

        try:
            data = json.loads(user_input)
            hook_event_name = data.get("hook_event_name")

            if hook_event_name == "PostToolUse" or hook_event_name == "SessionStart":
                hook_type = hook_event_name
        except (json.JSONDecodeError, ValueError):
            pass

        if hook_type == "PostToolUse":
            print(handle_post_tool_use(user_input))
        elif hook_type == "SessionStart":
            print(handle_session_start(user_input), end="")
        else:
            print(handle_user_prompt_submit(user_input, config), end="")

        elapsed = time.time() - start_time
        _log(f"Execution time: {elapsed:.3f}s", config)

    except Exception as e:
        log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Hook error: {e}\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
