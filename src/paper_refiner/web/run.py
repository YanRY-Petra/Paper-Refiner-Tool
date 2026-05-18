"""Launch the web UI (uvicorn).

命令行传入的 ``--api-key`` / ``--api-base`` / ``--model`` 会写入环境变量，
在应用加载 ``.env`` 时**不会覆盖**这些已设置的变量（见 ``app.py`` lifespan）。

``llm.py`` 会对部分 base（如 ``api.deepseek.com``、``api.gptsapi.net``）在未带 ``/v1`` 时自动补全，
再请求 ``{base}/chat/completions``。

示例::

    paper-refiner-web --api-key sk-xxx --api-base https://api.deepseek.com --model deepseek-v4-flash
    paper-refiner-web --api-key sk-xxx --api-base https://api.gptsapi.net --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import errno
import os
import sys


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser(description="paper-refiner tool Web UI")
    p.add_argument("--host", default="0.0.0.0", help="监听地址")
    p.add_argument("--port", type=int, default=8765, help="端口")
    p.add_argument(
        "--api-key",
        dest="api_key",
        default=None,
        help="API 密钥（等价于 export OPENAI_API_KEY；优先于 .env）",
    )
    p.add_argument(
        "--api-base",
        dest="api_base",
        default=None,
        help="OpenAI 兼容 base，如 https://api.gptsapi.net 或 https://api.deepseek.com",
    )
    p.add_argument(
        "--model",
        dest="model",
        default=None,
        help="模型名，如 deepseek-v4-flash、deepseek-v4-pro、gpt-4o-mini",
    )
    args = p.parse_args()

    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key.strip()
    if args.api_base:
        os.environ["OPENAI_API_BASE"] = args.api_base.strip()
    if args.model:
        os.environ["OPENAI_MODEL"] = args.model.strip()

    try:
        uvicorn.run(
            "paper_refiner.web.app:app",
            host=args.host,
            port=args.port,
            reload=False,
        )
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 98) or "address already in use" in str(e).lower():
            print(
                f"\n端口 {args.port} 已被占用（通常是已有一个 paper-refiner-web 在跑）。\n"
                "请先结束旧进程，例如：\n"
                "  pgrep -af paper-refiner-web\n"
                "  kill <上面显示的 PID>\n"
                "或换端口启动：\n"
                f"  paper-refiner-web --port {args.port + 1}\n",
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    main()
