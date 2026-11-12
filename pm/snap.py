import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _git(cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env,
                          timeout=60)  # a huge untracked folder: no snapshot beats a hung pm run


def snapshot(cwd: Path) -> str | None:
    try:
        # shortcut: untracked files that aren't in .gitignore (e.g. a.out) are written as git objects on every run until git gc prunes them, skip untracked files over 1 MB if .git grows
        top = _git(cwd, "rev-parse", "--show-toplevel")
        if top.returncode:
            return None
        top_path = Path(top.stdout.strip())
        index = _git(top_path, "rev-parse", "--git-path", "index")
        if index.returncode:
            return None
        index_path = Path(index.stdout.strip())
        if not index_path.is_absolute():
            index_path = top_path / index_path
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "index"
            if index_path.exists():
                shutil.copyfile(index_path, copy)
            env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
            if _git(top_path, "add", "-A", env=env).returncode:
                return None
            tree = _git(top_path, "write-tree", env=env)
            if tree.returncode:
                return None
            return tree.stdout.strip()
    except Exception:
        return None


def diff(cwd: Path, a: str, b: str) -> str:
    try:
        out = _git(cwd, "diff", "--no-color", "--no-ext-diff", a, b)
        return out.stdout if out.returncode == 0 else ""
    except Exception:
        return ""
