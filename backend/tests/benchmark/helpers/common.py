import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
TESTS_DIR = BENCHMARK_DIR.parent
PROJECT_ROOT = BENCHMARK_DIR.parents[2]
DATASETS_DIR = TESTS_DIR / "datasets"
THRESHOLDS_V1_PATH = BENCHMARK_DIR / "thresholds_v1.json"
BASELINE_MANIFEST_PATH = BENCHMARK_DIR / "baseline_manifest.md"
BENCHMARK_ARTIFACTS_ROOT = (
    Path(tempfile.gettempdir()) / "memory-palace-benchmark-artifacts"
)
BENCHMARK_ARTIFACT_DIR_ENV = "BENCHMARK_ARTIFACT_DIR"
BENCHMARK_ARTIFACT_RUN_TOKEN_ENV = "BENCHMARK_ARTIFACT_RUN_TOKEN"


def _sanitize_run_token(raw_value: str) -> str:
    lowered = "".join(
        ch.lower() if ch.isalnum() or ch in {"-", "_", "."} else "-"
        for ch in raw_value.strip()
    )
    compact = "-".join(chunk for chunk in lowered.split("-") if chunk)
    return compact or f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def resolve_benchmark_artifact_dir(artifact_dir: Path | str | None = None) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir).expanduser()

    env_dir = str(os.getenv(BENCHMARK_ARTIFACT_DIR_ENV, "")).strip()
    if env_dir:
        path = Path(env_dir).expanduser()
        if path.is_absolute():
            return path
        return BENCHMARK_ARTIFACTS_ROOT / path

    return BENCHMARK_ARTIFACT_DIR


_DEFAULT_BENCHMARK_ARTIFACT_RUN_TOKEN = _sanitize_run_token(
    str(os.getenv(BENCHMARK_ARTIFACT_RUN_TOKEN_ENV, "")).strip()
    or f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
)
BENCHMARK_ARTIFACT_DIR = BENCHMARK_ARTIFACTS_ROOT / _DEFAULT_BENCHMARK_ARTIFACT_RUN_TOKEN


def benchmark_artifact_path(
    filename: str, *, artifact_dir: Path | str | None = None
) -> Path:
    return resolve_benchmark_artifact_dir(artifact_dir) / filename


def render_repo_relative_path(path: Path | str) -> str:
    path_obj = Path(path)
    try:
        return path_obj.resolve(strict=False).relative_to(PROJECT_ROOT).as_posix()
    except Exception:
        return path_obj.as_posix()


def load_thresholds_v1() -> Dict[str, Any]:
    return json.loads(THRESHOLDS_V1_PATH.read_text(encoding="utf-8"))
