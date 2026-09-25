"""Compare local files with Canvas and download updates."""

from __future__ import annotations

import os
import time
from pathlib import Path

from tqdm import tqdm

from canvassyncer.client import CanvasAPIError, CanvasClient
from canvassyncer.config import Config


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def prepare_local_tree(course_root: Path, files: list[dict]) -> None:
    course_root.mkdir(parents=True, exist_ok=True)
    for item in files:
        ensure_parent(course_root / item["path"].lstrip("/"))


def local_path_for(course_root: Path, rel_path: str) -> Path:
    return course_root / rel_path.lstrip("/")


class Syncer:
    def __init__(
        self,
        config: Config,
        client: CanvasClient,
        *,
        confirm_all: bool = False,
        connections: int = 8,
    ):
        self.config = config
        self.client = client
        self.confirm_all = confirm_all
        self.connections = max(1, connections)

    def sync(self) -> None:
        for course_id, folder_name in self.config.courses.items():
            print(f"\nCourse {course_id} → {folder_name}")
            try:
                course = self.client.get_course(course_id)
                code = course.get("course_code") or course.get("name") or course_id
                print(f"  Resolved: {code}")
            except CanvasAPIError as exc:
                print(f"  Skipping course {course_id}: {exc}")
                continue
            self._sync_course(course_id)

    def _sync_course(self, course_id: str) -> None:
        course_root = self.config.course_root(course_id)
        files = self.client.list_files(course_id)
        prepare_local_tree(course_root, files)

        new_files: list[tuple[str, Path, int]] = []
        later_files: list[tuple[str, Path, int]] = []
        skipped: list[str] = []
        max_bytes = self.config.max_file_size_mb * 1_000_000

        for item in files:
            dest = local_path_for(course_root, item["path"])
            size = item["size"]
            label = f"{course_id}{item['path']} ({size / 1_000_000:.2f}MB)"

            if dest.exists() and not dest.is_dir():
                local_mtime = dest.stat().st_mtime
                if item["modified_at"] <= local_mtime + 1:
                    continue
                later_files.append((item["url"], dest, size))
                continue

            if size > max_bytes:
                if self.confirm_all:
                    ensure_parent(dest)
                    dest.write_bytes(b"")
                    skipped.append(label)
                    continue
                answer = input(
                    f"  {label} exceeds {self.config.max_file_size_mb}MB. "
                    f"Download? (y/N) "
                ).strip()
                if answer.lower() not in ("y", "yes"):
                    ensure_parent(dest)
                    dest.write_bytes(b"")
                    skipped.append(label)
                    continue

            new_files.append((item["url"], dest, size))

        if skipped:
            print(f"  Skipped {len(skipped)} oversized file(s) (empty placeholders written).")
            for entry in skipped:
                print(f"    {entry}")

        if new_files:
            total = sum(size for _, _, size in new_files)
            print(f"  Downloading {len(new_files)} new file(s) ({total / 1_000_000:.2f}MB)...")
            self._download_many(new_files)
        else:
            print("  No new files.")

        if later_files:
            print("  Newer versions on Canvas:")
            for _, dest, size in later_files:
                print(f"    {dest} ({size / 1_000_000:.2f}MB)")
            if self.confirm_all:
                do_update = True
            else:
                answer = input("  Update all? (Y/n) ").strip()
                do_update = answer.lower() not in ("n", "no")
            if do_update:
                to_fetch: list[tuple[str, Path, int]] = []
                for url, dest, size in later_files:
                    try:
                        mtime = int(dest.stat().st_mtime)
                        archived = dest.with_name(f"{mtime}_{dest.name}")
                        if archived.exists():
                            archived = dest.with_name(f"{int(time.time())}_{dest.name}")
                        os.rename(dest, archived)
                        to_fetch.append((url, dest, size))
                    except OSError as exc:
                        print(f"    Could not archive {dest}: {exc}")
                if to_fetch:
                    self._download_many(to_fetch)

    def _download_many(self, items: list[tuple[str, Path, int]]) -> None:
        total = sum(size for _, _, size in items) or None
        progress = tqdm(total=total, unit="B", unit_scale=True, leave=False)
        failures: list[str] = []
        for url, dest, _size in items:
            ensure_parent(dest)
            try:
                self.client.download_file(str(url), str(dest), progress=progress)
            except (CanvasAPIError, OSError, Exception) as exc:
                failures.append(f"{dest}: {exc}")
                if dest.exists() and dest.stat().st_size == 0:
                    try:
                        dest.unlink()
                    except OSError:
                        pass
        progress.close()
        if failures:
            print(f"  Failed to download {len(failures)} file(s):")
            for entry in failures:
                print(f"    {entry}")
