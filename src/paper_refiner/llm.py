from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# HTTP 状态码：限流与上游/网关临时故障，适合重试
_RETRIABLE_HTTP = frozenset({429, 500, 502, 503, 504})


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name)
    if v is None or v == "":
        if default is None:
            raise RuntimeError(f"Missing environment variable: {name}")
        return default
    return v


def normalize_openai_compatible_base_url(raw: str) -> str:
    """
    Build the prefix for ``.../chat/completions``.

    DeepSeek 文档中的 OpenAI 兼容 ``base_url`` 为 ``https://api.deepseek.com``（无 ``/v1``），
    而本仓库请求路径为 ``{base}/chat/completions``，故需补全为 ``https://api.deepseek.com/v1``。
    """
    s = (raw or "").strip().rstrip("/")
    if not s:
        return s
    low = s.lower()
    if "api.deepseek.com" in low and not low.endswith("/v1"):
        return s.rstrip("/") + "/v1"
    # gptsapi 等 OpenAI 兼容网关：若只填主机未带 /v1，则补上
    if "api.gptsapi.net" in low and not low.endswith("/v1"):
        return s.rstrip("/") + "/v1"
    return s


def _api_base() -> str:
    return normalize_openai_compatible_base_url(
        _env("OPENAI_API_BASE", "https://api.deepseek.com")
    )


def _normalize_api_key(raw: str) -> str:
    """Strip whitespace / newlines and optional wrapping quotes from .env paste mistakes."""
    key = (raw or "").strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
        key = key[1:-1].strip()
    return key


def _get_api_key() -> str:
    """
    Prefer OPENAI_API_KEY (OpenAI-compatible env name), then DEEPSEEK_API_KEY.
    """
    raw = os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    key = _normalize_api_key(raw)
    if not key:
        raise RuntimeError(
            "未设置 API 密钥：请使用命令行 `--api-key` 或在项目根目录 `.env` 中配置 "
            "OPENAI_API_KEY=（或 DEEPSEEK_API_KEY=）"
        )
    low = key.lower()
    bogus_substrings = (
        "your-key-here",
        "your-deepseek-key",
        "sk-your-key",
        "sk-xxx",
        "changeme",
        "placeholder",
        "example",
    )
    for frag in bogus_substrings:
        if frag in low:
            raise RuntimeError(
                "OPENAI_API_KEY 看起来仍是示例或占位内容。请到 https://platform.deepseek.com "
                "（或你使用的服务商）复制真实密钥。"
            )
    return key


def describe_llm_http_error(response: httpx.Response | None) -> str:
    """Short, safe summary of provider JSON error (redacts sk-… fragments)."""
    if response is None:
        return ""
    try:
        data = response.json()
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(data, ensure_ascii=False)[:400]
        else:
            msg = str(data)[:400]
    except (json.JSONDecodeError, ValueError, TypeError):
        msg = (response.text or "")[:400]
    msg = re.sub(r"sk-[a-zA-Z0-9_-]{8,}", "sk-***", msg, flags=re.IGNORECASE)
    return msg.strip()


def max_llm_concurrency() -> int:
    """单次批量改写时，同时发出的 LLM HTTP 请求上限（过大易触发 429）。"""
    raw = os.environ.get("OPENAI_MAX_CONCURRENT", "5")
    try:
        return max(1, min(int(raw), 32))
    except ValueError:
        return 5


def _llm_retry_count() -> int:
    """Max automatic retries after the first attempt (default 3 → up to 4 tries)."""
    raw = os.environ.get("OPENAI_RETRY_COUNT", "3")
    try:
        return max(0, min(int(raw), 10))
    except ValueError:
        return 3


def _llm_timeout() -> httpx.Timeout:
    # Connect 单独设短一些，连接抖动时更快进入重试
    return httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)


def _retry_backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter; attempt is 0-based."""
    try:
        base = float(os.environ.get("OPENAI_RETRY_BACKOFF", "1.5"))
    except ValueError:
        base = 1.5
    return min(30.0, base * (2**attempt)) + random.uniform(0, 0.3)


def _is_retriable_http_status(status_code: int) -> bool:
    return status_code in _RETRIABLE_HTTP


def _build_chat_request(
    user_message: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    base = _api_base().rstrip("/")
    key = _get_api_key()
    model_name = model or _env("OPENAI_MODEL", "deepseek-v4-flash")
    url = f"{base}/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "messages": [
            {"role": "user", "content": user_message},
        ],
    }
    return url, headers, payload


def _extract_chat_content(data: dict[str, Any]) -> str:
    try:
        return str(data["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Unexpected API response: {data!r}") from e


async def _post_chat_async(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    max_retries = _llm_retry_count()
    last_error: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.is_success:
                return response
            if _is_retriable_http_status(response.status_code) and attempt < max_retries:
                detail = describe_llm_http_error(response)
                logger.warning(
                    "LLM HTTP %s on attempt %s/%s, retrying: %s",
                    response.status_code,
                    attempt + 1,
                    max_retries + 1,
                    detail or response.text[:200],
                )
                await asyncio.sleep(_retry_backoff_seconds(attempt))
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else 0
            if _is_retriable_http_status(status) and attempt < max_retries:
                logger.warning(
                    "LLM HTTP %s on attempt %s/%s, retrying",
                    status,
                    attempt + 1,
                    max_retries + 1,
                )
                await asyncio.sleep(_retry_backoff_seconds(attempt))
                continue
            raise
        except httpx.RequestError as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    "LLM request error on attempt %s/%s (%s), retrying",
                    attempt + 1,
                    max_retries + 1,
                    type(e).__name__,
                )
                await asyncio.sleep(_retry_backoff_seconds(attempt))
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM request failed without a captured error")


def _post_chat_sync(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> httpx.Response:
    max_retries = _llm_retry_count()
    last_error: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.post(url, headers=headers, json=payload)
            if response.is_success:
                return response
            if _is_retriable_http_status(response.status_code) and attempt < max_retries:
                detail = describe_llm_http_error(response)
                logger.warning(
                    "LLM HTTP %s on attempt %s/%s, retrying: %s",
                    response.status_code,
                    attempt + 1,
                    max_retries + 1,
                    detail or response.text[:200],
                )
                time.sleep(_retry_backoff_seconds(attempt))
                continue
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else 0
            if _is_retriable_http_status(status) and attempt < max_retries:
                logger.warning(
                    "LLM HTTP %s on attempt %s/%s, retrying",
                    status,
                    attempt + 1,
                    max_retries + 1,
                )
                time.sleep(_retry_backoff_seconds(attempt))
                continue
            raise
        except httpx.RequestError as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(
                    "LLM request error on attempt %s/%s (%s), retrying",
                    attempt + 1,
                    max_retries + 1,
                    type(e).__name__,
                )
                time.sleep(_retry_backoff_seconds(attempt))
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM request failed without a captured error")


def _parse_chat_response_json(response: httpx.Response) -> dict[str, Any]:
    ct = (response.headers.get("content-type") or "").lower()
    text = response.text or ""
    if "json" not in ct and not text.strip().startswith("{"):
        raise RuntimeError(
            f"API 返回非 JSON（HTTP {response.status_code}），可能是 base_url 错误。"
            f" 当前请求 URL: {response.url}。DeepSeek 请使用 --api-base https://api.deepseek.com "
            f"或 OPENAI_API_BASE=https://api.deepseek.com 。正文片段: {text[:300]}"
        )
    try:
        return response.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"API 响应不是合法 JSON（HTTP {response.status_code}）: {text[:400]}"
        ) from e


async def rewrite_text_async(
    user_message: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
    client: httpx.AsyncClient | None = None,
) -> str:
    url, headers, payload = _build_chat_request(
        user_message, model=model, temperature=temperature
    )
    if client is not None:
        response = await _post_chat_async(client, url, headers, payload)
        data = _parse_chat_response_json(response)
        return _extract_chat_content(data)
    async with httpx.AsyncClient(timeout=_llm_timeout()) as c:
        response = await _post_chat_async(c, url, headers, payload)
        data = _parse_chat_response_json(response)
    return _extract_chat_content(data)


def rewrite_text_sync(
    user_message: str,
    *,
    model: str | None = None,
    temperature: float = 0.7,
) -> str:
    url, headers, payload = _build_chat_request(
        user_message, model=model, temperature=temperature
    )
    with httpx.Client(timeout=_llm_timeout()) as client:
        response = _post_chat_sync(client, url, headers, payload)
        data = _parse_chat_response_json(response)
    return _extract_chat_content(data)
