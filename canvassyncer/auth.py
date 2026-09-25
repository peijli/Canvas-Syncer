"""Resolve and store Canvas API tokens outside the config file."""

from __future__ import annotations

import getpass
import os
from urllib.parse import urlparse

import keyring

SERVICE_NAME = "canvassyncer"
ENV_TOKEN = "CANVAS_API_TOKEN"


def host_from_url(canvas_url: str) -> str:
    parsed = urlparse(canvas_url)
    host = parsed.netloc or parsed.path
    return host.rstrip("/").lower()


def get_token(canvas_url: str) -> str | None:
    env = os.environ.get(ENV_TOKEN, "").strip()
    if env:
        return env
    return keyring.get_password(SERVICE_NAME, host_from_url(canvas_url))


def store_token(canvas_url: str, token: str) -> None:
    keyring.set_password(SERVICE_NAME, host_from_url(canvas_url), token.strip())


def delete_token(canvas_url: str) -> bool:
    host = host_from_url(canvas_url)
    if keyring.get_password(SERVICE_NAME, host) is None:
        return False
    keyring.delete_password(SERVICE_NAME, host)
    return True


def prompt_and_store(canvas_url: str) -> str:
    token = getpass.getpass("Canvas access token: ").strip()
    if not token:
        raise SystemExit("No token provided.")
    store_token(canvas_url, token)
    print(f"Token stored in the OS keyring for {host_from_url(canvas_url)}.")
    return token


def require_token(canvas_url: str) -> str:
    token = get_token(canvas_url)
    if token:
        return token
    print(
        f"No token found (checked ${ENV_TOKEN} and the OS keyring).\n"
        "Create one in Canvas: Account → Settings → New Access Token,\n"
        "then run: canvassyncer login"
    )
    raise SystemExit(1)
