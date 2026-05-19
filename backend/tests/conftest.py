import os
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _prepend_windows_git_bash_to_path() -> None:
    if os.name != "nt":
        return

    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "usr" / "bin",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Git" / "bin",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Git" / "usr" / "bin",
    ]
    git_bash_dirs = [str(path) for path in candidates if path.is_dir()]
    if not git_bash_dirs:
        return

    current_path = os.environ.get("PATH", "")
    existing = [part for part in current_path.split(os.pathsep) if part]
    existing_without_git = [part for part in existing if part not in git_bash_dirs]
    os.environ["PATH"] = os.pathsep.join([*git_bash_dirs, *existing_without_git])


_prepend_windows_git_bash_to_path()
