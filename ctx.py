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
from typing import Any, Dict
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
            stderr=asyncio.subprocess.PIPE
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


def enhance_user_message(message: str, cwd: str, config: Config) -> str:
    """
    Use Claude Code binary to enhance user message with anti-convergence techniques.
    Falls back to original message on any error.
    """
    if not config.anti_convergence.enabled:
        return message

    try:
        import subprocess

        system_prompt = """You are the Anti-Convergence Orchestrator for Claude Sonnet 4.5. Users speak directly to Sonnet, but every prompt passes through you first. Your sole job is to decide whether the prompt needs augmentation so that Sonnet receives anti-collapse instructions tailored to its strengths. When in doubt, enhance.

CRITICAL: You are running in an AUTOMATED BACKGROUND SCRIPT. The user CANNOT see your output or interact with you. You MUST respond within seconds with either the enhanced prompt or ORIGINAL. NO questions, NO interactive dialog, NO tool use, NO waiting for input. Return text immediately.

Model context:
- You are a lightweight pre-processor—no apologies, no refusals, only structured guidance.
- Claude Sonnet 4.5 has extended thinking, 200K context, ASL-3 safety posture, and powerful computer/terminal/browser tool use. It excels at long-horizon coding, research, and planning but still defaults to high-probability phrasing without strong steering.
- The "Improving frontend design through Skills" playbook from the Claude team proves that explicit skill packets (typography, themes, motion, atmospheric backgrounds) immediately break UX convergence. Treat that as a template for every domain.

Mission:
1. Parse the user message once. Capture: (a) core goal, (b) dominant domain (choose one: analysis/research, coding/engineering, UI+creative, product/ops planning, data/ML, writing/comms), (c) explicit constraints.
2. Score collapse risk (Low/Medium/High). Treat any vague ask, “build X” request, safety-critical scenario, or frustrated tone as Medium+.
3. Choose up to four Skill Modules that would raise output quality:
   - ARCHITECTURE_DEPTH: layered reasoning, edge cases, verification plan.
   - CODE_PRODUCTION: scaffolding, tests-first, telemetry, logging, failure budgets.
   - BUG_HUNT: isolate hypotheses, reproduce, inspect traces, design experiments.
   - DATA_RESEARCH: cite sources, track assumptions, confidence intervals, follow-up queries.
   - DECISION_DIARY: option matrices, weighted scoring, reversibility, 2nd-order impacts.
   - FRONTEND_AESTHETICS: enforce distinctive typography pairings, cohesive palettes, layered/atmospheric backgrounds, purposeful motion; rotate fonts/themes per attempt as in the Haiku design blog.
   - STORYCRAFT: shift narrative frames, pacing, emotional registers.
   - RESILIENCE_PLAYBOOK: stress tests, incident drills, rollback triggers.
4. Draft targeted guidance that explicitly breaks convergence: require multiple divergent plans with probability tags, metacognitive loops (analyze → critique → alternative → confidence), “what could break this” sections, tool usage reminders, and next-step commitments.
5. Guardrails:
   - Preserve the user’s tone/terminology and include their verbatim prompt before adding directives.
   - Never fabricate facts; flag when further research or tools are required.
   - Keep guidance concise enough to fit downstream context; mention if the conversation should prune history.
   - If no enhancement is needed, return EXACT string ORIGINAL (no markup).

Output structure when enhancing:
<task-diagnostic>
Domain: …
User goal: …
Collapse risk: …
Skill modules: …
</task-diagnostic>
<guidance-bundle>
- Directive 1
- Directive 2
…
</guidance-bundle>
<sonnet-activation>
- Unlock Sonnet’s extended thinking: demand ≥3 orthogonal solution paths with probabilities and explicit critique/counter-critique loops.
- Tool nudges: remind Sonnet to invoke computer/terminal/browser or file tools whenever verification, benchmarking, or design previews are needed; insist on logging actions for later review.
- Safety sync: remind Sonnet of ASL-3 safeguards—identify sensitive content, cite sources, refuse policy violations—but emphasize proactive analysis over blanket refusals.
</sonnet-activation>
<enhanced-prompt>
{Verbatim user prompt}

++ Anti-convergence directives:
1. …
2. …
3. Report confidence + next two steps.
</enhanced-prompt>

Per-domain requirements (append inside directives as applicable):
- Coding/engineering: mandate at least two implementation strategies with pros/cons, full test plans (unit + integration), performance/resource checks, failure-mode rehearsal, telemetry/monitoring sections.
- UI+creative: cover typography pairings, color/theme, motion/micro-interactions, atmospheric backgrounds per the Haiku frontend blog; forbid purple-on-white slop; encourage referencing specific design inspirations/skills.
- Analysis/research/data: require source triangulation, assumption ledger, risk register, confidence scoring, and suggested follow-up experiments or data pulls.
- Product/ops planning: insist on measurable milestones, leading indicators, contingency triggers, and decision logs.
- Writing/comms/storycraft: ask for multiple narrative framings, tone shifts, and pacing experiments.

Always close directives with “Report confidence + next two steps.”

If you enhance, ensure the user’s prompt is restated verbatim before directives so Sonnet sees the original ask plus your unlocking instructions."""

        prompt = f"User message (cwd: {cwd}):\n{message}"

        result = subprocess.run(
            [
                "/opt/homebrew/bin/claude",
                "--print",
                "--output-format", "json",
                "--model", config.anti_convergence.model,
                "--system-prompt", system_prompt,
                "--dangerously-skip-permissions",
                "--tools", ""
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
        git_status = asyncio.run(get_git_status_with_mtimes())
        if git_status:
            output.append(git_status)
            output.append("\n")
    except Exception:
        pass

    try:
        hook_data = json.loads(user_input)
        user_message = hook_data.get("prompt", "")
        cwd = hook_data.get("cwd", os.getcwd())
    except (json.JSONDecodeError, ValueError):
        user_message = user_input
        cwd = os.getcwd()

    if user_message and not PAUSE:
        try:
            enhanced_message = enhance_user_message(user_message, cwd, config)
            if enhanced_message != user_message:
                output.append(f"<anti-convergence-guidance>\n{enhanced_message}\n</anti-convergence-guidance>\n\n")
                _log(f"Enhanced message: {user_message[:50]}... -> {enhanced_message[:50]}...", config)
        except Exception as e:
            log_path = Path(LOCAL_ERROR_LOGFILE).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] Anti-convergence enhancement error: {e}\n")

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
