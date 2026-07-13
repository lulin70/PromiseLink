"""Pairing page — inline HTML for device pairing mode.

Served at /pair when the basic edition starts without a PRO_LICENSE_KEY.
The page displays a QR code (generated from the device_pair_code) and
polls /api/v1/pair/status until the miniapp scans and matches.

License: MPL 2.0
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

_PAIR_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PromiseLink 专业版激活</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f5f7; min-height: 100vh; display: flex;
      align-items: center; justify-content: center; padding: 20px;
    }
    .card {
      background: #fff; border-radius: 16px; padding: 40px; max-width: 480px;
      width: 100%; box-shadow: 0 2px 12px rgba(0,0,0,0.08); text-align: center;
    }
    .logo { font-size: 28px; font-weight: 700; color: #333; margin-bottom: 8px; }
    .subtitle { font-size: 14px; color: #888; margin-bottom: 32px; }
    .status-icon { font-size: 48px; margin-bottom: 16px; }
    .status-text { font-size: 18px; color: #333; margin-bottom: 24px; font-weight: 500; }
    .qr-container {
      background: #fafafa; border: 2px dashed #ddd; border-radius: 12px;
      padding: 24px; margin: 24px 0;
    }
    .qr-code { display: flex; justify-content: center; margin-bottom: 16px; }
    .pair-code {
      font-size: 36px; font-weight: 700; color: #4a90d9;
      letter-spacing: 8px; margin: 16px 0;
    }
    .hint { font-size: 14px; color: #888; line-height: 1.6; margin-top: 16px; }
    .steps { text-align: left; margin: 24px 0; padding: 0 20px; }
    .steps li { font-size: 14px; color: #555; margin-bottom: 8px; line-height: 1.5; }
    .error { color: #e74c3c; }
    .success { color: #27ae60; }
    .spinner {
      border: 3px solid #f0f0f0; border-top: 3px solid #4a90d9;
      border-radius: 50%; width: 40px; height: 40px;
      animation: spin 1s linear infinite; margin: 0 auto 16px;
    }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    .btn {
      display: inline-block; padding: 12px 32px; background: #4a90d9;
      color: #fff; border-radius: 8px; text-decoration: none; font-size: 16px;
      border: none; cursor: pointer; margin-top: 16px;
    }
    .btn:hover { background: #357abd; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">PromiseLink</div>
    <div class="subtitle">专业版激活</div>
    <div id="content">
      <div class="spinner"></div>
      <div class="status-text">正在连接网关...</div>
    </div>
  </div>

  <script>
    let pairCode = '';
    let pollTimer = null;
    let initRetries = 0;

    async function initPair() {
      try {
        const res = await fetch('/api/v1/pair/init', { method: 'POST' });
        const data = await res.json();
        if (!data.success) {
          showError('连接网关失败：' + (data.error || '未知错误') + '<br>请检查网络后刷新页面重试。');
          return;
        }
        pairCode = data.device_pair_code;
        showQRCode(data.qr_content || ('https://www.promiselink.cn/pair?code=' + pairCode), pairCode, data.expires_in);
        startPolling();
      } catch (err) {
        initRetries++;
        if (initRetries < 3) {
          setTimeout(initPair, 3000);
        } else {
          showError('无法连接网关，请检查网络连接后刷新页面重试。<br>网关地址：' + (data?.gateway_url || 'gateway.promiselink.cn'));
        }
      }
    }

    function showQRCode(qrContent, code, expiresIn) {
      const qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' + encodeURIComponent(qrContent);
      document.getElementById('content').innerHTML = `
        <div class="status-text">请用微信「扫一扫」扫描下方二维码</div>
        <div class="qr-container">
          <div class="qr-code"><img src="${qrUrl}" alt="配对二维码" width="200" height="200" /></div>
          <div class="pair-code">${code}</div>
        </div>
        <div class="hint">
          <ol class="steps">
            <li>打开微信，点击右上角「+」→「扫一扫」</li>
            <li>扫描上方二维码，自动跳转 PromiseLink 小程序</li>
            <li>在小程序中确认配对，电脑端自动激活专业版</li>
          </ol>
        </div>
        <div class="hint" style="margin-top:16px;padding:12px;background:#fff3cd;border-radius:8px;color:#856404;">
          <strong>无法扫码？</strong>打开 PromiseLink 小程序 →「我的」→「专业版激活」→ 激活后点击「配对电脑」→ 输入配对码：<strong>${code}</strong>
        </div>
        <div class="hint">配对码有效期：${Math.floor(expiresIn / 60)} 分钟</div>
      `;
    }

    function startPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(async () => {
        try {
          const res = await fetch('/api/v1/pair/status?code=' + pairCode);
          const data = await res.json();
          if (data.success && data.status === 'matched' && data.license_key) {
            clearInterval(pollTimer);
            await activatePair(data.license_key);
          } else if (data.status === 'expired') {
            clearInterval(pollTimer);
            showExpired();
          }
        } catch (err) {
          // Network error — keep polling
        }
      }, 3000);
    }

    async function activatePair(licenseKey) {
      document.getElementById('content').innerHTML = `
        <div class="spinner"></div>
        <div class="status-text">配对成功！正在激活专业版...</div>
      `;
      try {
        const res = await fetch('/api/v1/pair/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ license_key: licenseKey }),
        });
        const data = await res.json();
        if (data.success) {
          showSuccess(data.message);
        } else {
          showError('激活失败：' + (data.error || '未知错误'));
        }
      } catch (err) {
        showError('激活请求失败，请刷新页面重试。');
      }
    }

    function showSuccess(msg) {
      document.getElementById('content').innerHTML = `
        <div class="status-icon success">&#10003;</div>
        <div class="status-text success">${msg || '专业版激活成功！'}</div>
        <div class="hint">即将跳转到主页面...</div>
        <button class="btn" onclick="location.href='/'">进入 PromiseLink</button>
      `;
      setTimeout(() => { location.href = '/'; }, 5000);
    }

    function showError(msg) {
      document.getElementById('content').innerHTML = `
        <div class="status-icon error">&#10007;</div>
        <div class="status-text error">${msg}</div>
        <button class="btn" onclick="location.reload()">重新尝试</button>
      `;
    }

    function showExpired() {
      document.getElementById('content').innerHTML = `
        <div class="status-icon error">&#8635;</div>
        <div class="status-text">配对码已过期</div>
        <div class="hint">请重新生成配对码</div>
        <button class="btn" onclick="initPair()">重新生成</button>
      `;
    }

    initPair();
  </script>
</body>
</html>"""


async def get_pair_page(request: Request) -> HTMLResponse:
    """Serve the device pairing HTML page."""
    return HTMLResponse(content=_PAIR_PAGE_HTML)
