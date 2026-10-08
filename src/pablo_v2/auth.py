"""Auth: Codex account sign-in / status / sign-out. No model calls here.

Follows https://learn.chatgpt.com/docs/auth : `codex login` runs the ChatGPT browser OAuth flow,
`--device-auth` is the headless variant, `codex login status` / `codex logout` manage the session.
Tokens stay where Codex keeps them (`cli_auth_credentials_store`: file | keyring | auto | ephemeral);
Pablo never reads them.
# ponytail: requires the codex CLI on PATH; desktop app can move to `codex app-server` later.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib


class AuthError(RuntimeError):
    pass


def codex_bin() -> str:
    path = shutil.which("codex")
    if not path:
        raise AuthError("codex CLI not found. Install: npm i -g @openai/codex")
    return path


def status() -> tuple[bool, str]:
    try:
        r = subprocess.run([codex_bin(), "login", "status"], capture_output=True, text=True, encoding="utf-8")
    except AuthError as e:
        return False, str(e)
    msg = (r.stdout + r.stderr).strip()
    return r.returncode == 0 and "Logged in" in msg, msg


def require() -> None:
    ok, msg = status()
    if not ok:
        raise AuthError(f"Not signed in to Codex ({msg}). Run: python -m pablo_v2 login")


def login(device: bool = False) -> int:
    """Interactive: opens the browser (or prints a device code) for ChatGPT sign-in."""
    code = subprocess.call([codex_bin(), "login"] + (["--device-auth"] if device else []))
    if code and device:
        print("Device code sign-in failed. It must first be enabled in ChatGPT security settings "
              "(personal) or workspace permissions (admin). Alternatives: sign in on a machine with a "
              "browser and copy ~/.codex/auth.json, or SSH-forward localhost:1455. "
              "See https://learn.chatgpt.com/docs/auth", file=sys.stderr)
    return code


def logout() -> int:
    return subprocess.call([codex_bin(), "logout"])


def config_overrides() -> list[str]:
    """`-c` args that keep the user's credential store when a caller ignores the rest of config.toml."""
    path = os.path.join(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "config.toml")
    try:
        with open(path, "rb") as f:
            store = tomllib.load(f).get("cli_auth_credentials_store")
    except (OSError, tomllib.TOMLDecodeError):
        return []
    return ["-c", f'cli_auth_credentials_store="{store}"'] if store else []
