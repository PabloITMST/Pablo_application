"""LLM Provider: model calls. Uses Auth only to check the session.

Provider contract (duck-typed, consumers depend on nothing else):
    complete_json(prompt: str, schema: dict) -> dict
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

from pablo_v2 import auth


class ProviderError(RuntimeError):
    pass


class CodexProvider:
    """One-shot, read-only, no-tools completion through the signed-in Codex account."""

    def __init__(self, model: str | None = None, reasoning_effort: str = "low", timeout: int = 180):
        self.model, self.reasoning_effort, self.timeout = model, reasoning_effort, timeout

    def complete_json(self, prompt: str, schema: dict) -> dict:
        auth.require()
        with tempfile.TemporaryDirectory() as tmp:
            schema_path, out_path = os.path.join(tmp, "schema.json"), os.path.join(tmp, "out.json")
            with open(schema_path, "w", encoding="utf-8") as f:
                json.dump(schema, f)
            # --ignore-user-config: a personal config.toml may pin a model the ChatGPT plan can't use.
            # The credential store setting is passed back explicitly so sign-in still resolves.
            cmd = [auth.codex_bin(), "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
                   *auth.config_overrides(), "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
                   "-s", "read-only", "-C", tmp, "--output-schema", schema_path, "-o", out_path]
            if self.model:
                cmd += ["-m", self.model]
            cmd.append("-")  # prompt from stdin: avoids Windows cmd quoting
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                               timeout=self.timeout)
            if r.returncode != 0 or not os.path.exists(out_path):
                raise ProviderError(f"codex exec failed ({r.returncode}): {r.stderr[-2000:]}")
            with open(out_path, encoding="utf-8") as f:
                return json.load(f)


class ResponsesProvider:
    """M4.2: the desktop's Sign in with ChatGPT token (PABLO_ACCESS_TOKEN, set by the Electron main process for this
    child only) -> /v1/responses with a strict JSON schema. No `codex exec`, no `codex login`."""

    URL = "https://api.openai.com/v1/responses"

    def __init__(self, model: str, token: str, timeout: int = 180):
        self.model, self.token, self.timeout = model, token, timeout

    def complete_json(self, prompt: str, schema: dict) -> dict:
        body = {"model": self.model, "instructions": "Answer with JSON that matches the schema.", "store": False,
                "stream": True,  # the ChatGPT-plan endpoint streams (same call as the desktop's plan-usage check)
                "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
                "text": {"format": {"type": "json_schema", "name": "pablo", "schema": schema, "strict": True}}}
        req = urllib.request.Request(self.URL, json.dumps(body).encode(), {
            "authorization": "Bearer " + self.token, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                events = [json.loads(line[5:]) for line in r.read().decode("utf-8").splitlines()
                          if line.startswith("data:") and line[5:].strip() not in ("", "[DONE]")]
        except urllib.error.HTTPError as e:
            raise ProviderError(f"responses {e.code}: {e.read()[:500]!r}") from e
        except OSError as e:
            raise ProviderError(f"responses: {e}") from e
        done = next((e["response"] for e in events if e.get("type") == "response.completed"), None)
        if not done:
            raise ProviderError(f"responses: no response.completed ({str(events[-1:])[:500]})")
        # the streamed completed event may carry an empty output list; the deltas always have the text
        text = "".join(e.get("delta", "") for e in events if e.get("type") == "response.output_text.delta")
        return json.loads(text)


def provider(model: str | None = None):
    """The desktop passes its SIWC token + model; the CLI keeps `codex exec` with `codex login`."""
    token = os.environ.get("PABLO_ACCESS_TOKEN")
    return ResponsesProvider(model or os.environ["PABLO_MODEL"], token) if token else CodexProvider(model)
