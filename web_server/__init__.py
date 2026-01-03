import base64
import io
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from traceback import format_exception

from PySide6.QtCore import QThread

import app_state
import qrcode
from models.log import get_logger
from models.states import HttpSignalEmitter


class HttpServerWorker(QThread):
    httpd: HTTPServer

    def __init__(self, host="localhost", port=8080, *,
                 username: str | None = None, password: str | None = None):
        super().__init__()
        self.host = host
        self.port = port
        # Simple credential gate for the web endpoint
        self.username = username or os.environ.get("STARTLIVE_WEB_USERNAME",
                                                   "startlive")
        self.password = password or os.environ.get("STARTLIVE_WEB_PASSWORD",
                                                   "startlive")
        self._tokens: set[str] = set()
        self.logger = get_logger(self.__class__.__name__)
        self.signals = HttpSignalEmitter()
        self._index_html = self._build_index_page()
        self._qr_version = 0  # bump to invalidate cached QR when refreshed

    def run(self):
        try:
            handler = self.make_handler()
            self.httpd = HTTPServer((self.host, self.port), handler)
            # Provide qr_version state for handlers
            self.httpd.qr_version = self._qr_version
            self.logger.info(
                f"HTTP Server running on http://{self.host}:{self.port}")
            self.httpd.serve_forever()
        except Exception as e:
            self.logger.error(f"HTTP Server failed to start")
            self.logger.error(
                format_exception(type(e), e, e.__traceback__))
            self.signals.exception.emit(e)

    def _build_index_page(self) -> str:
        return """<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>StartLive Remote</title>
  <style>
    :root {
      --card: #0f172a;
      --accent: #22c55e;
      --accent-dark: #16a34a;
      --surface: #111827;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --danger: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at 20% 20%, #0ea5e9 0, transparent 35%),
                  radial-gradient(circle at 80% 0%, #22c55e 0, transparent 30%),
                  radial-gradient(circle at 50% 80%, #6366f1 0, transparent 40%),
                  #020617;
      color: var(--text);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 32px 16px;
    }
    .card {
      width: min(960px, 100%);
      background: linear-gradient(135deg, rgba(17,24,39,0.9), rgba(17,24,39,0.7));
      border: 1px solid rgba(148,163,184,0.2);
      border-radius: 18px;
      padding: 28px;
      box-shadow: 0 20px 70px rgba(0,0,0,0.45);
      backdrop-filter: blur(8px);
    }
    h1 {
      margin: 0 0 8px 0;
      font-size: 28px;
      letter-spacing: 0.4px;
    }
    p.muted { color: var(--muted); margin: 0 0 18px 0; }
    form {
      display: flex;
      flex-direction: column;
      gap: 14px;
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin-bottom: 6px;
    }
    input {
      width: 100%;
      padding: 12px 12px;
      border-radius: 10px;
      border: 1px solid rgba(148,163,184,0.3);
      background: rgba(15,23,42,0.8);
      color: var(--text);
      outline: none;
      transition: border 0.15s ease, box-shadow 0.15s ease;
    }
    input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(34,197,94,0.15);
    }
    button {
      border: none;
      border-radius: 10px;
      padding: 12px 16px;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.1s ease, box-shadow 0.2s ease, background 0.2s ease;
      color: #0b1224;
      background: linear-gradient(135deg, var(--accent), var(--accent-dark));
      box-shadow: 0 10px 30px rgba(34,197,94,0.35);
    }
    button:hover { transform: translateY(-1px); }
    button:disabled {
      opacity: 0.45;
      cursor: not-allowed;
      transform: none;
      box-shadow: none;
    }
    .btn {
      position: relative;
    }
    .btn.loading {
      pointer-events: none;
    }
    .btn.loading::after {
      content: "";
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255,255,255,0.6);
      border-left-color: transparent;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      position: absolute;
      right: 12px;
      top: 50%;
      transform: translateY(-50%);
    }
    @keyframes spin { to { transform: translateY(-50%) rotate(360deg); } }
    .controls {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 10px;
    }
    .panel {
      border: 1px solid rgba(148,163,184,0.2);
      border-radius: 12px;
      padding: 14px;
      background: rgba(17,24,39,0.7);
    }
    .panel + .panel { margin-top: 16px; }
    .panel h2 {
      margin: 0 0 8px 0;
      font-size: 16px;
      color: var(--muted);
      letter-spacing: 0.3px;
    }
    .kv { display: flex; gap: 10px; align-items: center; margin: 6px 0; }
    .kv span { width: 110px; color: var(--muted); font-size: 13px; }
    .kv code,
    .kv .kv-field { flex: 1; }
    .kv code {
      display: flex;
      align-items: center;
      min-height: 42px;
    }
    .kv .kv-field {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .kv .kv-field input {
      flex: 1;
    }
    code {
      background: rgba(15,23,42,0.9);
      border: 1px solid rgba(148,163,184,0.2);
      padding: 10px 12px;
      border-radius: 10px;
      display: block;
      width: 100%;
      overflow-wrap: anywhere;
      color: var(--text);
    }
    .flex { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .qr-box {
      width: 220px;
      height: 220px;
      border-radius: 14px;
      border: 1px dashed rgba(148,163,184,0.4);
      display: grid;
      place-items: center;
      background: rgba(15,23,42,0.6);
      position: relative;
    }
    .qr-box img { max-width: 200px; max-height: 200px; border-radius: 12px; }
    .qr-overlay {
      position: absolute;
      inset: 0;
      border-radius: 12px;
      background: rgba(2,6,23,0.65);
      color: var(--text);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 6px;
      backdrop-filter: blur(3px);
      cursor: pointer;
    }
    .qr-overlay svg { width: 20px; height: 20px; fill: var(--text); opacity: 0.85; }
    .blurred { filter: blur(2px); }
    .inline-controls { display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }
    .inline-controls select {
      flex: 1;
      border-radius: 10px;
      border: 1px solid rgba(148,163,184,0.35);
      background: rgba(15,23,42,0.6);
      color: var(--text);
      padding: 8px 12px;
      appearance: none;
      -webkit-appearance: none;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    .inline-controls select:hover {
      border-color: var(--accent);
      color: var(--accent);
    }
    .inline-controls select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(34,197,94,0.15);
      outline: none;
    }
    .pill {
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(148,163,184,0.12);
      color: var(--muted);
      font-size: 12px;
    }
    .btn, .copy-btn {
      border-radius: 8px;
      border: 1px solid rgba(148,163,184,0.35);
      background: rgba(15,23,42,0.6);
      color: var(--text);
      font-size: 12px;
      padding: 8px 14px;
      cursor: pointer;
      transition: border-color 0.15s ease, color 0.15s ease, background 0.2s ease;
      box-shadow: none;
    }
    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }
    .btn:hover, .copy-btn:hover {
      border-color: var(--accent);
      color: var(--accent);
    }
    .hidden { display: none !important; }
    .face-panel {
      display: flex;
      gap: 16px;
      align-items: center;
      padding: 12px;
      margin: 6px 0 4px 0;
      border-radius: 12px;
      border: 1px solid rgba(148,163,184,0.25);
      background: rgba(15,23,42,0.75);
    }
    .face-panel img {
      width: 170px;
      height: 170px;
      border-radius: 12px;
      background: rgba(2,6,23,0.55);
      padding: 10px;
      border: 1px dashed rgba(148,163,184,0.4);
    }
    .face-panel .face-panel-text {
      font-size: 14px;
      color: var(--muted);
      line-height: 1.5;
    }
    .face-panel .face-panel-text strong {
      color: var(--danger);
      font-size: 15px;
      display: block;
      margin-bottom: 6px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>StartLive Remote Panel</h1>
    <p class="muted" id="intro-text">Login first, then send Start/Stop Live and read the stream address/key.</p>
    <form id="login-form">
      <div>
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" placeholder="username" required />
      </div>
      <div>
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" placeholder="password" required />
      </div>
      <div>
        <button type="submit" id="login-btn" class="btn">Login</button>
      </div>
    </form>
    <div id="authed-area" class="hidden">
      <div class="panel">
        <h2>B站账号</h2>
        <div class="kv hidden" id="current-user-row">
          <span>当前账号</span>
          <code id="bili-user">-</code>
        </div>
        <div class="kv hidden" id="room-edit-row">
          <span>房间标题</span>
          <div class="kv-field">
            <input id="room-title-input" placeholder="输入新的房间名" />
            <button class="btn" id="room-title-btn">保存</button>
          </div>
        </div>
        <div class="flex">
          <div class="qr-box hidden" id="qr-block">
            <img id="qr-img" alt="扫码登录" />
            <div class="qr-overlay hidden" id="qr-overlay" title="点击刷新二维码">
              <div>已失效</div>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 5V2L8 6l4 4V7c2.76 0 5 2.24 5 5a5 5 0 0 1-5 5 5 5 0 0 1-4.9-4H5.9A6.1 6.1 0 0 0 12 19.1 6.1 6.1 0 0 0 18.1 13 6.1 6.1 0 0 0 12 6.9Z"/>
              </svg>
            </div>
          </div>
          <div style="flex:1; min-width: 200px;" id="qr-info"></div>
        </div>
        <div class="controls hidden" id="logout-row" style="justify-content:flex-start; margin-top:16px;">
          <button class="btn hidden" id="bili-logout-btn" disabled>退出登录</button>
        </div>
      </div>
      <div class="panel hidden" id="area-panel">
        <h2>分区选择</h2>
        <div class="inline-controls" style="align-items:center;">
          <label style="color:var(--muted);">父分区</label>
          <select id="area-parent" style="flex:1;"></select>
          <label style="color:var(--muted);">子分区</label>
          <select id="area-child" style="flex:1;"></select>
        </div>
      </div>
      <div class="panel hidden" id="stream-panel">
        <h2>Stream Info</h2>
        <div class="kv">
          <span>Stream URL</span>
          <div class="kv-field">
            <code id="stream-addr">-</code>
            <button type="button" class="copy-btn" data-copy-target="stream-addr">复制</button>
          </div>
        </div>
        <div class="kv">
          <span>Stream Key</span>
          <div class="kv-field">
            <code id="stream-key">-</code>
            <button type="button" class="copy-btn" data-copy-target="stream-key">复制</button>
          </div>
        </div>
        <div class="face-panel hidden" id="face-panel">
          <img id="face-img" alt="人脸认证二维码" />
          <div class="face-panel-text">
            <strong>目标分区需要人脸验证</strong>
            <div>请使用哔哩哔哩 APP 扫描二维码进行身份验证，完成后再点击 Start Live。</div>
          </div>
        </div>
        <div class="controls hidden" id="controls-row" style="margin-top: 12px;">
          <button class="btn" id="start-btn" disabled>Start Live</button>
          <button class="btn" id="stop-btn" disabled>Stop Live</button>
        </div>
      </div>
    </div>
  </div>
<script>
(() => {
  const el = {
    form: document.getElementById("login-form"),
    loginForm: document.getElementById("login-form"),
    startBtn: document.getElementById("start-btn"),
    stopBtn: document.getElementById("stop-btn"),
    addrEl: document.getElementById("stream-addr"),
    keyEl: document.getElementById("stream-key"),
    loginBtn: document.getElementById("login-btn"),
    biliLogoutBtn: document.getElementById("bili-logout-btn"),
    biliUser: document.getElementById("bili-user"),
    qrImg: document.getElementById("qr-img"),
    qrBlock: document.getElementById("qr-block"),
    qrOverlay: document.getElementById("qr-overlay"),
    authedArea: document.getElementById("authed-area"),
    controlsRow: document.getElementById("controls-row"),
    currentUserRow: document.getElementById("current-user-row"),
    qrInfo: document.getElementById("qr-info"),
    streamPanel: document.getElementById("stream-panel"),
    facePanel: document.getElementById("face-panel"),
    faceImg: document.getElementById("face-img"),
    roomEditRow: document.getElementById("room-edit-row"),
    roomTitleInput: document.getElementById("room-title-input"),
    roomTitleBtn: document.getElementById("room-title-btn"),
    areaPanel: document.getElementById("area-panel"),
    areaParent: document.getElementById("area-parent"),
    areaChild: document.getElementById("area-child"),
    logoutRow: document.getElementById("logout-row"),
    qrRefreshBtn: document.getElementById("qr-refresh-btn"),
    copyButtons: document.querySelectorAll("[data-copy-target]"),
    introText: document.getElementById("intro-text"),
  };

  const state = {
    token: localStorage.getItem("startlive_token") || "",
    lastQrVersion: 0,
    qrPollTimer: null,
    qrReady: false,
    biliLoggedIn: false,
    faceRequired: false,
    faceQueryArmed: false,
    liveActive: false,
    areasLoaded: false,
    areaRetry: 0,
    areaOptionsCache: {},
    areaSaving: false,
    loginPending: false,
    statusRetryTimer: null,
    userReady: false,
    titleReady: false,
  };

  const report = (msg, isError = false) => {
    if (!msg) return;
    if (isError) {
      console.error(msg);
    } else {
      console.log(msg);
    }
  };

  const copyToClipboard = (text) => {
    if (!text) return Promise.reject(new Error("无可复制内容"));
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    try {
      document.execCommand("copy");
      document.body.removeChild(textarea);
      return Promise.resolve();
    } catch (err) {
      document.body.removeChild(textarea);
      return Promise.reject(err);
    }
  };

  const normalizeUser = (value) => (value || "").replace(/^cookies\\|/i, "");

  const setPending = (btn, pending) => {
    if (!btn) return;
    if (btn.dataset.pending === "true" && pending) return;
    if (pending) {
      btn.dataset.pending = "true";
      btn.classList.add("loading");
      btn.disabled = true;
    } else {
      btn.dataset.pending = "false";
      btn.classList.remove("loading");
      if (btn.dataset.keepDisabled !== "true") {
        btn.disabled = false;
      }
    }
  };

  const setToken = (token) => {
    state.token = token || "";
    if (state.token) {
      localStorage.setItem("startlive_token", state.token);
    } else {
      localStorage.removeItem("startlive_token");
    }
  };

  const stopStatusRetry = () => {
    if (state.statusRetryTimer) {
      clearInterval(state.statusRetryTimer);
      state.statusRetryTimer = null;
    }
  };

  const ensureStatusReady = () => {
    if (state.statusRetryTimer) return;
    state.statusRetryTimer = setInterval(() => {
      if (!state.biliLoggedIn) {
        stopStatusRetry();
        return;
      }
      if (state.userReady && state.titleReady) {
        stopStatusRetry();
        return;
      }
      loadBiliStatus();
    }, 1000);
  };

  const toggleWebAuthed = (authed) => {
    if (el.authedArea) el.authedArea.classList.toggle("hidden", !authed);
    if (el.loginForm) el.loginForm.classList.toggle("hidden", authed);
    if (el.introText) el.introText.classList.toggle("hidden", authed);
    if (el.startBtn) el.startBtn.disabled = !authed;
    if (el.stopBtn) el.stopBtn.disabled = !authed;
    if (el.biliLogoutBtn) el.biliLogoutBtn.disabled = !authed;
  };

  const updateLiveUI = () => {
    const logged = state.biliLoggedIn;
    const active = state.liveActive;
    if (el.controlsRow) el.controlsRow.classList.toggle("hidden", !logged);
    if (el.logoutRow) el.logoutRow.classList.toggle("hidden", !logged);
    if (el.streamPanel) el.streamPanel.classList.toggle("hidden", !logged);
    if (el.areaPanel) el.areaPanel.classList.toggle("hidden", !logged);
    if (el.roomEditRow) el.roomEditRow.classList.toggle("hidden", !logged);
    if (el.currentUserRow) el.currentUserRow.classList.toggle("hidden", !logged);
    if (el.biliLogoutBtn) el.biliLogoutBtn.classList.toggle("hidden", !logged);
    if (el.startBtn) {
      el.startBtn.classList.toggle("hidden", active);
      el.startBtn.disabled = !logged || active;
    }
    if (el.stopBtn) {
      el.stopBtn.classList.toggle("hidden", !active);
      el.stopBtn.disabled = !logged || !active;
    }
    if (el.roomTitleBtn) el.roomTitleBtn.disabled = !logged;
    if ((!logged || !active) && el.addrEl && el.keyEl) {
      el.addrEl.textContent = active ? el.addrEl.textContent : "-";
      el.keyEl.textContent = active ? el.keyEl.textContent : "-";
    }
  };

  const hideFaceQr = () => {
    state.faceRequired = false;
    if (el.facePanel) el.facePanel.classList.add("hidden");
    if (el.faceImg) el.faceImg.removeAttribute("src");
  };

  const showFaceQr = (payload) => {
    if (!payload || !el.facePanel || !el.faceImg) {
      hideFaceQr();
      return;
    }
    state.faceRequired = true;
    if (payload.startsWith("data:") || payload.startsWith("http")) {
      el.faceImg.src = payload;
    } else {
      el.faceImg.src = "data:image/png;base64," + payload;
    }
    el.facePanel.classList.remove("hidden");
  };

  const resetBiliState = () => {
    state.biliLoggedIn = false;
    state.liveActive = false;
    state.faceQueryArmed = false;
    state.areasLoaded = false;
    state.areaRetry = 0;
    state.userReady = false;
    state.titleReady = false;
    state.areaOptionsCache = {};
    state.lastQrVersion = 0;
    if (state.qrPollTimer) {
      clearInterval(state.qrPollTimer);
      state.qrPollTimer = null;
    }
    stopStatusRetry();
    el.addrEl.textContent = "-";
    el.keyEl.textContent = "-";
    if (el.areaParent) el.areaParent.innerHTML = "";
    if (el.areaChild) {
      el.areaChild.innerHTML = "";
      el.areaChild.disabled = true;
    }
    hideFaceQr();
    updateLiveUI();
  };

  const handleAuthResponse = (res) => {
    if (res.status === 401) {
      setToken("");
      toggleWebAuthed(false);
      resetBiliState();
      throw new Error("Login required");
    }
    return res;
  };

  const authedFetch = (url, options = {}) => {
    if (!state.token) {
      return Promise.reject(new Error("Login required"));
    }
    const headers = Object.assign({}, options.headers || {}, {
      "Authorization": "Bearer " + state.token
    });
    return fetch(url, Object.assign({}, options, { headers })).then(handleAuthResponse);
  };

  const updateInfo = () => {
    if (!state.token) return Promise.resolve();
    return authedFetch("/api/streamInfo")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "Unable to load stream info");
        el.addrEl.textContent = data.stream_addr || "-";
        el.keyEl.textContent = data.stream_key || "-";
        const facePayload = data.face_qr || data.face_url || "";
        if (state.faceQueryArmed && facePayload) {
          showFaceQr(facePayload);
        } else {
          hideFaceQr();
        }
        state.liveActive = Boolean(
          data.live_status ||
          ((data.stream_addr || "") && (data.stream_key || ""))
        );
        updateLiveUI();
      })
      .catch(() => {});
  };

  const stopQrPoll = () => {
    if (state.qrPollTimer) {
      clearInterval(state.qrPollTimer);
      state.qrPollTimer = null;
    }
  };

  const startQrPoll = () => {
    if (state.qrPollTimer) return;
    state.qrReady = false;
    state.qrPollTimer = setInterval(() => {
      if (state.biliLoggedIn) {
        stopQrPoll();
        return;
      }
      loadBiliStatus();
    }, 800);
    loadBiliStatus();
  };

  const renderQr = (data, showOverlay) => {
    if (!el.qrImg) return;
    if (data.qr_png) {
      const shouldUpdate = (data.qr_version !== undefined && data.qr_version !== state.lastQrVersion) || !el.qrImg.src;
      if (shouldUpdate) {
        el.qrImg.src = "data:image/png;base64," + data.qr_png;
        state.lastQrVersion = data.qr_version || 0;
      }
      state.qrReady = true;
      el.qrImg.style.visibility = "visible";
    } else {
      if (state.biliLoggedIn) {
        el.qrImg.src = "";
        el.qrImg.style.visibility = "hidden";
        state.qrReady = false;
      } else {
        el.qrImg.style.visibility = el.qrImg.src ? "visible" : "hidden";
      }
    }
    el.qrImg.classList.toggle("blurred", showOverlay);
  };

  const renderBili = (data) => {
    const status = data.scan_status || {};
    const scanned = !!status.scanned;
    const expired = !!status.expired || !!status.timeout;

    const usernames = data.usernames || {};
    const hasFormattedUser = Object.values(usernames || {}).some(
      (v) => typeof v === "string" && v.includes("（") && v.includes("）")
    );
    const baseUser = scanned
      ? normalizeUser(
          data.display_user_full ||
          data.display_user ||
          data.nickname ||
          data.current_user ||
          Object.values(usernames).find(Boolean) ||
          ""
        ) || "-"
      : "-";
    let displayUser = baseUser;
    if (scanned && data.current_uid) {
      const alreadyFormatted = /（.+?）$/.test(baseUser) || baseUser.includes(`（${data.current_uid}）`);
      if (!alreadyFormatted) {
        displayUser = `${baseUser}（${data.current_uid}）`;
      }
    }
    if (!scanned) {
      displayUser = "-";
    }
    el.biliUser.textContent = displayUser;
    state.userReady = scanned && hasFormattedUser;

    state.biliLoggedIn = scanned;
    if (!scanned) {
      resetBiliState();
    } else if (el.roomTitleInput) {
      if (data.room_title) {
        el.roomTitleInput.value = data.room_title;
        state.titleReady = true;
      }
    }

    if (el.qrBlock) el.qrBlock.classList.toggle("hidden", scanned);
    if (el.qrInfo) el.qrInfo.classList.add("hidden");
    const showOverlay = !scanned && expired;
    if (el.qrOverlay) el.qrOverlay.classList.toggle("hidden", !showOverlay);

    if (scanned && !state.areasLoaded) {
      loadAreas();
    }

    renderQr(data, showOverlay);

    if (scanned && (!state.userReady || !state.titleReady)) {
      ensureStatusReady();
    } else if (scanned) {
      stopStatusRetry();
    }

    if (scanned) {
      stopQrPoll();
    } else {
      startQrPoll();
    }
    updateLiveUI();
  };

  const loadBiliStatus = () => {
    if (!state.token) return Promise.resolve();
    return authedFetch("/api/bili/status")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "无法获取B站状态");
        renderBili(data);
      })
      .catch((err) => report(err.message, true));
  };

  const startBiliLogin = () => {
    if (state.loginPending) return;
    state.loginPending = true;
    setPending(el.qrRefreshBtn, true);
    if (el.qrImg) {
      el.qrImg.style.visibility = "hidden";
      el.qrImg.classList.remove("blurred");
    }
    authedFetch("/api/bili/login", { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "二维码获取失败");
        renderBili(data);
        startQrPoll();
      })
      .catch((err) => report(err.message, true))
      .finally(() => {
        state.loginPending = false;
        setPending(el.qrRefreshBtn, false);
      });
  };

  const saveRoomTitle = () => {
    if (!el.roomTitleInput || !el.roomTitleBtn) return;
    if (el.roomTitleBtn.dataset.pending === "true") return;
    const title = (el.roomTitleInput.value || "").trim();
    if (!title) return;
    setPending(el.roomTitleBtn, true);
    authedFetch("/api/setTitle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title })
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "更新失败");
        report("房间标题已更新");
      })
      .catch((err) => report(err.message, true))
      .finally(() => setPending(el.roomTitleBtn, false));
  };

  const fillAreas = (data) => {
    if (!el.areaParent || !el.areaChild) return;
    state.areaOptionsCache = data.area_options || {};
    const parents = data.parents || [];
    const currentParent = data.current_parent || "";
    const currentChild = data.current_child || "";
    const firstRealParent = parents.find((p) => p && p !== "请选择") || "";
    el.areaParent.innerHTML = "";
    el.areaChild.innerHTML = "";
    parents.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = p;
      el.areaParent.appendChild(opt);
    });
    if (currentParent && parents.includes(currentParent)) {
      el.areaParent.value = currentParent;
    } else if (firstRealParent) {
      el.areaParent.value = firstRealParent;
    }
    const options = (state.areaOptionsCache && state.areaOptionsCache[el.areaParent.value]) || [];
    options.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      el.areaChild.appendChild(opt);
    });
    let hasSelection = false;
    if (currentChild && options.includes(currentChild)) {
      el.areaChild.value = currentChild;
      hasSelection = true;
    } else if (currentParent && !el.areaChild.value && options.length > 0) {
      el.areaChild.value = options[0];
    }
    el.areaChild.disabled = options.length === 0;
    return {
      hasOptions: options.length > 0 || parents.length > 1,
      hasSelection: hasSelection && Boolean(currentParent),
    };
  };

  const loadAreas = () => {
    if (!state.token) return Promise.resolve();
    return authedFetch("/api/areas")
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "分区获取失败");
        const result = fillAreas(data) || { hasOptions: false, hasSelection: false };
        const hasParents = Array.isArray(data.parents) && data.parents.length > 1;
        state.areasLoaded = (result.hasOptions || hasParents) && result.hasSelection;
        if (!state.areasLoaded && state.areaRetry < 5) {
          state.areaRetry += 1;
          setTimeout(loadAreas, 800);
        } else {
          state.areaRetry = 0;
        }
      })
      .catch((err) => report(err.message, true));
  };

  const refreshChildOptions = () => {
    if (!el.areaParent || !el.areaChild) return;
    const parent = el.areaParent.value;
    const options = (state.areaOptionsCache && state.areaOptionsCache[parent]) || [];
    el.areaChild.innerHTML = "";
    options.forEach((c) => {
      const opt = document.createElement("option");
      opt.value = c;
      opt.textContent = c;
      el.areaChild.appendChild(opt);
    });
    el.areaChild.disabled = options.length === 0;
  };

  const saveArea = () => {
    if (state.areaSaving) return Promise.resolve();
    if (!el.areaParent || !el.areaChild) return Promise.resolve();
    const parent = el.areaParent.value;
    const child = el.areaChild.value;
    if (!parent || !child) return Promise.resolve();
    state.areaSaving = true;
    return authedFetch("/api/setArea", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent, child })
    })
      .then((r) => r.json())
      .then((data) => {
        if (!data.ok) throw new Error(data.message || "分区保存失败");
        report("分区已更新");
      })
      .catch((err) => report(err.message, true))
      .finally(() => {
        state.areaSaving = false;
      });
  };

  if (el.roomTitleBtn) {
    el.roomTitleBtn.addEventListener("click", saveRoomTitle);
  }
  if (el.roomTitleInput) {
    el.roomTitleInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        saveRoomTitle();
      }
    });
  }
  if (el.areaParent) {
    el.areaParent.addEventListener("change", () => {
      refreshChildOptions();
      saveArea();
    });
  }
  if (el.areaChild) {
    el.areaChild.addEventListener("change", () => saveArea());
  }
  if (el.qrOverlay) {
    el.qrOverlay.addEventListener("click", () => startBiliLogin());
  }
  if (el.qrRefreshBtn) {
    el.qrRefreshBtn.addEventListener("click", () => startBiliLogin());
  }
  if (el.copyButtons && el.copyButtons.length) {
    el.copyButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.getAttribute("data-copy-target");
        const target = targetId ? document.getElementById(targetId) : null;
        const text = target ? (target.textContent || "").trim() : "";
        copyToClipboard(text)
          .then(() => report("已复制到剪贴板"))
          .catch(() => report("复制失败或没有可复制内容", true));
      });
    });
  }

  if (el.biliLogoutBtn) {
    el.biliLogoutBtn.addEventListener("click", () => {
      setPending(el.biliLogoutBtn, true);
      authedFetch("/api/bili/logout", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) throw new Error(data.message || "退出失败");
          report("已退出B站账号");
          resetBiliState();
          renderBili({
            ok: true,
            scan_status: { scanned: false },
            qr_url: null,
            qr_png: null,
            usernames: {},
            room_title: "",
          });
          startBiliLogin();
        })
        .catch((err) => report(err.message, true))
        .finally(() => setPending(el.biliLogoutBtn, false));
    });
  }

  if (el.form) {
    el.form.addEventListener("submit", (e) => {
      e.preventDefault();
      setPending(el.loginBtn, true);
      fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value
        })
      })
        .then((r) => r.json())
        .then((data) => {
          if (data.ok && data.token) {
            setToken(data.token);
            toggleWebAuthed(true);
            report("Login successful");
            updateInfo();
            loadBiliStatus();
          } else {
            setToken("");
            toggleWebAuthed(false);
            resetBiliState();
            report(data.message || "Login failed", true);
          }
        })
        .catch(() => {
          report("Login failed", true);
        })
        .finally(() => setPending(el.loginBtn, false));
    });
  }

  if (el.startBtn) {
    el.startBtn.addEventListener("click", () => {
      setPending(el.startBtn, true);
      state.faceQueryArmed = true;
      Promise.resolve()
        .then(() => saveArea())
        .then(() => authedFetch("/api/startLive", { method: "POST" }))
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) throw new Error(data.message || "Start failed");
          report("Start signal sent");
          state.liveActive = true;
          updateLiveUI();
          setTimeout(() => updateInfo(), 1200);
        })
        .catch((err) => {
          state.liveActive = false;
          report(err.message, true);
          updateLiveUI();
        })
        .finally(() => setPending(el.startBtn, false));
    });
  }

  if (el.stopBtn) {
    el.stopBtn.addEventListener("click", () => {
      setPending(el.stopBtn, true);
      authedFetch("/api/stopLive", { method: "POST" })
        .then((r) => r.json())
        .then((data) => {
          if (!data.ok) throw new Error(data.message || "Stop failed");
          report("Stop signal sent");
          state.liveActive = false;
          el.addrEl.textContent = "-";
          el.keyEl.textContent = "-";
          updateLiveUI();
        })
        .catch((err) => report(err.message, true))
        .finally(() => setPending(el.stopBtn, false));
    });
  }

  if (state.token) {
    toggleWebAuthed(true);
    updateInfo();
    loadBiliStatus().then(() => loadAreas());
  } else {
    toggleWebAuthed(false);
    resetBiliState();
  }
})();
</script>
</body>
</html>
"""

    def make_handler(self):
        signals = self.signals
        logger = self.logger
        tokens = self._tokens
        index_html = self._index_html
        expected_user = self.username
        expected_pass = self.password

        class EmitSignalHandler(BaseHTTPRequestHandler):
            triggers: dict[str, str] = {
                "/api/startLive": "startLive",
                "/api/stopLive": "stopLive",
                "/api/bili/login": "startLogin",
                "/api/bili/logout": "logout",
                "/api/setTitle": "setTitle",
                "/api/setArea": "setArea",
            }

            def _send_json(self, payload: dict, code: int = 200,
                           set_cookie: str | None = None):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type",
                                 "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                if set_cookie:
                    self.send_header("Set-Cookie", set_cookie)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    logger.warning("Client closed connection while sending JSON")

            def _send_html(self, html: str, code: int = 200):
                body = html.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except BrokenPipeError:
                    logger.warning("Client closed connection while sending HTML")

            def _parse_json(self) -> dict:
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError:
                    return {}

            def _extract_token(self) -> str:
                auth_header = self.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    return auth_header.removeprefix("Bearer ").strip()
                cookie_header = self.headers.get("Cookie", "")
                for part in cookie_header.split(";"):
                    if "=" not in part:
                        continue
                    key, value = part.strip().split("=", 1)
                    if key == "startlive_token":
                        return value
                return ""

            def _require_auth(self) -> bool:
                token = self._extract_token()
                if token and token in tokens:
                    return True
                self._send_json({"ok": False, "message": "Unauthorized"}, 401)
                return False

            def _bili_status(self):
                def _normalize_user(value: str | None) -> str:
                    if not value:
                        return ""
                    return str(value).replace("cookies|", "")

                scan_status = app_state.scan_status.as_dict()
                scanned = bool(scan_status.get("scanned"))
                qr_url = scan_status.get("qr_url") if not scanned else None
                qr_png_b64 = self._qr_png(qr_url) if qr_url else None

                def _pick_user():
                    names = list(app_state.usernames.values())
                    if names:
                        names = [n for n in names if n]
                    for v in names:
                        if v and "cookies|" not in v:
                            return v
                    for v in names:
                        if v:
                            return v.replace("cookies|", "")
                    if app_state.cookies_dict.get("DedeUserID"):
                        return str(app_state.cookies_dict["DedeUserID"])
                    return None

                current_user = _pick_user() if scanned else None
                idx = getattr(self, "cookie_index", 0)
                nickname = ""
                safe_idx = None
                try:
                    if app_state.usernames:
                        # 优先当前索引，其次任意一个非空昵称
                        if app_state.cookie_indices and 0 <= idx < len(app_state.cookie_indices):
                            safe_idx = idx
                            nickname = app_state.usernames.get(app_state.cookie_indices[idx], "")
                        if not nickname:
                            nickname = next((v for v in app_state.usernames.values() if v), "")
                except Exception:
                    nickname = ""

                current_uid = ""
                try:
                    current_uid = str(app_state.cookies_dict.get("DedeUserID") or "")
                except Exception:
                    current_uid = ""
                display_user = ""
                try:
                    if current_uid:
                        display_user = app_state.usernames.get(f"cookies|{current_uid}", "")
                    if not display_user and safe_idx is not None:
                        key = app_state.cookie_indices[safe_idx]
                        display_user = app_state.usernames.get(key, "")
                except Exception:
                    display_user = ""
                if not display_user:
                    display_user = nickname or current_user or ""
                display_user_full = display_user
                if display_user_full and current_uid:
                    uid_tag = f"（{current_uid}）"
                    if uid_tag not in display_user_full and not (
                            display_user_full.endswith("）") and current_uid in display_user_full):
                        display_user_full = f"{display_user_full}{uid_tag}"

                self._send_json({
                    "ok": True,
                    "scan_status": scan_status,
                    "qr_url": qr_url,
                    "qr_png": qr_png_b64,
                    "usernames": app_state.usernames,
                    "cookie_indices": app_state.cookie_indices,
                    "current_user": _normalize_user(current_user),
                    "nickname": _normalize_user(nickname),
                    "display_user": _normalize_user(display_user),
                    "display_user_full": _normalize_user(display_user_full),
                    "current_uid": current_uid,
                    "room_title": app_state.room_info.get("title") or "",
                    "qr_version": getattr(self.server, "qr_version", 0),
                })

            def _qr_png(self, url: str) -> str | None:
                try:
                    qr = qrcode.QRCode(box_size=4, border=1)
                    qr.add_data(url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    return base64.b64encode(buf.getvalue()).decode("ascii")
                except Exception as e:  # noqa: BLE001
                    logger.error(f"QR generate error: {e}")
                    return None

            def _handle_login(self):
                data = self._parse_json()
                if data.get("username") == expected_user and data.get(
                        "password") == expected_pass:
                    token = secrets.token_urlsafe(32)
                    tokens.add(token)
                    self._send_json(
                        {"ok": True, "token": token},
                        set_cookie=f"startlive_token={token}; Path=/; HttpOnly")
                else:
                    self._send_json({"ok": False,
                                     "message": "Invalid credentials"}, 401)

            def _handle_signal(self, signal_name: str):
                if not self._require_auth():
                    return
                app_state.web_action = True
                logger.info(f"Server received signal {signal_name}")
                getattr(signals, signal_name).emit()
                self._send_json({"ok": True})

            def do_POST(self):
                if self.path == "/api/login":
                    self._handle_login()
                    return
                if self.path == "/api/setTitle":
                    if not self._require_auth():
                        return
                    if not app_state.scan_status.get("scanned"):
                        self._send_json({"ok": False, "message": "未登录B站"}, 400)
                        return
                    data = self._parse_json()
                    title = (data.get("title") or "").strip()
                    if not title:
                        self._send_json({"ok": False, "message": "标题不能为空"}, 400)
                        return
                    app_state.web_action = True
                    app_state.room_info["title"] = title
                    signals.setTitle.emit(title)
                    self._send_json({"ok": True, "room_title": title})
                    return
                if self.path == "/api/setArea":
                    if not self._require_auth():
                        return
                    if not app_state.scan_status.get("scanned"):
                        self._send_json({"ok": False, "message": "未登录B站"}, 400)
                        return
                    data = self._parse_json()
                    parent = (data.get("parent") or "").strip()
                    child = (data.get("child") or "").strip()
                    if parent not in app_state.parent_area:
                        self._send_json({"ok": False, "message": "无效父分区"}, 400)
                        return
                    if parent not in app_state.area_options or child not in app_state.area_options[parent]:
                        self._send_json({"ok": False, "message": "无效子分区"}, 400)
                        return
                    app_state.web_action = True
                    app_state.room_info["parent_area"] = parent
                    app_state.room_info["area"] = child
                    signals.setArea.emit(parent, child)
                    self._send_json({"ok": True, "parent": parent, "child": child})
                    return
                if self.path in self.triggers and hasattr(
                        signals, self.triggers[self.path]):
                    # start/stop live and bili login/logout
                    if self.triggers[self.path] == "startLogin":
                        if not self._require_auth():
                            return
                        app_state.web_action = True
                        self._handle_signal("startLogin")
                        self.server.qr_version = getattr(self.server, "qr_version", 0) + 1
                        self._bili_status()
                        return
                    if self.triggers[self.path] == "logout":
                        if not self._require_auth():
                            return
                        app_state.web_action = True
                        getattr(signals, "logout").emit()
                        # 立即清空 B 站登录态，让前端不必等下一轮轮询
                        try:
                            app_state.scan_settings_default()
                            app_state.room_info_default()
                            app_state.stream_status_default()
                            app_state.cookies_dict.clear()
                            app_state.usernames.clear()
                        except Exception as e:  # noqa: BLE001
                            logger.warning(f"Reset bili state failed: {e}")
                        # 返回最新状态（未登录），前端可直接切换到扫码界面
                        self._bili_status()
                        return
                    if not self._require_auth():
                        return
                    self._handle_signal(self.triggers[self.path])
                    return
                self._send_json({"ok": False, "message": "Not Found"}, 404)

            def do_GET(self):
                if self.path == "/":
                    self._send_html(index_html)
                    return
                if self.path == "/api/streamInfo":
                    if not self._require_auth():
                        return
                    face_url = app_state.stream_status.get("face_url")
                    face_required = bool(
                        app_state.stream_status.get("required_face") and face_url)
                    face_qr_png = self._qr_png(face_url) if face_required else None
                    if face_required:
                        app_state.stream_status["required_face"] = False
                    self._send_json({
                        "ok": True,
                        "stream_addr": app_state.stream_status["stream_addr"],
                        "stream_key": app_state.stream_status["stream_key"],
                        "live_status": app_state.stream_status["live_status"],
                        "requires_face": face_required,
                        "face_url": face_url if face_required else None,
                        "face_qr": face_qr_png
                    })
                    return
                if self.path == "/api/areas":
                    if not self._require_auth():
                        return
                    if not app_state.scan_status.get("scanned"):
                        self._send_json({"ok": False, "message": "未登录B站"}, 400)
                        return
                    current_parent = app_state.room_info.get("parent_area", "")
                    current_child = app_state.room_info.get("area", "")
                    self._send_json({
                        "ok": True,
                        "parents": app_state.parent_area,
                        "area_options": app_state.area_options,
                        "current_parent": current_parent,
                        "current_child": current_child,
                    })
                    return
                if self.path == "/api/bili/status":
                    if not self._require_auth():
                        return
                    self._bili_status()
                    return
                self._send_json({"ok": False, "message": "Not Found"}, 404)

            def log_message(self, format_s, *args):
                logger.info(format_s % args)

        return EmitSignalHandler

    @property
    def qr_version(self) -> int:
        return getattr(self, "_qr_version", 0)

    @qr_version.setter
    def qr_version(self, value: int):
        self._qr_version = value
        if hasattr(self, "httpd"):
            try:
                setattr(self.httpd, "qr_version", value)
            except Exception:
                pass

    def stop(self):
        if hasattr(self, 'httpd'):
            self.httpd.shutdown()
            self.httpd.server_close()
