"""Unit tests with a fake HTTP transport (no live Canvas)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from canvassyncer import auth, config
from canvassyncer.client import (
    CanvasClient,
    folder_relative_path,
    parse_canvas_time,
    parse_next_link,
    sanitize_name,
)


class FakeTransport(httpx.BaseTransport):
    def __init__(self, routes: dict[str, tuple[int, dict | list, dict | None]]):
        # key: method + " " + path_or_full_url
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        if key not in self.routes and str(request.url) in self.routes:
            key = str(request.url)
        if key not in self.routes:
            # try full URL without query for next-link lookups
            for candidate in list(self.routes):
                if candidate.endswith(request.url.path) or request.url.path in candidate:
                    # match by path suffix
                    pass
            status, body, headers = self.routes.get(
                key, (404, {"errors": [{"message": f"missing route {key}"}]}, None)
            )
        else:
            status, body, headers = self.routes[key]
        headers = dict(headers or {})
        content = json.dumps(body).encode() if not isinstance(body, (bytes, bytearray)) else body
        if "content-type" not in {h.lower() for h in headers}:
            headers["content-type"] = "application/json"
        return httpx.Response(status, headers=headers, content=content, request=request)


def test_sanitize_name_strips_illegal_and_truncates():
    assert "?" not in sanitize_name('a/b:c*d?"e')
    assert len(sanitize_name("x" * 300)) == 240


def test_folder_relative_path_strips_course_files():
    assert folder_relative_path("course files") == "/"
    assert folder_relative_path("course files/Lectures") == "/Lectures"
    assert folder_relative_path("course files/A/B") == "/A/B"


def test_parse_canvas_time_fractional():
    ts = parse_canvas_time("2024-01-15T12:30:45.123Z")
    assert ts > 0
    assert parse_canvas_time(None) == 0.0


def test_parse_next_link():
    header = (
        '<https://canvas.example/api/v1/courses/1/files?page=2&per_page=100>; rel="next", '
        '<https://canvas.example/api/v1/courses/1/files?page=1&per_page=100>; rel="first"'
    )
    assert parse_next_link(header) == (
        "https://canvas.example/api/v1/courses/1/files?page=2&per_page=100"
    )
    assert parse_next_link(None) is None


def test_link_header_pagination(tmp_path: Path):
    page1 = [
        {
            "id": 1,
            "folder_id": 10,
            "display_name": "a.txt",
            "url": "https://canvas.example/files/1/download",
            "size": 10,
            "modified_at": "2024-01-01T00:00:00Z",
        }
    ]
    page2 = [
        {
            "id": 2,
            "folder_id": 10,
            "display_name": "b.txt",
            "url": "https://canvas.example/files/2/download",
            "size": 20,
            "modified_at": "2024-01-02T00:00:00Z",
        }
    ]
    folders = [
        {"id": 10, "full_name": "course files/Notes"},
    ]
    next_url = "https://canvas.example/api/v1/courses/1/files?page=2&per_page=100"
    routes = {
        "GET /api/v1/courses/1": (200, {"id": 1, "course_code": "TEST"}, None),
        "GET /api/v1/courses/1/folders": (200, folders, None),
        "GET /api/v1/courses/1/files": (
            200,
            page1,
            {"Link": f'<{next_url}>; rel="next"'},
        ),
        f"GET {next_url}": (200, page2, None),
    }

    # FakeTransport matches on path; register next page by path with query ignored —
    # httpx request path is still /api/v1/courses/1/files for page 2, so we need
    # a smarter transport for pagination.
    class PagingTransport(httpx.BaseTransport):
        def __init__(self):
            self.file_calls = 0

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/api/v1/courses/1/folders":
                return httpx.Response(200, json=folders, request=request)
            if path == "/api/v1/courses/1/files":
                self.file_calls += 1
                if self.file_calls == 1:
                    return httpx.Response(
                        200,
                        json=page1,
                        headers={"Link": f'<{next_url}>; rel="next"'},
                        request=request,
                    )
                return httpx.Response(200, json=page2, request=request)
            return httpx.Response(404, json={"errors": [{"message": path}]}, request=request)

    transport = PagingTransport()
    with CanvasClient("https://canvas.example", "tok", transport=transport) as client:
        files = client.list_files(1)
    assert len(files) == 2
    assert files[0]["path"] == "/Notes/a.txt"
    assert files[1]["path"] == "/Notes/b.txt"
    assert transport.file_calls == 2


def test_course_id_path_mapping(tmp_path: Path):
    cfg = config.Config(
        canvas_url="https://canvas.stanford.edu",
        download_dir=tmp_path / "Courses",
        courses={"123": "CS224N", "456": str(tmp_path / "abs_course")},
    )
    assert cfg.course_root("123") == (tmp_path / "Courses" / "CS224N").resolve()
    assert cfg.course_root("456") == tmp_path / "abs_course"


def test_config_does_not_persist_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    stored: dict[tuple[str, str], str] = {}

    monkeypatch.setattr(
        auth.keyring,
        "set_password",
        lambda service, user, password: stored.__setitem__((service, user), password),
    )
    monkeypatch.setattr(
        auth.keyring,
        "get_password",
        lambda service, user: stored.get((service, user)),
    )
    monkeypatch.setattr(
        auth.keyring,
        "delete_password",
        lambda service, user: stored.pop((service, user), None),
    )

    path = tmp_path / "config.json"
    legacy = {
        "canvasURL": "https://canvas.stanford.edu",
        "token": "secret-token",
        "courseIDs": [99],
        "courseCodes": ["OLD101"],
        "downloadDir": str(tmp_path / "dl"),
        "filesizeThresh": 100,
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    with pytest.warns(UserWarning, match="courseCodes"):
        cfg = config.load(path)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in written
    assert written["courses"] == {"99": "99"}
    assert written["canvas_url"] == "https://canvas.stanford.edu"
    assert stored[(auth.SERVICE_NAME, "canvas.stanford.edu")] == "secret-token"
    assert cfg.courses == {"99": "99"}


def test_env_token_preferred(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(auth.ENV_TOKEN, "from-env")
    monkeypatch.setattr(auth.keyring, "get_password", lambda *a, **k: "from-keyring")
    assert auth.get_token("https://canvas.stanford.edu") == "from-env"


def test_download_rejects_html_login(tmp_path: Path):
    class HtmlTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<!DOCTYPE html><html>login</html>",
                request=request,
            )

    dest = tmp_path / "out.bin"
    with CanvasClient("https://canvas.example", "tok", transport=HtmlTransport()) as client:
        with pytest.raises(Exception, match="HTML"):
            client.download_file("https://canvas.example/files/1/download", str(dest))
    assert not dest.exists()
