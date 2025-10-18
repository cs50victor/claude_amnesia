#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rich>=13.0.0",
# ]
# ///

import json
import sys
import urllib.request
from pathlib import Path
from rich.console import Console

console = Console()
AMNESIA_DIRECTORY = "~/.amnesia"
CLAUDE_SETTINGS_DIR = "~/.claude"
CLAUDE_SETTINGS_FILE = "~/.claude/settings.json"
RAW_FILE_URL = "https://raw.githubusercontent.com/cs50victor/claude_amnesia/main/ctx.py"

def install_ctx_file():
    target_dir = Path(AMNESIA_DIRECTORY).expanduser()
    target_file = target_dir / "ctx.py"

    console.print("starting installation")

    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"created directory: {target_dir}", style="green")

    if target_file.exists():
        console.print(f"file already exists: {target_file}", style="yellow")
        console.print("skipping download", style="dim")
        return target_file

    console.print(f"fetching from: {RAW_FILE_URL}", style="dim")

    req = urllib.request.Request(RAW_FILE_URL)
    with urllib.request.urlopen(req, timeout=10) as response:
        content = response.read()

    target_file.write_bytes(content)
    target_file.chmod(0o755)

    console.print(f"installed to: {target_file}", style="green")

    if target_file.exists():
        file_size = target_file.stat().st_size
        console.print(f"size: {file_size:,} bytes", style="dim")
    else:
        console.print("installation failed", style="bold red")
        sys.exit(1)

    return target_file

def setup_claude_hooks(ctx_file_path: Path):
    settings_file = Path(CLAUDE_SETTINGS_FILE).expanduser()
    settings_dir = Path(CLAUDE_SETTINGS_DIR).expanduser()

    console.print(f"\nthis will add hooks to {settings_file}", style="yellow")
    console.print("hooks will be added to: UserPromptSubmit, PostToolUse", style="dim")

    response = input("\nproceed with hook installation? (y/n): ").strip().lower()

    if response not in ('y', 'yes'):
        console.print("skipping hook installation", style="yellow")
        return False

    if not settings_dir.exists():
        console.print(f"creating directory: {settings_dir}", style="green")
        settings_dir.mkdir(parents=True, exist_ok=True)

    settings = {}
    if settings_file.exists():
        console.print(f"reading existing settings from: {settings_file}", style="dim")
        try:
            with open(settings_file, 'r') as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            console.print(f"error parsing existing settings: {e}", style="bold red")
            console.print("please fix the JSON file before continuing", style="yellow")
            return False
    else:
        console.print(f"creating new settings file: {settings_file}", style="green")
        settings = {"$schema": "https://json.schemastore.org/claude-code-settings.json"}

    if "hooks" not in settings:
        settings["hooks"] = {}

    hook_config = {
        "hooks": [
            {
                "type": "command",
                "command": str(ctx_file_path)
            }
        ]
    }

    hooks_to_add = ["UserPromptSubmit", "PostToolUse"]

    for hook_name in hooks_to_add:
        if hook_name not in settings["hooks"]:
            console.print(f"creating hook: {hook_name}", style="green")
            settings["hooks"][hook_name] = [hook_config]
        else:
            existing_commands = []
            for hook_entry in settings["hooks"][hook_name]:
                for h in hook_entry.get("hooks", []):
                    if h.get("type") == "command":
                        existing_commands.append(h.get("command"))

            if str(ctx_file_path) in existing_commands:
                console.print(f"hook already exists in {hook_name}", style="yellow")
            else:
                console.print(f"appending hook to {hook_name}", style="green")
                settings["hooks"][hook_name].append(hook_config)

    temp_file = settings_file.with_suffix('.tmp')
    console.print(f"writing settings to temporary file", style="dim")

    with open(temp_file, 'w') as f:
        json.dump(settings, f, indent=2)

    temp_file.replace(settings_file)
    console.print(f"successfully updated: {settings_file}", style="bold green")

    return True

def setup_amnesia():
    ctx_file = install_ctx_file()
    console.print("installation complete", style="bold green")

    hook_installed = setup_claude_hooks(ctx_file)

    if hook_installed:
        console.print("\nsetup complete!", style="bold green")
        console.print("restart claude code to activate hooks", style="yellow")
    else:
        console.print("\nctx.py installed but hooks not configured", style="yellow")
        console.print(f"you can manually add {ctx_file} to your hooks later", style="dim")

    return 0

if __name__ == "__main__":
    try:
        sys.exit(setup_amnesia())
    except KeyboardInterrupt:
        console.print("\ncancelled", style="yellow")
        sys.exit(130)
    except Exception as e:
        console.print(f"error: {e}", style="bold red")
        console.print("please file an issue: https://github.com/cs50victor/claude_amnesia/issues", style="dim")
        sys.exit(1)
