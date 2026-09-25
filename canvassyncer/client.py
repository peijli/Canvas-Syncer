"""Synchronous Canvas LMS REST client."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from canvassyncer import __version__

PER_PAGE = 100


class CanvasAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def sanitize_name(name: str) -> str:
    cleaned = "".join(re.split(r'[\\/:*?"<>|]', name.strip()))
    if len(cleaned) > 240:
        cleaned = cleaned[:240]
    return cleaned or "_"


def parse_canvas_time(value: str | None) -> float:
    if not value:
        return 0.0
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def folder_relative_path(full_name: str) -> str:
    name = full_name or "/"
    if name.startswith("course files"):
        name = name[len("course files") :]
    name = name.replace("\\", "/")
    if not name.startswith("/"):
        name = "/" + name
    parts = [sanitize_name(p) for p in name.split("/") if p]
    return "/" + "/".join(parts) if parts else "/"


def parse_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if not section:
            continue
        if 'rel="next"' not in section and "rel=next" not in section:
            continue
        match = re.search(r"<([^>]+)>", section)
        if match:
            return match.group(1)
    return None


class CanvasClient:
    def __init__(
        self,
        canvas_url: str,
        token: str,
        *,
        proxy: str | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = canvas_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": f"canvassyncer/{__version__}",
        }
        client_kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": timeout,
            "follow_redirects": True,
        }
        if proxy:
            client_kwargs["proxy"] = proxy
        if transport is not None:
            client_kwargs["transport"] = transport
        self._client = httpx.Client(**client_kwargs)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CanvasClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _api_url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _raise_for_payload(self, response: httpx.Response) -> None:
        try:
            data = response.json()
        except ValueError:
            data = None
        if isinstance(data, dict) and data.get("errors"):
            messages = []
            for err in data["errors"]:
                if isinstance(err, dict):
                    messages.append(err.get("message", str(err)))
                else:
                    messages.append(str(err))
            raise CanvasAPIError("; ".join(messages), response.status_code)
        if response.status_code == 401:
            raise CanvasAPIError("Unauthorized — check your Canvas access token.", 401)
        if response.status_code == 404:
            raise CanvasAPIError("Not found.", 404)
        if response.status_code >= 400:
            raise CanvasAPIError(
                f"HTTP {response.status_code}: {response.text[:200]}",
                response.status_code,
            )

    def get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(url, params=params)
        self._raise_for_payload(response)
        return response.json()

    def iter_pages(self, path: str, *, params: dict[str, Any] | None = None) -> Iterator[Any]:
        query = {"per_page": PER_PAGE}
        if params:
            query.update(params)
        url: str | None = self._api_url(path)
        first = True
        while url:
            response = self._client.get(url, params=query if first else None)
            first = False
            self._raise_for_payload(response)
            payload = response.json()
            if isinstance(payload, list):
                yield from payload
            elif isinstance(payload, dict):
                # Unexpected single object; stop after yielding nothing useful
                break
            url = parse_next_link(response.headers.get("Link") or response.headers.get("link"))

    def get_course(self, course_id: str | int) -> dict[str, Any]:
        return self.get_json(self._api_url(f"/api/v1/courses/{course_id}"))

    def list_folders(self, course_id: str | int) -> dict[int, str]:
        folders: dict[int, str] = {}
        for folder in self.iter_pages(f"/api/v1/courses/{course_id}/folders"):
            folders[int(folder["id"])] = folder_relative_path(folder.get("full_name", "/"))
        return folders

    def list_files(self, course_id: str | int) -> list[dict[str, Any]]:
        folders = self.list_folders(course_id)
        files: list[dict[str, Any]] = []
        for item in self.iter_pages(f"/api/v1/courses/{course_id}/files"):
            folder_id = item.get("folder_id")
            if folder_id not in folders:
                continue
            if item.get("locked_for_user"):
                continue
            url = item.get("url")
            if not url:
                continue
            display = sanitize_name(item.get("display_name") or item.get("filename") or "file")
            rel_folder = folders[folder_id]
            rel_path = f"{rel_folder}/{display}".replace("//", "/")
            modified = parse_canvas_time(item.get("modified_at") or item.get("updated_at"))
            size = int(item.get("size") or 0)
            files.append(
                {
                    "id": item.get("id"),
                    "path": rel_path,
                    "url": url,
                    "size": size,
                    "modified_at": modified,
                }
            )
        return files

    def download_file(self, url: str, destination: str, *, progress=None) -> None:
        with self._client.stream("GET", url) as response:
            if response.status_code >= 400:
                raise CanvasAPIError(
                    f"Download failed with HTTP {response.status_code}",
                    response.status_code,
                )
            content_type = (response.headers.get("content-type") or "").lower()
            # Peek first chunk to detect HTML login pages
            temp_path = destination + ".temp"
            try:
                with open(temp_path, "wb") as handle:
                    first = True
                    for chunk in response.iter_bytes():
                        if first:
                            first = False
                            if (
                                "text/html" in content_type
                                or chunk.lstrip()[:15].lower().startswith(b"<!doctype html")
                                or chunk.lstrip()[:6].lower().startswith(b"<html")
                            ):
                                raise CanvasAPIError(
                                    "Download returned an HTML page — token may be invalid "
                                    "or the file requires browser login.",
                                    response.status_code,
                                )
                        handle.write(chunk)
                        if progress is not None:
                            progress.update(len(chunk))
                os.rename(temp_path, destination)
            except Exception:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                raise
