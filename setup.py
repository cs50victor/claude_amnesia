#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rich>=13.0.0",
# ]
# ///

import sys
import urllib.request
from pathlib import Path
from rich.console import Console

console = Console()
AMNESIA_DIRECTORY = "~/.amnesia"
RAW_FILE_URL = "https://raw.githubusercontent.com/cs50victor/claude_amnesia/main/ctx.py"

def setup_amnesia():
    target_dir = Path(AMNESIA_DIRECTORY).expanduser()
    target_file = target_dir / "ctx.py"

    # console.print("[amnesia] Starting installation", style="bold blue")
    console.print("<amnesia>")
    console.print("starting installation")

    if not target_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"created directory: {target_dir}", style="green")

    if target_file.exists():
        console.print(f"file already exists: {target_file}", style="yellow")
        console.print("skipping installation", style="dim")
        return 0

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
        console.print("installation complete", style="bold green")
        return 0
    else:
        console.print("installation failed", style="bold red")
        sys.exit(1)

if __name__ == "__main__":
    try:
        sys.exit(setup_amnesia())
    except KeyboardInterrupt:
        console.print("\nCancelled", style="yellow")
        sys.exit(130)
    except Exception as e:
        console.print(f"Error: {e}. Please file and issue here - https://github.com/cs50victor/claude_amnesia/issues", style="bold red")
        sys.exit(1)
