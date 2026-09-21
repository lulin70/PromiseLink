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
    .notice {
      background: #fff3cd; border-radius: 8px; padding: 12px;
      color: #856404; text-align: left;
    }
    .notice code { word-break: break-all; color: #6b4f00; }
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
      let data = null;
      try {
        const res = await fetch('/api/v1/pair/init', { method: 'POST' });
        data = await res.json();
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
          // 2026-09-21：原先这里引用 catch 外的 `data?.gateway_url`，必然抛
          // ReferenceError，导致"无法连接网关"这句提示永远渲染不出来 —— 用户
          // 只看到卡住的转圈。data 已提到 try 外，异常时也能给出可诊断信息。
          showError('无法连接网关，请检查网络连接后刷新页面重试。<br>网关地址：'
            + ((data && data.gateway_url) || 'gateway.promiselink.cn'));
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
          } else if (data.status === 'rejected') {
            // ②（2026-09-21）：上一次激活留下的终态（凭据被网关拒绝）也要显示，
            // 否则用户会一直盯着"请扫码"，而问题其实在许可证本身。
            clearInterval(pollTimer);
            showRejected(data.rejected_kind);
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
        <div class="hint">正在与网关确认激活结果，请勿关闭本页面…</div>
      `;
      try {
        const res = await fetch('/api/v1/pair/activate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ license_key: licenseKey }),
        });
        const data = await res.json();
        if (!data.success) {
          showError('激活失败：' + (data.error || '未知错误'));
          return;
        }
      } catch (err) {
        showError('激活请求失败，请刷新页面重试。');
        return;
      }
      // ②（2026-09-21）：`/pair/activate` 的 success 只表示"已写入配置并尝试启动
      // 中继"—— WSS 启动失败时它同样返回 success=true。原先这里直接报"激活成功"，
      // 于是许可证被网关拒绝的用户看到的是成功提示，随后小程序连不上，
      // 售后拿不到任何线索。现在以中继的真实状态为准。
      await waitForRelayOutcome();
    }

    async function waitForRelayOutcome() {
      const deadline = Date.now() + 20000;
      while (Date.now() < deadline) {
        try {
          const res = await fetch('/api/v1/pair/status?code=' + pairCode);
          const data = await res.json();
          if (data.status === 'activated') {
            showSuccess('专业版激活成功，中继已连接！');
            return;
          }
          if (data.status === 'rejected') {
            showRejected(data.rejected_kind);
            return;
          }
        } catch (err) {
          // 网络抖动：继续等待
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
      showNotConnected();
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
        <div class="hint">配对码有效期 5 分钟。请重新生成后再扫码。</div>
        <button class="btn" onclick="initPair()">重新生成</button>
      `;
    }

    function showRejected(kind) {
      // ②（2026-09-21）：三类归因各给一条下一步动作。与"配对码已过期"在语义
      // （凭据被拒 vs 有效期到）与视觉（本页为红色 ✗，过期页为中性 ↻）上区分开。
      const guides = {
        not_found: '网关没有找到这把许可证。请在小程序「我的 → 专业版激活」确认账号已开通专业版，再回到本页重新配对。',
        occupied: '这把许可证已绑定到其他账号或设备。请在「我的 → 专业版激活」中先解绑原设备；如需协助请联系客服。',
        invalid: '这把许可证当前不可用（可能已过期、被停用或已退还）。请在「我的 → 专业版激活」中确认许可证状态，或联系客服。',
      };
      document.getElementById('content').innerHTML = `
        <div class="status-icon error">&#10007;</div>
        <div class="status-text error">许可证未能激活</div>
        <div class="hint notice">${guides[kind] || guides.invalid}</div>
        <div class="hint">本页提示来自网关返回的原因，未包含许可证内容。若确认无误，请把本页截图发给客服。</div>
        <button class="btn" onclick="initPair()">重新生成配对码</button>
      `;
    }

    function showNotConnected() {
      document.getElementById('content').innerHTML = `
        <div class="status-icon error">&#8635;</div>
        <div class="status-text">激活已提交，但中继尚未连上</div>
        <div class="hint notice">
          可能是网络较慢，也可能是网关侧未接受该许可证。可点击下方按钮重试。<br>
          若反复出现，请把本页截图发给客服，并附上诊断地址：
          <code>http://localhost:8000/api/v1/health</code>
        </div>
        <button class="btn" onclick="initPair()">重新尝试</button>
      `;
    }

    initPair();
  </script>
</body>
</html>"""


async def get_pair_page(request: Request) -> HTMLResponse:
    """Serve the device pairing HTML page."""
    return HTMLResponse(content=_PAIR_PAGE_HTML)
