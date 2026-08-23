import sys
import os
import subprocess
import tempfile


def extract_code(notebook: dict) -> str:
    """Pull all code-cell source out of a parsed .ipynb JSON dict, in order."""
    cells = notebook.get('cells', [])
    code_parts = []
    for cell in cells:
        if cell.get('cell_type') == 'code':
            source = cell.get('source', '')
            if isinstance(source, list):
                source = ''.join(source)
            code_parts.append(source)
    return '\n'.join(code_parts)


def strip_magics(code: str) -> str:
    """Remove Jupyter magic (%) and shell escape (!) lines that break ast/pipreqs parsing."""
    lines = code.splitlines()
    cleaned = [
        line for line in lines
        if not line.lstrip().startswith(('!', '%'))
    ]
    return '\n'.join(cleaned)


def run_pipreqs(code: str) -> list[str]:
    """Write code to a temp .py file, run pipreqs against it, return requirement lines.

    Everything happens inside a TemporaryDirectory — created fresh and
    fully deleted when this function returns. No files persist in the repo.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "notebook.py")
        with open(script_path, "w") as f:
            f.write(strip_magics(code))

        result = subprocess.run(
            [sys.executable, "-m", "pipreqs.pipreqs", tmpdir, "--force", "--mode", "no-pin"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"pipreqs failed: {result.stderr.strip()}")

        req_path = os.path.join(tmpdir, "requirements.txt")
        if not os.path.exists(req_path):
            return []
        with open(req_path) as f:
            return [line.strip() for line in f if line.strip()]