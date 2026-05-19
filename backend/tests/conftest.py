import os
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _windows_git_bash_dirs() -> list[Path]:
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "usr" / "bin",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Git" / "bin",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Git" / "usr" / "bin",
    ]
    return [path for path in candidates if path.is_dir()]


def _prepend_windows_git_bash_to_path() -> None:
    if os.name != "nt":
        return

    git_bash_dirs = [str(path) for path in _windows_git_bash_dirs()]
    if not git_bash_dirs:
        return

    current_path = os.environ.get("PATH", "")
    existing = [part for part in current_path.split(os.pathsep) if part]
    existing_without_git = [part for part in existing if part not in git_bash_dirs]
    os.environ["PATH"] = os.pathsep.join([*git_bash_dirs, *existing_without_git])


def _windows_git_bash_executable() -> str | None:
    if os.name != "nt":
        return None

    for directory in _windows_git_bash_dirs():
        candidate = directory / "bash.exe"
        if candidate.is_file():
            return str(candidate)
    return None


_ORIGINAL_SUBPROCESS_RUN = subprocess.run
_WINDOWS_GIT_BASH = _windows_git_bash_executable()


def _resolve_bash_args(args):
    if (
        _WINDOWS_GIT_BASH
        and isinstance(args, (list, tuple))
        and args
        and str(args[0]).lower() == "bash"
    ):
        return [_WINDOWS_GIT_BASH, *list(args[1:])]
    return args


def _run_with_git_bash(*popenargs, **kwargs):
    if popenargs:
        popenargs = (_resolve_bash_args(popenargs[0]), *popenargs[1:])
    elif "args" in kwargs:
        kwargs = {**kwargs, "args": _resolve_bash_args(kwargs["args"])}
    return _ORIGINAL_SUBPROCESS_RUN(*popenargs, **kwargs)


_prepend_windows_git_bash_to_path()
if _WINDOWS_GIT_BASH:
    subprocess.run = _run_with_git_bash
