import json
import os
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


APP_VERSION = "0.1.0"


def _env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _split_csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _extract_text_input(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("input"), str) and payload["input"].strip():
        return payload["input"].strip()

    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()

    params = payload.get("params")
    if isinstance(params, dict):
        if isinstance(params.get("input"), str) and params["input"].strip():
            return params["input"].strip()

        nested_message = params.get("message")
        if isinstance(nested_message, str) and nested_message.strip():
            return nested_message.strip()

        if isinstance(nested_message, dict):
            parts = nested_message.get("parts")
            if isinstance(parts, list):
                texts: list[str] = []
                for part in parts:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text = part["text"].strip()
                        if text:
                            texts.append(text)
                if texts:
                    return "\n".join(texts)

    raise ValueError("Cannot extract text input. Provide 'input' or A2A-like params.message.parts[].text")


def _extract_openclaw_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = data.get("output")
    if isinstance(output, list):
        collected: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    collected.append(text.strip())
        if collected:
            return "\n".join(collected)

    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)


async def _call_openclaw(prompt: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    base_url = _env("OPENCLAW_BASE_URL")
    model = _env("OPENCLAW_MODEL", "openclaw:main")
    token = os.getenv("OPENCLAW_API_TOKEN", "").strip()
    timeout_seconds = float(_env("OPENCLAW_TIMEOUT_SECONDS", "60"))

    url = f"{base_url.rstrip('/')}/v1/responses"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body: dict[str, Any] = {
        "model": model,
        "input": prompt,
    }
    if metadata:
        body["metadata"] = metadata

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(url, headers=headers, json=body)

    if resp.status_code >= 400:
        detail = resp.text[:1000]
        raise RuntimeError(f"OpenClaw upstream error {resp.status_code}: {detail}")

    return resp.json()


async def health(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "service": "openclaw-a2a-gateway", "version": APP_VERSION})


async def oasf(_: Request) -> JSONResponse:
    payload = {
        "name": _env("AGENT_NAME", "OpenClaw Agent"),
        "description": _env("AGENT_DESCRIPTION", "OpenClaw agent with MCP tools"),
        "skills": _split_csv("AGENT_SKILLS"),
        "domains": _split_csv("AGENT_DOMAINS"),
        "services": {
            "mcp": os.getenv("AGENT_MCP_URL", "").strip(),
            "a2a": os.getenv("AGENT_A2A_URL", "").strip(),
        },
    }
    return JSONResponse(payload)


async def agent_card(_: Request) -> JSONResponse:
    agent_a2a_url = os.getenv("AGENT_A2A_URL", "").strip()
    payload = {
        "name": _env("AGENT_NAME", "OpenClaw Agent"),
        "description": _env("AGENT_DESCRIPTION", "OpenClaw agent with MCP tools"),
        "url": agent_a2a_url,
        "version": APP_VERSION,
        "protocolVersion": "0.3.0",
        "capabilities": {
            "streaming": False,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": _split_csv("AGENT_SKILLS"),
        "domains": _split_csv("AGENT_DOMAINS"),
        "metadata": {
            "mcp_url": os.getenv("AGENT_MCP_URL", "").strip(),
            "oasf_url": os.getenv("AGENT_OASF_URL", "").strip(),
        },
    }

    if _bool_env("A2A_REQUIRE_API_KEY", False):
        payload["authentication"] = {
            "schemes": ["bearer"],
        }

    return JSONResponse(payload)


async def a2a(request: Request) -> JSONResponse:
    if _bool_env("A2A_REQUIRE_API_KEY", False):
        inbound = request.headers.get("authorization", "")
        expected = os.getenv("A2A_API_KEY", "").strip()
        if not expected:
            return JSONResponse({"error": "A2A_API_KEY is required when A2A_REQUIRE_API_KEY=true"}, status_code=500)
        if inbound != f"Bearer {expected}":
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    if not isinstance(payload, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)

    req_id = payload.get("id")

    try:
        prompt = _extract_text_input(payload)
        upstream = await _call_openclaw(prompt, metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None)
        text = _extract_openclaw_text(upstream)
    except Exception as exc:
        if req_id is not None:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(exc)},
                },
                status_code=502,
            )
        return JSONResponse({"error": str(exc)}, status_code=502)

    if req_id is not None:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "status": "completed",
                    "output": [{"type": "text", "text": text}],
                },
            }
        )

    return JSONResponse({"output": text})


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/oasf.json", oasf, methods=["GET"]),
    Route("/.well-known/agent.json", agent_card, methods=["GET"]),
    Route("/a2a", a2a, methods=["POST"]),
]

app = Starlette(debug=False, routes=routes)
