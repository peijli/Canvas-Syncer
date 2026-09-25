"""Load, migrate, and interactively create sync configuration."""

from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from canvassyncer import auth

DEFAULT_CANVAS_URL = "https://canvas.stanford.edu"
DEFAULT_MAX_FILE_SIZE_MB = 250.0
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "canvassyncer" / "config.json"


@dataclass
class Config:
    canvas_url: str = DEFAULT_CANVAS_URL
    download_dir: Path = field(default_factory=lambda: Path.cwd())
    max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB
    courses: dict[str, str] = field(default_factory=dict)
    path: Path | None = None

    def course_root(self, course_id: str) -> Path:
        mapped = self.courses[course_id]
        candidate = Path(mapped).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.download_dir / mapped).resolve()

    def to_dict(self) -> dict[str, Any]:
        return {
            "canvas_url": self.canvas_url.rstrip("/"),
            "download_dir": str(self.download_dir),
            "max_file_size_mb": self.max_file_size_mb,
            "courses": {str(k): v for k, v in self.courses.items()},
        }


def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def _prompt(prompt: str, default: str = "") -> str:
    tip = f" [{default}]" if default else ""
    value = input(f"{prompt}{tip}: ").strip()
    return value if value else default


def migrate_legacy(raw: dict[str, Any], config_path: Path) -> dict[str, Any]:
    """Normalize older config shapes and move tokens out of the file."""
    data = dict(raw)
    changed = False

    if "canvasURL" in data and "canvas_url" not in data:
        data["canvas_url"] = data.pop("canvasURL")
        changed = True
    if "downloadDir" in data and "download_dir" not in data:
        data["download_dir"] = data.pop("downloadDir")
        changed = True
    if "filesizeThresh" in data and "max_file_size_mb" not in data:
        data["max_file_size_mb"] = data.pop("filesizeThresh")
        changed = True

    token = data.pop("token", None)
    if token:
        auth.store_token(data.get("canvas_url", DEFAULT_CANVAS_URL), token)
        changed = True
        print("Moved Canvas token from config into the OS keyring.")

    if "courseCodes" in data:
        codes = data.pop("courseCodes")
        if codes:
            warnings.warn(
                "courseCodes are no longer supported; sync by numeric course ID only. "
                f"Dropped: {codes}",
                UserWarning,
                stacklevel=2,
            )
        changed = True

    courses = data.get("courses")
    if not isinstance(courses, dict):
        courses = {}
        changed = True

    for course_id in data.pop("courseIDs", []) or []:
        key = str(course_id)
        if key not in courses:
            courses[key] = key
            changed = True

    # Drop leftover keys from older formats
    for obsolete in ("y", "proxies", "no_subfolder", "connection_count"):
        if obsolete in data:
            data.pop(obsolete)
            changed = True

    data["courses"] = {str(k): str(v) for k, v in courses.items()}
    data.setdefault("canvas_url", DEFAULT_CANVAS_URL)
    data.setdefault("download_dir", str(Path.cwd()))
    data.setdefault("max_file_size_mb", DEFAULT_MAX_FILE_SIZE_MB)

    if changed:
        save_raw(data, config_path)
    return data


def save_raw(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def save(config: Config, path: Path | None = None) -> Path:
    target = path or config.path or default_config_path()
    save_raw(config.to_dict(), target)
    config.path = target
    return target


def parse_config(data: dict[str, Any], path: Path | None = None) -> Config:
    courses = {str(k): str(v) for k, v in (data.get("courses") or {}).items()}
    if not courses:
        raise ValueError("Config must define at least one course under 'courses'.")
    download_dir = Path(data.get("download_dir", Path.cwd())).expanduser()
    return Config(
        canvas_url=str(data.get("canvas_url", DEFAULT_CANVAS_URL)).rstrip("/"),
        download_dir=download_dir,
        max_file_size_mb=float(data.get("max_file_size_mb", DEFAULT_MAX_FILE_SIZE_MB)),
        courses=courses,
        path=path,
    )


def load(path: Path | None = None) -> Config:
    config_path = path or default_config_path()
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw = migrate_legacy(raw, config_path)
    return parse_config(raw, config_path)


def prompt_config(existing: Config | None = None, path: Path | None = None) -> Config:
    print("Generating config file...")
    base = existing or Config()
    canvas_url = _prompt("Canvas URL", base.canvas_url or DEFAULT_CANVAS_URL)
    download_dir = _prompt(
        "Path to save Canvas files",
        str(base.download_dir) if base.download_dir else str(Path.cwd()),
    )
    size_default = str(base.max_file_size_mb or DEFAULT_MAX_FILE_SIZE_MB)
    size_raw = _prompt("Maximum file size to download (MB)", size_default)
    try:
        max_file_size_mb = float(size_raw)
    except ValueError:
        max_file_size_mb = DEFAULT_MAX_FILE_SIZE_MB

    courses: dict[str, str] = {}
    print(
        "Enter courses as: <course_id> <folder_name>\n"
        "Leave blank when finished. Folder names are relative to the download path "
        "unless absolute."
    )
    if base.courses:
        print("Existing courses (press Enter on a blank line to keep them):")
        for cid, name in base.courses.items():
            print(f"  {cid} -> {name}")
        keep = _prompt("Keep existing courses? (Y/n)", "Y")
        if keep.lower() not in ("n", "no"):
            courses.update(base.courses)

    while True:
        line = input("course_id folder_name: ").strip()
        if not line:
            break
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            print("Expected: <course_id> <folder_name>")
            continue
        course_id, folder = parts
        if not course_id.isdigit():
            print("course_id must be numeric.")
            continue
        courses[course_id] = folder

    if not courses:
        raise SystemExit("At least one course is required.")

    config = Config(
        canvas_url=canvas_url.rstrip("/"),
        download_dir=Path(download_dir).expanduser(),
        max_file_size_mb=max_file_size_mb,
        courses=courses,
        path=path or default_config_path(),
    )
    save(config)
    print(f"Wrote config to {config.path}")
    return config
