import html
import json
import os
import time
from collections import deque
from typing import Any

import httpx
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

import telemetry_store

load_dotenv()

APP_NAME = "provider-gateway"
APP_VERSION = "0.1.0"

ALLOWED_RPC_METHODS = {
    "getAccountInfo",
    "getBalance",
    "getBlockHeight",
    "getLatestBlockhash",
    "getMinimumBalanceForRentExemption",
    "getProgramAccounts",
    "getRecentPrioritizationFees",
    "getSignatureStatuses",
    "getSignaturesForAddress",
    "getStakeActivation",
    "getTokenAccountBalance",
    "getTokenAccountsByOwner",
    "getTokenSupply",
    "getTransaction",
    "getVersion",
    "getVoteAccounts",
    "getSlot",
    "simulateTransaction",
    "sendTransaction",
}

ALLOWED_EVM_RPC_METHODS = {
    "alchemy_getTokenBalances",
    "eth_blockNumber",
    "eth_call",
    "eth_chainId",
    "eth_estimateGas",
    "eth_feeHistory",
    "eth_gasPrice",
    "eth_getBalance",
    "eth_getBlockByNumber",
    "eth_getCode",
    "eth_getTransactionCount",
    "eth_getTransactionReceipt",
    "eth_maxPriorityFeePerGas",
    "eth_sendRawTransaction",
}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _trim(value: str | None) -> str:
    return (value or "").strip()


def _json_error(message: str, status_code: int = 400, extra: dict[str, Any] | None = None) -> JSONResponse:
    payload = {"ok": False, "error": message}
    if extra:
        payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


def _status_bucket(status_code: int) -> str:
    if status_code < 300:
        return "2xx"
    if status_code < 400:
        return "3xx"
    if status_code < 500:
        return "4xx"
    return "5xx"


def _latency_bucket(started: float) -> str:
    elapsed_ms = max((time.monotonic() - started) * 1000, 0)
    if elapsed_ms < 100:
        return "lt_100ms"
    if elapsed_ms < 500:
        return "100_500ms"
    if elapsed_ms < 2000:
        return "500ms_2s"
    return "gt_2s"


def _record_rpc_usage(
    *,
    endpoint: str,
    network: str,
    provider: str,
    method: str,
    status_code: int,
    started: float,
) -> None:
    try:
        telemetry_store.record_rpc_usage(
            endpoint=endpoint,
            network=network,
            provider=provider,
            method=method,
            status_bucket=_status_bucket(status_code),
            latency_bucket=_latency_bucket(started),
        )
    except Exception:
        pass


def _format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def _format_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _friendly_label(value: str) -> str:
    mapping = {
        "core_wallet": "core wallet",
        "solana_wallet": "solana wallet",
        "solana_defi": "solana defi",
        "evm_wallet": "evm wallet",
        "evm_defi": "evm defi",
        "cross_chain": "cross-chain",
        "btc": "btc",
        "x402": "x402",
        "autonomous": "autonomous",
        "tool_invocations": "tool invocations",
        "plugin_installs": "plugin installs",
        "active_installs": "active installs",
        "tool_successes": "tool successes",
        "rpc_calls": "rpc usage",
    }
    return mapping.get(value, value.replace("_", " "))


def _wants_html(request: Request) -> bool:
    format_hint = request.query_params.get("format", "").strip().lower()
    if format_hint == "html":
        return True
    if format_hint == "json":
        return False
    accept = request.headers.get("accept", "").lower()
    return "text/html" in accept


def _lookup_breakdown(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("key", "")) == key:
            return row
    return None


def _legacy_stats_payload(stats: dict[str, Any]) -> dict[str, Any]:
    legacy_npm = {
        key: value
        for key, value in dict(stats.get("npm_downloads") or {}).items()
        if key in {
            "ok",
            "package",
            "since",
            "through",
            "all_time",
            "last_30_days",
            "last_7_days",
            "days",
            "cached",
            "stale",
            "disabled",
            "error",
        }
    }
    return {
        "ok": stats.get("ok"),
        "window_days": stats.get("window_days"),
        "total_events": stats.get("total_events"),
        "active_installs": stats.get("active_installs"),
        "dau": stats.get("dau"),
        "success_rate": stats.get("success_rate"),
        "by_event": stats.get("by_event"),
        "by_host": stats.get("by_host"),
        "by_tool": stats.get("by_tool"),
        "by_backend": stats.get("by_backend"),
        "by_version": stats.get("by_version"),
        "by_source": stats.get("by_source"),
        "by_command": stats.get("by_command"),
        "npm_downloads": legacy_npm,
        "rpc_usage": stats.get("rpc_usage"),
    }


def _svg_line_chart(
    title: str,
    series: list[dict[str, Any]],
    *,
    value_key: str = "count",
    accent: str = "#2563eb",
    days: int = 30,
) -> str:
    rows = series[-days:] if days > 0 else list(series)
    values = [int(row.get(value_key, 0) or 0) for row in rows]
    labels = [str(row.get("day", ""))[5:] for row in rows]
    total = sum(values)
    peak = max(values, default=0)
    width = 520
    height = 220
    left = 46
    right = 16
    top = 18
    bottom = 34
    plot_w = max(width - left - right, 1)
    plot_h = max(height - top - bottom, 1)
    max_value = max(peak, 1)

    def _x(idx: int) -> float:
        if len(values) <= 1:
            return left
        return left + (plot_w * idx / (len(values) - 1))

    def _y(value: int) -> float:
        return top + plot_h - ((value / max_value) * plot_h)

    points = " ".join(f"{_x(idx):.2f},{_y(value):.2f}" for idx, value in enumerate(values)) if values else ""
    area_points = (
        f"{left:.2f},{top + plot_h:.2f} "
        + " ".join(f"{_x(idx):.2f},{_y(value):.2f}" for idx, value in enumerate(values))
        + f" {left + plot_w:.2f},{top + plot_h:.2f}"
        if values
        else ""
    )

    grid = []
    for step in range(4):
        ratio = step / 3 if step else 0
        y = top + plot_h - (plot_h * ratio)
        value = int(round(max_value * ratio))
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#e5e7eb" stroke-width="1" />'
            f'<text x="{left - 10}" y="{y + 4:.2f}" text-anchor="end" class="axis">{html.escape(_format_int(value))}</text>'
        )

    label_marks = []
    if labels:
        indices = sorted({0, len(labels) // 2, len(labels) - 1})
        for idx in indices:
            x = _x(idx)
            label_marks.append(
                f'<text x="{x:.2f}" y="{height - 10}" text-anchor="middle" class="axis">{html.escape(labels[idx])}</text>'
            )

    svg = f"""
    <section class="chart-card">
      <div class="chart-head">
        <div>
          <h3>{html.escape(title)}</h3>
          <p>{html.escape(_format_int(total))} total</p>
        </div>
        <div class="chart-meta">peak/day {html.escape(_format_int(peak))}</div>
      </div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" />
        {''.join(grid)}
        {'<polygon points="' + area_points + f'" fill="{accent}" opacity="0.10" />' if area_points else ''}
        {'<polyline points="' + points + f'" fill="none" stroke="{accent}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />' if points else ''}
        {''.join(label_marks)}
      </svg>
    </section>
    """
    return svg


def _svg_bar_chart(
    title: str,
    rows: list[dict[str, Any]],
    *,
    value_field: str = "calls",
    accent: str = "#0f766e",
    limit: int = 7,
) -> str:
    rows = list(rows[:limit])
    if not rows:
        return f"""
        <section class="chart-card">
          <div class="chart-head"><div><h3>{html.escape(title)}</h3><p>no data</p></div></div>
        </section>
        """
    values = [int(row.get(value_field, 0) or 0) for row in rows]
    labels = [_friendly_label(str(row.get("key", ""))) for row in rows]
    peak = max(values, default=1)
    width = 520
    row_h = 34
    top = 18
    left = 130
    right = 16
    height = top + len(rows) * row_h + 12
    plot_w = max(width - left - right, 1)
    bars = []
    for idx, (label, value) in enumerate(zip(labels, values)):
        y = top + idx * row_h
        bar_w = (value / peak) * plot_w if peak else 0
        bars.append(
            f'<text x="{left - 12}" y="{y + 18}" text-anchor="end" class="label">{html.escape(label)}</text>'
            f'<rect x="{left}" y="{y + 5}" width="{plot_w}" height="16" rx="8" fill="#f3f4f6" />'
            f'<rect x="{left}" y="{y + 5}" width="{bar_w:.2f}" height="16" rx="8" fill="{accent}" />'
            f'<text x="{left + min(bar_w + 8, plot_w)}" y="{y + 18}" class="axis">{html.escape(_format_int(value))}</text>'
        )
    return f"""
    <section class="chart-card">
      <div class="chart-head">
        <div>
          <h3>{html.escape(title)}</h3>
          <p>top {len(rows)} by {html.escape(value_field)}</p>
        </div>
      </div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">
        <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" />
        {''.join(bars)}
      </svg>
    </section>
    """


def _html_table(
    title: str,
    rows: list[dict[str, Any]],
    *,
    fields: list[tuple[str, str]],
    limit: int = 10,
) -> str:
    rows = list(rows[:limit])
    header = "".join(f"<th>{html.escape(label)}</th>" for _field, label in fields)
    body_rows = []
    for row in rows:
        cells = []
        for field, _label in fields:
            value = row.get(field)
            if field == "key":
                rendered = _friendly_label(str(value or ""))
            elif field == "success_rate":
                rendered = _format_pct(value)
            else:
                rendered = _format_int(value)
            cells.append(f"<td>{html.escape(rendered)}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    if not body_rows:
        body_rows.append(f'<tr><td colspan="{len(fields)}">no data</td></tr>')
    return f"""
    <section class="table-card">
      <div class="table-head">
        <h3>{html.escape(title)}</h3>
      </div>
      <table>
        <thead><tr>{header}</tr></thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
    </section>
    """


def _render_telemetry_dashboard(stats: dict[str, Any]) -> str:
    success_by_family = list(stats.get("success_by_family") or [])
    install_family = _lookup_breakdown(success_by_family, "installs") or {}
    tool_family = _lookup_breakdown(success_by_family, "tool_invocations") or {}
    rpc_usage = dict(stats.get("rpc_usage") or {})
    npm = dict(stats.get("npm_downloads") or {})
    daily = dict(stats.get("daily") or {})
    raw_json = html.escape(json.dumps(_legacy_stats_payload(stats), indent=2, sort_keys=True))
    downloads_chart = (
        _svg_line_chart(
            "Downloads",
            list(npm.get("daily_window") or []),
            value_key="downloads",
            accent="#7c3aed",
            days=30,
        )
        if npm.get("ok")
        else f"""
        <section class="chart-card">
          <div class="chart-head">
            <div><h3>Downloads</h3><p>unavailable</p></div>
            <div class="chart-meta">{html.escape(str(npm.get('error', 'disabled')))}</div>
          </div>
        </section>
        """
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AgentLayer Telemetry</title>
  <style>
    :root {{
      color-scheme: light;
    }}
    body {{
      margin: 0;
      background: #ffffff;
      color: #111111;
      font: 14px/1.45 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }}
    .wrap {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 32px 24px 56px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 28px;
      padding-bottom: 18px;
      border-bottom: 1px solid #e5e7eb;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 24px;
      line-height: 1.1;
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: #4b5563;
    }}
    .hero-meta {{
      color: #6b7280;
      font-size: 12px;
      text-align: right;
    }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-bottom: 22px;
    }}
    .kpi {{
      border: 1px solid #e5e7eb;
      border-radius: 16px;
      padding: 16px;
      background: #fafafa;
    }}
    .kpi .label {{
      color: #6b7280;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .kpi .value {{
      margin-top: 10px;
      font-size: 28px;
      line-height: 1;
      letter-spacing: -0.04em;
      font-weight: 700;
    }}
    .kpi .sub {{
      margin-top: 8px;
      color: #4b5563;
      font-size: 12px;
    }}
    .section-title {{
      margin: 28px 0 14px;
      font-size: 13px;
      color: #6b7280;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }}
    .grid-3 {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }}
    .chart-card, .table-card, .raw-card {{
      border: 1px solid #e5e7eb;
      border-radius: 18px;
      background: #ffffff;
      padding: 16px;
    }}
    .chart-head, .table-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 12px;
    }}
    .chart-head h3, .table-head h3 {{
      margin: 0;
      font-size: 15px;
      font-weight: 700;
    }}
    .chart-head p {{
      margin: 4px 0 0;
      color: #6b7280;
      font-size: 12px;
    }}
    .chart-meta {{
      color: #6b7280;
      font-size: 12px;
      white-space: nowrap;
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .axis {{
      fill: #6b7280;
      font-size: 11px;
    }}
    .label {{
      fill: #111111;
      font-size: 11px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      text-align: left;
      padding: 9px 0;
      border-bottom: 1px solid #f0f1f3;
    }}
    th {{
      color: #6b7280;
      font-weight: 600;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .raw-card pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      overflow: auto;
      max-height: 520px;
      padding-top: 10px;
      color: #1f2937;
      font-size: 12px;
      line-height: 1.5;
    }}
    details summary {{
      cursor: pointer;
      color: #111111;
      font-weight: 700;
    }}
    @media (max-width: 980px) {{
      .kpis, .grid-2, .grid-3 {{
        grid-template-columns: 1fr;
      }}
      .hero {{
        display: block;
      }}
      .hero-meta {{
        text-align: left;
        margin-top: 10px;
      }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div>
        <h1>AgentLayer telemetry</h1>
        <p>Minimal, server-rendered analytics view over wallet adoption and provider usage.</p>
      </div>
      <div class="hero-meta">
        <div>window {html.escape(_format_int(stats.get("window_days", 0)))}d</div>
        <div>generated {html.escape(time.strftime("%Y-%m-%d %H:%M:%S"))}</div>
        <div>raw JSON: <code>?format=json</code></div>
      </div>
    </section>

    <section class="kpis">
      <article class="kpi">
        <div class="label">Active Installs</div>
        <div class="value">{html.escape(_format_int(stats.get("active_installs", 0)))}</div>
        <div class="sub">24h {html.escape(_format_int(stats.get("dau", 0)))}</div>
      </article>
      <article class="kpi">
        <div class="label">Wallet-Active Installs</div>
        <div class="value">{html.escape(_format_int(stats.get("wallet_active_installs", 0)))}</div>
        <div class="sub">24h {html.escape(_format_int(stats.get("wallet_dau", 0)))}</div>
      </article>
      <article class="kpi">
        <div class="label">Total Events</div>
        <div class="value">{html.escape(_format_int(stats.get("total_events", 0)))}</div>
        <div class="sub">tool success {html.escape(_format_pct(tool_family.get("success_rate")))}</div>
      </article>
      <article class="kpi">
        <div class="label">RPC Usage</div>
        <div class="value">{html.escape(_format_int(rpc_usage.get("total_calls", 0)))}</div>
        <div class="sub">provider gateway usage</div>
      </article>
      <article class="kpi">
        <div class="label">NPM All-Time</div>
        <div class="value">{html.escape(_format_int(npm.get("all_time", 0)))}</div>
        <div class="sub">30d {html.escape(_format_int(npm.get("last_30_days", 0)))}</div>
      </article>
    </section>

    <div class="section-title">Core Trends</div>
    <section class="grid-2">
      {_svg_line_chart("Events", list(daily.get("events") or []), accent="#2563eb", days=30)}
      {downloads_chart}
      {_svg_line_chart("RPC Usage", list(daily.get("rpc_calls") or []), accent="#0f766e", days=30)}
      {_svg_line_chart("Active Installs", list(daily.get("active_installs") or []), accent="#ea580c", days=30)}
      {_svg_line_chart("Wallet-Active Installs", list(daily.get("wallet_active_installs") or []), accent="#dc2626", days=30)}
    </section>

    <div class="section-title">Composition</div>
    <section class="grid-3">
      {_svg_bar_chart("Wallet Host Mix", list(stats.get("wallet_by_host") or []), accent="#111827")}
      {_svg_bar_chart("Backend Mix", list(stats.get("by_backend") or []), accent="#b45309")}
      {_svg_bar_chart("Tool Categories", list(stats.get("by_tool_category") or []), accent="#7c3aed")}
    </section>

    <div class="section-title">Detail</div>
    <section class="grid-2">
      {_html_table("Top Tools", list(stats.get("by_tool") or []), fields=[("key", "tool"), ("calls", "calls"), ("installs", "installs")])}
      {_html_table("Event Families", success_by_family, fields=[("key", "family"), ("calls", "calls"), ("ok_calls", "ok"), ("success_rate", "success")], limit=6)}
      {_html_table("RPC Methods", list(rpc_usage.get("by_method") or []), fields=[("key", "method"), ("calls", "calls")], limit=8)}
      {_html_table("RPC Status / Latency", list(rpc_usage.get("by_status") or []), fields=[("key", "status"), ("calls", "calls")], limit=8)}
    </section>

    <div class="section-title">Raw Data</div>
    <section class="raw-card">
      <details open>
        <summary>Original stats payload</summary>
        <pre>{raw_json}</pre>
      </details>
    </section>
  </div>
</body>
</html>"""


def _require_bearer(request: Request) -> str | None:
    if not _bool_env("REQUIRE_BEARER_AUTH", False):
        return None

    expected = _trim(os.getenv("PROVIDER_GATEWAY_BEARER_TOKEN"))
    if not expected:
        raise RuntimeError(
            "REQUIRE_BEARER_AUTH=true but PROVIDER_GATEWAY_BEARER_TOKEN is not configured"
        )

    actual = request.headers.get("authorization", "")
    if actual != f"Bearer {expected}":
        return "Unauthorized"
    return None


def _require_machine_token(request: Request) -> str | None:
    if not _bool_env("REQUIRE_BEARER_AUTH", False):
        return None

    expected = _trim(os.getenv("PROVIDER_GATEWAY_BEARER_TOKEN"))
    if not expected:
        raise RuntimeError(
            "REQUIRE_BEARER_AUTH=true but PROVIDER_GATEWAY_BEARER_TOKEN is not configured"
        )

    actual = request.headers.get("authorization", "")
    if actual == f"Bearer {expected}":
        return None

    query_token = request.query_params.get("token", "").strip()
    if query_token == expected:
        return None

    return "Unauthorized"


def _http_timeout_seconds() -> float:
    raw = _trim(os.getenv("HTTP_TIMEOUT_SECONDS")) or "20"
    return max(float(raw), 1.0)


def _bags_base_url() -> str:
    return _trim(os.getenv("BAGS_API_BASE_URL")) or "https://public-api-v2.bags.fm/api/v1"


def _bags_headers() -> dict[str, str]:
    api_key = _trim(os.getenv("BAGS_API_KEY"))
    if not api_key:
        raise RuntimeError("BAGS_API_KEY is not configured")
    return {"x-api-key": api_key}


def _jupiter_lend_base_url() -> str:
    return _trim(os.getenv("JUPITER_LEND_API_BASE_URL")) or "https://api.jup.ag/lend/v1"


def _jupiter_headers() -> dict[str, str]:
    api_key = _trim(os.getenv("JUPITER_API_KEY"))
    if not api_key:
        raise RuntimeError("JUPITER_API_KEY is not configured")
    return {"x-api-key": api_key}


def _flash_base_url() -> str:
    return _trim(os.getenv("FLASH_API_BASE_URL"))


def _flash_configured() -> bool:
    return bool(_flash_base_url())


def _houdini_base_url() -> str:
    return _trim(os.getenv("HOUDINI_API_BASE_URL")) or "https://api-partner.houdiniswap.com/v2"


def _houdini_configured() -> bool:
    return bool(_trim(os.getenv("HOUDINI_API_KEY")) and _trim(os.getenv("HOUDINI_API_SECRET")))


def _extract_request_ip(request: Request) -> str:
    for header_name in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        raw = request.headers.get(header_name, "").strip()
        if not raw:
            continue
        if header_name == "x-forwarded-for":
            return raw.split(",")[0].strip()
        return raw
    client = request.client
    if client and getattr(client, "host", ""):
        return str(client.host).strip()
    return ""


def _houdini_headers(request: Request) -> dict[str, str]:
    api_key = _trim(os.getenv("HOUDINI_API_KEY"))
    api_secret = _trim(os.getenv("HOUDINI_API_SECRET"))
    if not api_key or not api_secret:
        raise RuntimeError("HOUDINI_API_KEY and HOUDINI_API_SECRET are required")

    user_ip = _extract_request_ip(request)
    if not user_ip:
        raise RuntimeError("Could not determine user IP for Houdini compliance headers")

    user_agent = (
        request.headers.get("x-user-agent", "").strip()
        or request.headers.get("user-agent", "").strip()
        or _trim(os.getenv("HOUDINI_USER_AGENT"))
        or "AgentLayer/provider-gateway"
    )
    user_timezone = (
        request.headers.get("x-user-timezone", "").strip()
        or _trim(os.getenv("HOUDINI_USER_TIMEZONE"))
        or "UTC"
    )
    return {
        "Accept": "application/json",
        "Authorization": f"{api_key}:{api_secret}",
        "x-user-ip": user_ip,
        "x-user-agent": user_agent,
        "x-user-timezone": user_timezone,
    }

def _jupiter_swap_base_url() -> str:
    return _trim(os.getenv("JUPITER_SWAP_API_BASE_URL")) or "https://lite-api.jup.ag/swap/v1"

def _jupiter_swap_configured() -> bool:
    return bool(_trim(os.getenv("JUPITER_API_KEY")))


def _uniswap_base_url() -> str:
    return _trim(os.getenv("UNISWAP_TRADING_API_BASE_URL")) or "https://trade-api.gateway.uniswap.org/v1"


def _uniswap_configured() -> bool:
    return bool(_trim(os.getenv("UNISWAP_API_KEY")))


_UNISWAP_SUPPORTED_CHAIN_IDS = frozenset({"1", "8453", "4663"})


def _uniswap_router_version_for_request(request: Request) -> str:
    """Select the configured router version; never proxy a caller's selection."""
    requested_chain_id = _trim(request.headers.get("x-agentlayer-chain-id"))
    if requested_chain_id and requested_chain_id not in _UNISWAP_SUPPORTED_CHAIN_IDS:
        raise ValueError("x-agentlayer-chain-id must be one of: 1, 8453, 4663")

    configured_by_chain_raw = _trim(os.getenv("UNISWAP_ROUTER_VERSION_BY_CHAIN"))
    configured_by_chain: dict[str, str] = {}
    if configured_by_chain_raw:
        try:
            parsed = json.loads(configured_by_chain_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("UNISWAP_ROUTER_VERSION_BY_CHAIN must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("UNISWAP_ROUTER_VERSION_BY_CHAIN must be a JSON object")
        for chain_id, version in parsed.items():
            normalized_chain_id = _trim(str(chain_id))
            normalized_version = _trim(str(version))
            if normalized_chain_id not in _UNISWAP_SUPPORTED_CHAIN_IDS or not normalized_version:
                raise RuntimeError("UNISWAP_ROUTER_VERSION_BY_CHAIN contains an invalid chain or version")
            configured_by_chain[normalized_chain_id] = normalized_version

    fallback = _trim(os.getenv("UNISWAP_ROUTER_VERSION")) or "2.0"
    effective = configured_by_chain.get(requested_chain_id, fallback)
    requested_version = _trim(request.headers.get("x-agentlayer-uniswap-router-version"))
    if requested_version and requested_version != effective:
        raise ValueError("Requested Uniswap router version does not match gateway configuration")
    return effective


def _uniswap_headers(*, router_version: str, erc20eth_enabled: bool = False) -> dict[str, str]:
    api_key = _trim(os.getenv("UNISWAP_API_KEY"))
    if not api_key:
        raise RuntimeError("UNISWAP_API_KEY is not configured")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-api-key": api_key,
        "x-universal-router-version": router_version,
    }
    if erc20eth_enabled:
        # This opt-in is required by Uniswap for native ETH input on an UniswapX
        # route. It is a fixed, validated header rather than a caller-controlled
        # header passthrough.
        headers["x-erc20eth-enabled"] = "true"
    return headers


def _provider_url_from_env(name: str, default: str = "") -> str:
    return _trim(os.getenv(name)) or default


def _resolve_rpc_url(provider: str, network: str) -> tuple[str, str]:
    if network != "mainnet":
        raise RuntimeError("Shared provider gateway RPC is mainnet-only.")

    shared_url = _provider_url_from_env("SHARED_SOLANA_RPC_URL")
    helius_url = _provider_url_from_env("HELIUS_SHARED_RPC_URL")
    helius_key = _trim(os.getenv("HELIUS_API_KEY"))
    alchemy_url = _provider_url_from_env("ALCHEMY_SHARED_RPC_URL")
    alchemy_key = _trim(os.getenv("ALCHEMY_API_KEY"))

    if not helius_url and helius_key:
        helius_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    if not alchemy_url and alchemy_key:
        alchemy_url = f"https://solana-mainnet.g.alchemy.com/v2/{alchemy_key}"

    if provider == "shared":
        if shared_url:
            return ("shared", shared_url)
        raise RuntimeError("SHARED_SOLANA_RPC_URL is not configured")

    if provider == "helius":
        if helius_url:
            return ("helius", helius_url)
        raise RuntimeError("Helius shared RPC is not configured")

    if provider == "alchemy":
        if alchemy_url:
            return ("alchemy", alchemy_url)
        raise RuntimeError("Alchemy shared RPC is not configured")

    if provider != "auto":
        raise RuntimeError(f"Unsupported RPC provider: {provider}")

    if shared_url:
        return ("shared", shared_url)
    if helius_url:
        return ("helius", helius_url)
    if alchemy_url:
        return ("alchemy", alchemy_url)
    raise RuntimeError(
        "No shared Solana RPC is configured. Set SHARED_SOLANA_RPC_URL, HELIUS_API_KEY/HELIUS_SHARED_RPC_URL, or ALCHEMY_API_KEY/ALCHEMY_SHARED_RPC_URL."
    )


def _resolve_evm_rpc_url(provider: str, network: str) -> tuple[str, str]:
    network_key = network.strip().lower()
    if network_key not in {"ethereum", "base", "robinhood"}:
        raise RuntimeError(
            "Shared EVM provider gateway RPC currently supports only ethereum, base, and robinhood."
        )

    shared_by_network = {
        "ethereum": _provider_url_from_env("SHARED_EVM_ETHEREUM_RPC_URL"),
        "base": _provider_url_from_env("SHARED_EVM_BASE_RPC_URL"),
        "robinhood": _provider_url_from_env("SHARED_EVM_ROBINHOOD_RPC_URL"),
    }
    alchemy_url_by_network = {
        "ethereum": _provider_url_from_env("ALCHEMY_ETHEREUM_RPC_URL"),
        "base": _provider_url_from_env("ALCHEMY_BASE_RPC_URL"),
        "robinhood": _provider_url_from_env("ALCHEMY_ROBINHOOD_RPC_URL"),
    }

    alchemy_key = _trim(os.getenv("ALCHEMY_API_KEY"))
    if alchemy_key:
        if not alchemy_url_by_network["ethereum"]:
            alchemy_url_by_network["ethereum"] = f"https://eth-mainnet.g.alchemy.com/v2/{alchemy_key}"
        if not alchemy_url_by_network["base"]:
            alchemy_url_by_network["base"] = f"https://base-mainnet.g.alchemy.com/v2/{alchemy_key}"
        if not alchemy_url_by_network["robinhood"]:
            alchemy_url_by_network["robinhood"] = f"https://robinhood-mainnet.g.alchemy.com/v2/{alchemy_key}"

    if provider == "shared":
        shared_url = shared_by_network[network_key]
        if shared_url:
            return ("shared", shared_url)
        raise RuntimeError(f"Shared EVM RPC is not configured for {network_key}")

    if provider == "alchemy":
        alchemy_url = alchemy_url_by_network[network_key]
        if alchemy_url:
            return ("alchemy", alchemy_url)
        raise RuntimeError(f"Alchemy EVM RPC is not configured for {network_key}")

    if provider != "auto":
        raise RuntimeError(f"Unsupported EVM RPC provider: {provider}")

    if shared_by_network[network_key]:
        return ("shared", shared_by_network[network_key])
    if alchemy_url_by_network[network_key]:
        return ("alchemy", alchemy_url_by_network[network_key])
    raise RuntimeError(
        f"No shared EVM RPC is configured for {network_key}. "
        "Set SHARED_EVM_<NETWORK>_RPC_URL, ALCHEMY_<NETWORK>_RPC_URL, or ALCHEMY_API_KEY."
    )


def _status_payload() -> dict[str, Any]:
    configured_rpc = []
    for provider in ("shared", "helius", "alchemy"):
        try:
            resolved, _ = _resolve_rpc_url(provider, "mainnet")
            configured_rpc.append(resolved)
        except Exception:
            continue

    evm_rpc_upstreams: dict[str, list[str]] = {}
    for network in ("ethereum", "base", "robinhood"):
        available: list[str] = []
        for provider in ("shared", "alchemy"):
            try:
                resolved, _ = _resolve_evm_rpc_url(provider, network)
                available.append(resolved)
            except Exception:
                continue
        if available:
            evm_rpc_upstreams[network] = available

    return {
        "ok": True,
        "service": APP_NAME,
        "version": APP_VERSION,
        "auth_required": _bool_env("REQUIRE_BEARER_AUTH", False),
        "bags_configured": bool(_trim(os.getenv("BAGS_API_KEY"))),
        "rpc_upstreams": configured_rpc,
        "allowed_rpc_methods": sorted(ALLOWED_RPC_METHODS),
        "evm_rpc_upstreams": evm_rpc_upstreams,
        "allowed_evm_rpc_methods": sorted(ALLOWED_EVM_RPC_METHODS),
        "bags_features": {
            "trade_quote": True,
            "trade_swap": True,
            "claim_positions": True,
            "claim_transactions": True,
            "claim_analytics": True,
            "launch_token_info": True,
            "launch_fee_share_config": True,
            "launch_transaction": True,
        },
        "jupiter_earn_configured": bool(_trim(os.getenv("JUPITER_API_KEY"))),
        "jupiter_earn_features": {
            "earn_tokens": True,
            "earn_positions": True,
            "earn_earnings": True,
            "earn_deposit": True,
            "earn_withdraw": True,
        },
        "flash_configured": _flash_configured(),
        "flash_features": {
            "perps_markets": True,
            "perps_positions": True,
        },
        "houdini_configured": _houdini_configured(),
        "houdini_features": {
            "tokens": True,
            "private_quotes": True,
            "exchange_create": True,
            "order_status": True,
            "multi_create": True,
            "multi_status": True,
            "multi_tx": True,
        },
        "jupiter_swap_configured": _jupiter_swap_configured(),
        "jupiter_swap_features": {
            "swap_quote": True,
            "swap_swap": True,
        },
        "uniswap_configured": _uniswap_configured(),
        "uniswap_features": {
            "quote": True,
            "swap": True,
        },
    }


def _require_query(request: Request, name: str) -> str:
    value = request.query_params.get(name, "").strip()
    if not value:
        raise ValueError(f"Missing required query parameter: {name}")
    return value


def _copy_optional_query(request: Request, names: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in names:
        value = request.query_params.get(name, "").strip()
        if value:
            result[name] = value
    return result


async def _http_get(url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.get(url, headers=headers, params=params)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


async def _http_post(url: str, *, headers: dict[str, str] | None = None, json_body: dict[str, Any] | None = None) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.post(url, headers=headers, json=json_body)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


async def _http_post_form(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data_body: dict[str, Any] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=_http_timeout_seconds()) as client:
        response = await client.post(url, headers=headers, data=data_body, files=files)
    if not response.content:
        return response.status_code, {}
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {"error": response.text[:500]}


def _require_body_dict(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def _validate_evm_rpc_payload(body: Any) -> tuple[dict[str, Any] | list[dict[str, Any]], str]:
    if isinstance(body, dict):
        entries = [body]
        normalized_body: dict[str, Any] | list[dict[str, Any]] = body
    elif isinstance(body, list) and body:
        if any(not isinstance(item, dict) for item in body):
            raise ValueError("JSON-RPC batch body must contain only objects")
        entries = body
        normalized_body = body
    else:
        raise ValueError("JSON body must be an object or a non-empty array of objects")

    for entry in entries:
        method = str(entry.get("method", "")).strip()
        if not method:
            raise ValueError("Field 'method' is required")
        if method not in ALLOWED_EVM_RPC_METHODS:
            raise PermissionError(method)
        params = entry.get("params", [])
        if not isinstance(params, list):
            raise TypeError("Field 'params' must be an array")
        entry["jsonrpc"] = str(entry.get("jsonrpc", "2.0") or "2.0")
        if "id" not in entry:
            entry["id"] = 1

    return normalized_body, entries[0]["method"]


def _require_string_field(body: dict[str, Any], name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{name}' is required")
    return value.strip()


def _require_list_field(body: dict[str, Any], name: str) -> list[Any]:
    value = body.get(name)
    if not isinstance(value, list) or not value:
        raise ValueError(f"Field '{name}' is required and must be a non-empty array")
    return value


def _normalize_form_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"))
    raise ValueError(f"Unsupported field type: {type(value).__name__}")


def _collect_form_fields_from_json(
    body: dict[str, Any],
    *,
    required_strings: list[str],
) -> dict[str, str]:
    data: dict[str, str] = {}
    for name in required_strings:
        value = body.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Field '{name}' is required")
        data[name] = value.strip()

    for key, value in body.items():
        if key in data or value is None:
            continue
        data[key] = _normalize_form_scalar(value)
    return data


def _validate_fee_share_body(body: dict[str, Any]) -> None:
    _require_string_field(body, "payer")
    _require_string_field(body, "baseMint")
    claimers = _require_list_field(body, "claimersArray")
    basis_points = _require_list_field(body, "basisPointsArray")
    if len(claimers) != len(basis_points):
        raise ValueError("claimersArray and basisPointsArray must have the same length")
    if len(claimers) > 100:
        raise ValueError("Bags fee share supports at most 100 claimers")
    if any(not isinstance(item, str) or not item.strip() for item in claimers):
        raise ValueError("claimersArray must contain non-empty wallet strings")
    if any(not isinstance(item, int) or item < 0 for item in basis_points):
        raise ValueError("basisPointsArray must contain non-negative integers")
    if sum(basis_points) != 10_000:
        raise ValueError("basisPointsArray must sum to exactly 10000")


async def _parse_launch_token_info_request(
    request: Request,
) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]] | None]:
    content_type = request.headers.get("content-type", "").lower()
    if "multipart/form-data" in content_type:
        form = await request.form()
        data: dict[str, str] = {}
        files: dict[str, tuple[str, bytes, str]] = {}
        for key, value in form.multi_items():
            filename = getattr(value, "filename", None)
            if filename:
                if key not in {"image", "imageFile"}:
                    raise ValueError("Only 'image' upload field is supported")
                content = await value.read()
                files["image"] = (
                    filename or "upload.bin",
                    content,
                    value.content_type or "application/octet-stream",
                )
                continue
            data[key] = _normalize_form_scalar(value)
        for required in ("name", "symbol", "description"):
            if not data.get(required, "").strip():
                raise ValueError(f"Field '{required}' is required")
        return data, files or None

    try:
        body = _require_body_dict(await request.json())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid JSON body") from exc
    return _collect_form_fields_from_json(
        body,
        required_strings=["name", "symbol", "description"],
    ), None


async def health(_: Request) -> JSONResponse:
    return JSONResponse(_status_payload())


async def status(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)
    return JSONResponse(_status_payload())


async def rpc_proxy(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)
    started = time.monotonic()

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)

    method = str(body.get("method", "")).strip()
    if not method:
        return _json_error("Field 'method' is required", 400)
    if method not in ALLOWED_RPC_METHODS:
        return _json_error(
            f"RPC method '{method}' is not allowed",
            403,
            {"allowed_methods": sorted(ALLOWED_RPC_METHODS)},
        )

    params = body.get("params", [])
    if not isinstance(params, list):
        return _json_error("Field 'params' must be an array", 400)

    provider = str(body.get("provider", "auto")).strip().lower() or "auto"
    network = str(body.get("network", "mainnet")).strip().lower() or "mainnet"

    try:
        resolved_provider, rpc_url = _resolve_rpc_url(provider, network)
    except Exception as exc:
        status_code = 403 if "mainnet-only" in str(exc) else 500
        _record_rpc_usage(
            endpoint="solana_rpc",
            network=network,
            provider=provider,
            method=method,
            status_code=status_code,
            started=started,
        )
        return _json_error(str(exc), status_code)

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

    try:
        status_code, upstream = await _http_post(rpc_url, json_body=payload)
    except httpx.HTTPError as exc:
        _record_rpc_usage(
            endpoint="solana_rpc",
            network=network,
            provider=resolved_provider,
            method=method,
            status_code=502,
            started=started,
        )
        return _json_error(f"RPC upstream error: {exc}", 502)

    response_status = 200 if status_code < 500 else 502
    _record_rpc_usage(
        endpoint="solana_rpc",
        network=network,
        provider=resolved_provider,
        method=method,
        status_code=response_status,
        started=started,
    )
    return JSONResponse(
        {
            "ok": status_code < 500,
            "provider": resolved_provider,
            "upstream_status": status_code,
            "rpc": upstream,
        },
        status_code=response_status,
    )


async def evm_rpc_proxy(request: Request) -> JSONResponse:
    auth_error = _require_machine_token(request)
    if auth_error:
        return _json_error(auth_error, 401)
    started = time.monotonic()

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        payload, method = _validate_evm_rpc_payload(body)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except TypeError as exc:
        return _json_error(str(exc), 400)
    except PermissionError as exc:
        return _json_error(
            f"EVM RPC method '{str(exc)}' is not allowed",
            403,
            {"allowed_methods": sorted(ALLOWED_EVM_RPC_METHODS)},
        )

    provider = str(request.query_params.get("provider", "auto")).strip().lower() or "auto"
    network = str(request.path_params.get("network", "")).strip().lower()

    try:
        resolved_provider, rpc_url = _resolve_evm_rpc_url(provider, network)
    except Exception as exc:
        status_code = 403 if "supports only" in str(exc) else 500
        _record_rpc_usage(
            endpoint="evm_rpc",
            network=network,
            provider=provider,
            method=method,
            status_code=status_code,
            started=started,
        )
        return _json_error(str(exc), status_code)

    try:
        status_code, upstream = await _http_post(rpc_url, json_body=payload)
    except httpx.HTTPError as exc:
        _record_rpc_usage(
            endpoint="evm_rpc",
            network=network,
            provider=resolved_provider,
            method=method,
            status_code=502,
            started=started,
        )
        return _json_error(f"EVM RPC upstream error: {exc}", 502)

    response_status = 200 if status_code < 500 else 502
    _record_rpc_usage(
        endpoint="evm_rpc",
        network=network,
        provider=resolved_provider,
        method=method,
        status_code=response_status,
        started=started,
    )
    response = JSONResponse(upstream, status_code=response_status)
    response.headers["X-Provider-Gateway-Upstream"] = resolved_provider
    response.headers["X-Provider-Gateway-Network"] = network
    return response


async def bags_trade_quote(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {
            "inputMint": _require_query(request, "inputMint"),
            "outputMint": _require_query(request, "outputMint"),
            "amount": _require_query(request, "amount"),
        }
        params.update(_copy_optional_query(request, ["slippageMode", "slippageBps"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/trade/quote",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags quote error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_trade_swap(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)
    if not isinstance(body.get("quoteResponse"), dict):
        return _json_error("Field 'quoteResponse' is required and must be an object", 400)
    if not isinstance(body.get("userPublicKey"), str) or not body["userPublicKey"].strip():
        return _json_error("Field 'userPublicKey' is required", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/trade/swap",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags swap error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_claim_positions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"wallet": _require_query(request, "wallet")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/claimable-positions",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim positions error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_claim_transactions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = await request.json()
    except Exception:
        return _json_error("Invalid JSON body", 400)

    if not isinstance(body, dict):
        return _json_error("JSON body must be an object", 400)
    for required in ("feeClaimer", "tokenMint"):
        if not isinstance(body.get(required), str) or not body[required].strip():
            return _json_error(f"Field '{required}' is required", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/token-launch/claim-txs/v3",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim tx error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_token_info(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        data, files = await _parse_launch_token_info_request(request)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_post_form(
            f"{_bags_base_url()}/token-launch/create-token-info",
            headers=_bags_headers(),
            data_body=data,
            files=files,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags launch token info error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_fee_share_config(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _validate_fee_share_body(body)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/fee-share/config",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags fee share config error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_launch_transaction(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "ipfs")
        _require_string_field(body, "tokenMint")
        _require_string_field(body, "wallet")
        _require_string_field(body, "configKey")
        if not str(body.get("initialBuyLamports", "")).strip():
            raise ValueError("Field 'initialBuyLamports' is required")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_bags_base_url()}/token-launch/create-launch-transaction",
            headers={**_bags_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags launch transaction error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_lifetime(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/lifetime-fees",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags lifetime fees error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_claim_stats(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/token-launch/claim-stats",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim stats error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def bags_fees_claim_events(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {"tokenMint": _require_query(request, "tokenMint")}
        params.update(_copy_optional_query(request, ["mode", "limit", "offset", "from", "to"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_bags_base_url()}/fee-share/token/claim-events",
            headers=_bags_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Bags claim events error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


def _split_csv_query(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise ValueError("Query parameter must contain at least one value")
    return items


async def jupiter_earn_tokens(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/tokens",
            headers=_jupiter_headers(),
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn tokens error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_positions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        users_raw = _require_query(request, "users")
        params = {"users": ",".join(_split_csv_query(users_raw))}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/positions",
            headers=_jupiter_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn positions error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_earnings(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        user = _require_query(request, "user")
        positions_raw = _require_query(request, "positions")
        params = {
            "user": user,
            "positions": ",".join(_split_csv_query(positions_raw)),
        }
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_lend_base_url()}/earn/earnings",
            headers=_jupiter_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn earnings error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_deposit(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "asset")
        _require_string_field(body, "signer")
        _require_string_field(body, "amount")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_jupiter_lend_base_url()}/earn/deposit",
            headers={**_jupiter_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn deposit error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_earn_withdraw(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "asset")
        _require_string_field(body, "signer")
        _require_string_field(body, "amount")
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_jupiter_lend_base_url()}/earn/withdraw",
            headers={**_jupiter_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter Earn withdraw error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def flash_perps_markets(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _flash_configured():
        return _json_error("Flash Trade is not configured", 503)

    params = _copy_optional_query(request, ["pool_name"])

    try:
        status_code, payload = await _http_get(
            f"{_flash_base_url()}/markets",
            params=params or None,
        )
    except httpx.HTTPError as exc:
        return _json_error(f"Flash Trade markets error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def flash_perps_positions(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _flash_configured():
        return _json_error("Flash Trade is not configured", 503)

    try:
        params = {"owner": _require_query(request, "owner")}
        params.update(_copy_optional_query(request, ["pool_name"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_flash_base_url()}/positions",
            params=params,
        )
    except httpx.HTTPError as exc:
        return _json_error(f"Flash Trade positions error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_swap_quote(request: Request) -> JSONResponse:
    """Proxy Jupiter swap quote with API key."""
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _jupiter_swap_configured():
        return _json_error("Jupiter swap is not configured", 503)

    try:
        params: dict[str, str] = {}
        for name in ("inputMint", "outputMint", "amount", "slippageBps",
                      "restrictIntermediateTokens", "onlyDirectRoutes", "swapMode"):
            value = request.query_params.get(name, "").strip()
            if value:
                params[name] = value
        if "inputMint" not in params or "outputMint" not in params or "amount" not in params:
            return _json_error("inputMint, outputMint, and amount are required", 400)
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_jupiter_swap_base_url()}/quote",
            headers=_jupiter_headers(),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter swap quote error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def jupiter_swap_swap(request: Request) -> JSONResponse:
    """Proxy Jupiter swap transaction build with API key."""
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _jupiter_swap_configured():
        return _json_error("Jupiter swap is not configured", 503)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "userPublicKey")
        if "quoteResponse" not in body or not isinstance(body["quoteResponse"], dict):
            return _json_error("quoteResponse is required and must be an object", 400)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_jupiter_swap_base_url()}/swap",
            headers={**_jupiter_headers(), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Jupiter swap swap error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def uniswap_quote(request: Request) -> JSONResponse:
    """Proxy a Uniswap Trading API quote, injecting the shared x-api-key.

    Lets the local EVM wallet daemon route Uniswap quotes through the gateway so
    the Uniswap key lives only here (never in per-machine wallet .env files). The
    request/response bodies are passed through verbatim.
    """
    auth_error = _require_machine_token(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _uniswap_configured():
        return _json_error("Uniswap is not configured", 503)

    try:
        body = _require_body_dict(await request.json())
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        router_version = _uniswap_router_version_for_request(request)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(f"Uniswap gateway configuration error: {exc}", 503)

    try:
        status_code, payload = await _http_post(
            f"{_uniswap_base_url()}/quote",
            headers=_uniswap_headers(
                router_version=router_version,
                erc20eth_enabled=request.headers.get("x-erc20eth-enabled", "").strip().lower()
                == "true"
            ),
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Uniswap quote error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def uniswap_order(request: Request) -> JSONResponse:
    """Submit a signed UniswapX order through the shared Trading API key."""
    auth_error = _require_machine_token(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _uniswap_configured():
        return _json_error("Uniswap is not configured", 503)

    try:
        body = _require_body_dict(await request.json())
        _require_string_field(body, "signature")
        routing = _require_string_field(body, "routing").upper()
        if routing not in {"DUTCH_V2", "DUTCH_V3", "LIMIT_ORDER", "PRIORITY"}:
            return _json_error(
                "Uniswap order routing must be DUTCH_V2, DUTCH_V3, LIMIT_ORDER, or PRIORITY", 400
            )
        body["routing"] = routing
        if not isinstance(body.get("quote"), dict):
            return _json_error("Field 'quote' is required and must be an object", 400)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        router_version = _uniswap_router_version_for_request(request)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(f"Uniswap gateway configuration error: {exc}", 503)

    try:
        status_code, payload = await _http_post(
            f"{_uniswap_base_url()}/order",
            headers=_uniswap_headers(
                router_version=router_version,
                erc20eth_enabled=request.headers.get("x-erc20eth-enabled", "").strip().lower()
                == "true"
            ),
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Uniswap order error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def uniswap_swap(request: Request) -> JSONResponse:
    """Proxy a Uniswap Trading API swap-calldata build, injecting the x-api-key."""
    auth_error = _require_machine_token(request)
    if auth_error:
        return _json_error(auth_error, 401)

    if not _uniswap_configured():
        return _json_error("Uniswap is not configured", 503)

    try:
        body = _require_body_dict(await request.json())
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        router_version = _uniswap_router_version_for_request(request)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except RuntimeError as exc:
        return _json_error(f"Uniswap gateway configuration error: {exc}", 503)

    try:
        status_code, payload = await _http_post(
            f"{_uniswap_base_url()}/swap",
            headers=_uniswap_headers(router_version=router_version),
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Uniswap swap error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_tokens(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params: dict[str, Any] = {"chain": _require_query(request, "chain")}
        params.update(_copy_optional_query(request, ["hasCex", "page", "pageSize"]))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_houdini_base_url()}/tokens",
            headers=_houdini_headers(request),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini tokens error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_private_quotes(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        params = {
            "from": _require_query(request, "from"),
            "to": _require_query(request, "to"),
            "amount": _require_query(request, "amount"),
            "types": "private",
        }
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_houdini_base_url()}/quotes",
            headers=_houdini_headers(request),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini quotes error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_multi_create(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        orders = body.get("orders")
        if not isinstance(orders, list) or not orders:
            return _json_error("Field 'orders' is required and must be a non-empty array", 400)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_houdini_base_url()}/exchanges/multi",
            headers={**_houdini_headers(request), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini multi create error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_exchange_create(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    try:
        body = _require_body_dict(await request.json())
        quote_id = body.get("quoteId")
        address_to = body.get("addressTo")
        if not isinstance(quote_id, str) or not quote_id.strip():
            return _json_error("Field 'quoteId' is required", 400)
        if not isinstance(address_to, str) or not address_to.strip():
            return _json_error("Field 'addressTo' is required", 400)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    except Exception:
        return _json_error("Invalid JSON body", 400)

    try:
        status_code, payload = await _http_post(
            f"{_houdini_base_url()}/exchanges",
            headers={**_houdini_headers(request), "Content-Type": "application/json"},
            json_body=body,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini exchange create error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_multi_status(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    multi_id = str(request.path_params.get("multi_id", "")).strip()
    if not multi_id:
        return _json_error("multi_id is required", 400)

    try:
        status_code, payload = await _http_get(
            f"{_houdini_base_url()}/exchanges/multi/{multi_id}",
            headers=_houdini_headers(request),
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini multi status error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_order_status(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    houdini_id = str(request.path_params.get("houdini_id", "")).strip()
    if not houdini_id:
        return _json_error("houdini_id is required", 400)

    try:
        status_code, payload = await _http_get(
            f"{_houdini_base_url()}/orders/{houdini_id}",
            headers=_houdini_headers(request),
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini order status error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


async def houdini_multi_tx(request: Request) -> JSONResponse:
    auth_error = _require_bearer(request)
    if auth_error:
        return _json_error(auth_error, 401)

    multi_id = str(request.path_params.get("multi_id", "")).strip()
    if not multi_id:
        return _json_error("multi_id is required", 400)
    try:
        params = {"sender": _require_query(request, "sender")}
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        status_code, payload = await _http_get(
            f"{_houdini_base_url()}/exchanges/multi/{multi_id}/tx",
            headers=_houdini_headers(request),
            params=params,
        )
    except (RuntimeError, httpx.HTTPError) as exc:
        return _json_error(f"Houdini multi tx error: {exc}", 502)

    return JSONResponse(payload, status_code=status_code)


# --- telemetry --------------------------------------------------------------

# Best-effort, in-memory per-IP sliding-window limiter. Telemetry is anonymous
# ingest from every wallet install, so the route is unauthenticated; this just
# blunts abuse. State is per-process and resets on redeploy — good enough for a
# low-stakes ingest endpoint.
_TELEMETRY_RL: dict[str, deque] = {}
_TELEMETRY_RL_MAX = int(os.getenv("TELEMETRY_RATE_LIMIT_PER_MIN", "120") or "120")


def _telemetry_rate_limited(ip: str) -> bool:
    if not ip:
        ip = "unknown"
    now = time.time()
    window = _TELEMETRY_RL.setdefault(ip, deque())
    while window and window[0] <= now - 60:
        window.popleft()
    if len(window) >= _TELEMETRY_RL_MAX:
        return True
    window.append(now)
    return False


def _telemetry_enabled() -> bool:
    return _bool_env("TELEMETRY_ENABLED", True)


async def telemetry_ingest(request: Request) -> JSONResponse:
    if not _telemetry_enabled():
        return JSONResponse({"ok": True, "stored": False, "disabled": True})

    if _telemetry_rate_limited(_extract_request_ip(request)):
        return _json_error("rate limited", 429)

    raw = await request.body()
    if len(raw) > telemetry_store.MAX_BODY_BYTES:
        return _json_error("payload too large", 413)

    try:
        parsed = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return _json_error("invalid JSON", 400)

    try:
        event = telemetry_store.validate_event(parsed)
    except telemetry_store.TelemetryValidationError as exc:
        return _json_error(str(exc), 422)

    try:
        telemetry_store.record_event(event)
    except Exception as exc:  # never let telemetry storage break the caller
        return _json_error(f"store error: {exc}", 500)

    return JSONResponse({"ok": True, "stored": True})


async def telemetry_stats(request: Request) -> Response:
    # Reading aggregates is privileged: adoption numbers must not be world-
    # readable. A dedicated TELEMETRY_STATS_TOKEN gates this route independently
    # of the global REQUIRE_BEARER_AUTH flag (which is currently off for the
    # public RPC endpoints), so stats can be locked down on its own. Accept the
    # token via `Authorization: Bearer <token>` or `?token=<token>`. If the env
    # var is unset, fall back to the machine-token gate.
    stats_token = _trim(os.getenv("TELEMETRY_STATS_TOKEN"))
    if stats_token:
        header = request.headers.get("authorization", "")
        query_token = request.query_params.get("token", "").strip()
        if header != f"Bearer {stats_token}" and query_token != stats_token:
            return _json_error("Unauthorized", 401)
    else:
        auth_error = _require_machine_token(request)
        if auth_error:
            return _json_error(auth_error, 401)
    try:
        window_days = int(request.query_params.get("window_days", "30"))
    except ValueError:
        window_days = 30
    window_days = max(1, min(window_days, 365))
    stats = telemetry_store.summary(window_days)
    if _wants_html(request):
        return HTMLResponse(_render_telemetry_dashboard(stats))
    return JSONResponse(stats)


routes = [
    Route("/health", health, methods=["GET"]),
    Route("/v1/status", status, methods=["GET"]),
    Route("/v1/rpc", rpc_proxy, methods=["POST"]),
    Route("/v1/evm/rpc/{network:str}", evm_rpc_proxy, methods=["POST"]),
    Route("/v1/bags/trade/quote", bags_trade_quote, methods=["GET"]),
    Route("/v1/bags/trade/swap", bags_trade_swap, methods=["POST"]),
    Route("/v1/bags/launch/token-info", bags_launch_token_info, methods=["POST"]),
    Route("/v1/bags/launch/fee-share-config", bags_launch_fee_share_config, methods=["POST"]),
    Route("/v1/bags/launch/transaction", bags_launch_transaction, methods=["POST"]),
    Route("/v1/bags/claim/positions", bags_claim_positions, methods=["GET"]),
    Route("/v1/bags/claim/transactions", bags_claim_transactions, methods=["POST"]),
    Route("/v1/bags/fees/lifetime", bags_fees_lifetime, methods=["GET"]),
    Route("/v1/bags/fees/claim-stats", bags_fees_claim_stats, methods=["GET"]),
    Route("/v1/bags/fees/claim-events", bags_fees_claim_events, methods=["GET"]),
    Route("/v1/jupiter/earn/tokens", jupiter_earn_tokens, methods=["GET"]),
    Route("/v1/jupiter/earn/positions", jupiter_earn_positions, methods=["GET"]),
    Route("/v1/jupiter/earn/earnings", jupiter_earn_earnings, methods=["GET"]),
    Route("/v1/jupiter/earn/deposit", jupiter_earn_deposit, methods=["POST"]),
    Route("/v1/jupiter/earn/withdraw", jupiter_earn_withdraw, methods=["POST"]),
    Route("/v1/flash/perps/markets", flash_perps_markets, methods=["GET"]),
    Route("/v1/flash/perps/positions", flash_perps_positions, methods=["GET"]),
    Route("/v1/jupiter/swap/quote", jupiter_swap_quote, methods=["GET"]),
    Route("/v1/jupiter/swap/swap", jupiter_swap_swap, methods=["POST"]),
    Route("/v1/evm/uniswap/quote", uniswap_quote, methods=["POST"]),
    Route("/v1/evm/uniswap/order", uniswap_order, methods=["POST"]),
    Route("/v1/evm/uniswap/swap", uniswap_swap, methods=["POST"]),
    Route("/v1/houdini/tokens", houdini_tokens, methods=["GET"]),
    Route("/v1/houdini/quotes/private", houdini_private_quotes, methods=["GET"]),
    Route("/v1/houdini/exchanges", houdini_exchange_create, methods=["POST"]),
    Route("/v1/houdini/orders/{houdini_id:str}", houdini_order_status, methods=["GET"]),
    Route("/v1/houdini/exchanges/multi", houdini_multi_create, methods=["POST"]),
    Route("/v1/houdini/exchanges/multi/{multi_id:str}", houdini_multi_status, methods=["GET"]),
    Route("/v1/houdini/exchanges/multi/{multi_id:str}/tx", houdini_multi_tx, methods=["GET"]),
    Route("/v1/telemetry", telemetry_ingest, methods=["POST"]),
    Route("/v1/telemetry/stats", telemetry_stats, methods=["GET"]),
]

app = Starlette(debug=False, routes=routes)

allowed_origins = _split_csv("ALLOWED_ORIGINS")
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
