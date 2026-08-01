"""PromiseLink launcher for PyInstaller packaging.

启动 uvicorn 服务并自动打开浏览器到 http://localhost:8000
"""

import os
import sys
import threading
import time
import webbrowser


def _setup_ssl_bundle() -> None:
    """PyInstaller 打包后系统 CA 证书束不可用，显式指向 certifi 的 cacert.pem。

    Without this, SSL verification fails with:
        "unable to get local issuer certificate"
    影响场景：relay WSS 连接网关、OAuth/微信登录回调、httpx 请求外部 HTTPS API。
    """
    try:
        import certifi
        ca_bundle = certifi.where()
        if os.path.isfile(ca_bundle):
            os.environ.setdefault("SSL_CERT_FILE", ca_bundle)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_bundle)
            os.environ.setdefault("CURL_CA_BUNDLE", ca_bundle)
    except ImportError:
        # certifi 未安装时静默降级（开发模式下系统证书可用）
        pass


def _open_browser_after_delay(delay_seconds: float = 2.0) -> None:
    """Open browser after server starts (called in background thread)."""
    time.sleep(delay_seconds)
    webbrowser.open("http://localhost:8000")


def main() -> None:
    """Entry point for packaged PromiseLink executable."""
    # PyInstaller 打包后必须先设置 SSL CA 证书束，再启动 server
    _setup_ssl_bundle()

    # Print banner
    print("=" * 60)
    print("  PromiseLink - 智能人脉关系管理助手")
    print("  Starting local server at http://localhost:8000")
    print("  Press Ctrl+C to stop")
    print("=" * 60)

    # Open browser after delay (non-blocking)
    browser_thread = threading.Thread(target=_open_browser_after_delay, daemon=True)
    browser_thread.start()

    # Import uvicorn here so PyInstaller can detect it
    import uvicorn

    # Run server
    uvicorn.run(
        "promiselink.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    main()
