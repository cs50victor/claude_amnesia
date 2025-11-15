# memory framework for claude code 

> Give me six hours to chop down a tree, and I will spend the first four sharpening the axe

## Installation

### Install uv

**macOS and Linux**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Alternative Methods**

- **macOS (Homebrew)**: `brew install uv`
- **Windows (winget)**: `winget install --id=astral-sh.uv -e`
- **Windows (scoop)**: `scoop install main/uv`
- **PyPI (via pipx)**: `pipx install uv`
- **Cargo**: `cargo install --git https://github.com/astral-sh/uv uv`

### Run setup.py

```bash
uv run -q --refresh https://raw.githubusercontent.com/cs50victor/claude_amnesia/main/setup.py
```
