// ==UserScript==
// @name         B站下载助手（BiliDrown）
// @namespace    https://github.com/Exsshly
// @version      0.0.5
// @description  该脚本由B站解析助手拓展改造，作为其油猴替代版，支持视频音频合并下载、仅下载音频以及提取封面。首次下载需要加载ffmpeg核心模块，后续会被浏览器缓存以加快下载速度。请在视频页面等待解析完成后再进行下载，解析过程中请勿刷新页面或切换视频，以免导致解析失败。解析失败时可以尝试多点击几次下载按钮，或刷新页面重试。如果持续无法解析，请检查控制台是否有相关错误日志，并反馈给开发者以便修复。该脚本仅供学习和研究使用，请勿用于任何商业用途或侵犯版权的行为。
// @author       Exsshly
// @copyright     2026, Exsshly (https://github.com/Exsshly)
// @license       MIT
// @source        https://github.com/Exsshly/BiliDrown
// @supportURL    https://github.com/Exsshly/BiliDrown/issues
// @match        *://www.bilibili.com/video/*
// @match        *://www.bilibili.com/bangumi/play/*
// @match        *://www.bilibili.com/s/video/*
// @run-at       document-start
// @grant        GM_xmlhttpRequest
// @connect      bilibili.com
// @connect      bilivideo.com
// @connect      *.bilivideo.com
// @connect      i0.hdslb.com
// @connect      i1.hdslb.com
// @connect      i2.hdslb.com
// @connect      i3.hdslb.com
// @connect      i4.hdslb.com
// @connect      *.hdslb.com
// @connect      unpkg.com
// @require      https://unpkg.com/@ffmpeg/ffmpeg@0.12.15/dist/umd/ffmpeg.min.js
// @require      https://unpkg.com/@ffmpeg/core@0.12.10/dist/umd/core.min.js
// @require      https://unpkg.com/@ffmpeg/core-mt@0.12.10/dist/umd/core-mt.min.js
// @noframes
// @downloadURL https://update.greasyfork.org/scripts/578205/B%E7%AB%99%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B%EF%BC%88BiliDrown%EF%BC%89.user.js
// @updateURL https://update.greasyfork.org/scripts/578205/B%E7%AB%99%E4%B8%8B%E8%BD%BD%E5%8A%A9%E6%89%8B%EF%BC%88BiliDrown%EF%BC%89.meta.js
// ==/UserScript==

(() => {
  'use strict';

  const SCRIPT_ID = 'bilibili-helper-tm-marker';
  const PANEL_ID = 'bilibili-helper-tm-panel';
  const HOST_ID = 'bilibili-helper-host';
  const PLAYURL_API = '//api.bilibili.com/x/player/wbi/playurl';
  const PANEL_COLLAPSED_STORAGE_KEY = 'bilibili-helper-tm-panel-collapsed';
  const FFMPEG_VERSION = '0.12.15';
  const FFMPEG_CORE_VERSION = '0.12.10';
  const FFMPEG_MT_CORE_VERSION = '0.12.10';
  const FFMPEG_BASE_URL = `https://unpkg.com/@ffmpeg/ffmpeg@${FFMPEG_VERSION}/dist/umd`;
  const FFMPEG_CORE_BASE_URL = `https://unpkg.com/@ffmpeg/core@${FFMPEG_CORE_VERSION}/dist/umd`;
  const FFMPEG_MT_CORE_BASE_URL = `https://unpkg.com/@ffmpeg/core-mt@${FFMPEG_MT_CORE_VERSION}/dist/umd`;

  const QUALITY_LABELS = {
    16: '360P 流畅',
    32: '480P 标清',
    64: '720P 准高清',
    80: '1080P 高清',
    112: '1080P 高码率',
    120: '4K 超高清',
    125: 'HDR 真彩',
  };

  const state = {
    installed: false,
    currentUrl: location.href,
    currentPageKey: '',
    currentPayloadKey: '',
    currentPayload: null,
    currentMeta: null,
    routeTimer: 0,
    messageHooked: false,
    pageHookInjected: false,
    activeTaskId: 0,
    ffmpegPromise: null,
    ffmpegModuleUrl: '',
    ffmpegCoreUrl: '',
    ffmpegWorkerUrl: '',
    ffmpegWasmUrl: '',
    ffmpegWorkerLoadUrl: '',
    ffmpegModuleCleanupBound: false,
  };

  if (location.href.includes('bilibili.com/s/video/')) {
    location.replace(location.href.replace('/s/', '/'));
    return;
  }

  if (!/\.bilibili\.com$/.test(location.hostname) && location.hostname !== 'bilibili.com' && location.hostname !== 'www.bilibili.com') {
    return;
  }

  installHooks();
  installRouteWatchers();
  scheduleScan();

  function installHooks() {
    if (!state.messageHooked) {
      state.messageHooked = true;
      window.addEventListener('message', event => {
        if (event.source !== window) {
          return;
        }
        const data = event.data;
        if (!data || data.source !== 'bilibili-helper-page-hook' || data.type !== 'playurl') {
          return;
        }
        capturePayload(data.requestUrl || '', data.text || '');
      });
    }

    if (!state.pageHookInjected) {
      state.pageHookInjected = true;
      injectPageHooks();
    }
  }

  function injectPageHooks() {
    const script = document.createElement('script');
    script.id = `${SCRIPT_ID}-page-hook`;
    script.textContent = `(() => {
            if (window.__bilibiliHelperPageHookInstalled) {
                return;
            }
            window.__bilibiliHelperPageHookInstalled = true;
            const source = 'bilibili-helper-page-hook';
            const post = (requestUrl, text) => window.postMessage({ source, type: 'playurl', requestUrl, text }, '*');
            const normalizeRequestUrl = input => {
                if (typeof input === 'string') return input;
                if (input instanceof URL) return input.href;
                if (input && typeof input.url === 'string') return input.url;
                return '';
            };
            const isPlayurlRequest = url => typeof url === 'string' && /\/playurl(?:\?|$)/i.test(url);

            if (typeof window.fetch === 'function') {
                const nativeFetch = window.fetch.bind(window);
                window.fetch = async (...args) => {
                    const response = await nativeFetch(...args);
                    try {
                        const requestUrl = normalizeRequestUrl(args[0]);
                        if (isPlayurlRequest(requestUrl)) {
                            response.clone().text().then(text => post(requestUrl, text)).catch(() => {});
                        }
                    } catch (_) {}
                    return response;
                };
            }

            if (window.XMLHttpRequest) {
                const nativeOpen = XMLHttpRequest.prototype.open;
                const nativeSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.open = function (method, url, ...rest) {
                    this.__bilibiliHelperUrl = typeof url === 'string' ? url : '';
                    return nativeOpen.call(this, method, url, ...rest);
                };
                XMLHttpRequest.prototype.send = function (...args) {
                    this.addEventListener('load', () => {
                        try {
                            if (isPlayurlRequest(this.__bilibiliHelperUrl)) {
                                post(this.__bilibiliHelperUrl, this.responseText || '');
                            }
                        } catch (_) {}
                    });
                    return nativeSend.apply(this, args);
                };
            }
        })();`;

    const parent = document.documentElement || document.head || document.body;
    if (parent) {
      parent.appendChild(script);
      script.remove();
    }
  }

  function installRouteWatchers() {
    const notify = () => scheduleScan();
    const nativePushState = history.pushState.bind(history);
    const nativeReplaceState = history.replaceState.bind(history);

    history.pushState = function (...args) {
      const result = nativePushState(...args);
      notify();
      return result;
    };

    history.replaceState = function (...args) {
      const result = nativeReplaceState(...args);
      notify();
      return result;
    };

    window.addEventListener('popstate', notify, true);
    window.addEventListener('hashchange', notify, true);
    window.addEventListener('load', notify, true);

    state.routeTimer = window.setInterval(() => {
      if (state.currentUrl !== location.href) {
        state.currentUrl = location.href;
        notify();
      }
    }, 1000);
  }

  function scheduleScan() {
    window.clearTimeout(state.scanTimer);
    state.scanTimer = window.setTimeout(scanPage, 150);
  }

  async function scanPage() {
    if (!isTargetPage()) {
      state.currentPageKey = '';
      state.currentPayloadKey = '';
      state.currentMeta = null;
      state.currentPayload = null;
      removePanel();
      return;
    }

    ensureMarker();
    ensureBaseStyles();
    ensurePanel();

    const meta = readPageMeta();
    if (meta && meta.pageKey !== state.currentPageKey) {
      state.currentPageKey = meta.pageKey;
      state.currentPayloadKey = '';
      state.currentPayload = null;
    }

    if (meta && JSON.stringify(meta) !== JSON.stringify(state.currentMeta)) {
      state.currentMeta = meta;
    }

    if (!state.currentPayload && hydratePayloadFromPageGlobals()) {
      renderPayload(state.currentPayload, state.currentMeta);
      return;
    }

    if (state.currentPayload) {
      renderPayload(state.currentPayload, state.currentMeta);
      return;
    }

    setStatus('正在等待或解析 playurl 数据...');
  }

  function isTargetPage() {
    return /\/video\/(av|BV)[0-9a-zA-Z]+/i.test(location.pathname) || /\/bangumi\/play\//i.test(location.pathname);
  }

  function ensureMarker() {
    if (document.getElementById(SCRIPT_ID)) {
      return;
    }

    const marker = document.createElement('script');
    marker.id = SCRIPT_ID;
    marker.type = 'application/json';
    marker.dataset.internals = JSON.stringify({
      manifest: {
        name: 'B站下载助手',
        version: '3.0.4-tm',
        version_name: '3.0.4-tm',
      },
    });
    (document.head || document.documentElement).appendChild(marker);
  }

  function ensureBaseStyles() {
    if (document.getElementById(`${PANEL_ID}-styles`)) {
      return;
    }

    const style = document.createElement('style');
    style.id = `${PANEL_ID}-styles`;
    style.textContent = `
      [class*="fullscreen"] #${HOST_ID},
      [class*="webscreen-fix"] #${HOST_ID} {
        z-index: 9 !important;
      }
      #${PANEL_ID} {
        position: fixed;
        right: 16px;
        bottom: 16px;
        width: min(420px, calc(100vw - 32px));
        max-height: min(62vh, 760px);
        z-index: 2147483647;
        background: rgba(255, 255, 255, 0.84);
        color: #111827;
        border: 1px solid rgba(255, 255, 255, 0.72);
        border-radius: 16px;
        box-shadow: 0 18px 50px rgba(15, 23, 42, 0.16);
        backdrop-filter: blur(18px) saturate(1.18);
        -webkit-backdrop-filter: blur(18px) saturate(1.18);
        overflow: hidden;
        font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
      }
      #${PANEL_ID} * {
        box-sizing: border-box;
      }
      #${PANEL_ID} .bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 14px 16px;
        border-bottom: 1px solid rgba(17, 24, 39, 0.08);
        background: rgba(255, 255, 255, 0.52);
      }
      #${PANEL_ID} .title {
        font-size: 15px;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: #111827;
      }
      #${PANEL_ID} .status {
        margin-top: 4px;
        font-size: 12px;
        color: rgba(17, 24, 39, 0.66);
      }
      #${PANEL_ID} .controls {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      #${PANEL_ID} button,
      #${PANEL_ID} a.btn {
        appearance: none;
        border: 0;
        cursor: pointer;
        border-radius: 10px;
        padding: 8px 12px;
        font-size: 12px;
        font-weight: 600;
        color: #0b1020;
        background: linear-gradient(180deg, #7dd3fc, #38bdf8);
        text-decoration: none;
        transition: transform .15s ease, filter .15s ease;
      }
      #${PANEL_ID} button:hover,
      #${PANEL_ID} a.btn:hover {
        transform: translateY(-1px);
        filter: brightness(1.04);
      }
      #${PANEL_ID} button.secondary {
        background: rgba(17, 24, 39, 0.06);
        color: #111827;
        border: 1px solid rgba(17, 24, 39, 0.08);
      }
      #${PANEL_ID} button.primary {
        background: linear-gradient(180deg, #34d399, #10b981);
        color: #06231a;
      }
      #${PANEL_ID} button:disabled {
        cursor: not-allowed;
        filter: saturate(0.6) brightness(0.8);
        transform: none;
      }
      #${PANEL_ID} .action-summary {
        margin-bottom: 0;
        color: rgba(17, 24, 39, 0.72);
        font-size: 13px;
        line-height: 1.5;
      }
      #${PANEL_ID} .download-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-bottom: 10px;
      }
      #${PANEL_ID} .log-toggle {
        margin-left: auto;
      }
      #${PANEL_ID} .log-panel {
        margin-top: 10px;
        padding: 12px;
        border: 1px solid rgba(17, 24, 39, 0.08);
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.48);
        display: none;
      }
      #${PANEL_ID}.logs-open .log-panel {
        display: block;
      }
      #${PANEL_ID} .log-panel h4 {
        margin: 0 0 8px;
        font-size: 12px;
        color: rgba(17, 24, 39, 0.72);
        font-weight: 600;
      }
      #${PANEL_ID} .log-list {
        margin: 0;
        padding: 0;
        list-style: none;
        display: grid;
        gap: 6px;
      }
      #${PANEL_ID} .log-list li {
        font-size: 12px;
        line-height: 1.5;
        color: rgba(17, 24, 39, 0.72);
        word-break: break-all;
      }
      #${PANEL_ID} .log-list strong {
        color: #111827;
        font-weight: 600;
      }
      #${PANEL_ID} .body {
        padding: 14px 16px 16px;
        overflow: auto;
        max-height: calc(min(62vh, 760px) - 64px);
      }
      #${PANEL_ID} .empty {
        padding: 18px 0 6px;
        color: rgba(17, 24, 39, 0.68);
        font-size: 13px;
      }
      #${PANEL_ID} .meta {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: 10px;
        margin-bottom: 14px;
      }
      #${PANEL_ID} .card {
        border: 1px solid rgba(17, 24, 39, 0.08);
        border-radius: 12px;
        padding: 12px;
        background: rgba(255, 255, 255, 0.44);
      }
      #${PANEL_ID} .card h4 {
        margin: 0 0 8px;
        font-size: 12px;
        color: rgba(17, 24, 39, 0.72);
        font-weight: 600;
      }
      #${PANEL_ID} .card .value {
        font-size: 13px;
        line-height: 1.45;
        word-break: break-all;
      }
      #${PANEL_ID} ul {
        margin: 0;
        padding: 0;
        list-style: none;
      }
      #${PANEL_ID} .stream {
        display: grid;
        gap: 8px;
      }
      #${PANEL_ID} .row {
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        gap: 10px;
        padding: 12px;
        border: 1px solid rgba(17, 24, 39, 0.08);
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.42);
      }
      #${PANEL_ID} .row .label {
        min-width: 0;
      }
      #${PANEL_ID} .row .label strong {
        display: block;
        margin-bottom: 4px;
        font-size: 13px;
      }
      #${PANEL_ID} .row .label span {
        display: block;
        font-size: 12px;
        color: rgba(17, 24, 39, 0.68);
        word-break: break-all;
      }
      #${PANEL_ID} .row .size {
        font-size: 12px;
        color: rgba(17, 24, 39, 0.64);
        white-space: nowrap;
      }
      #${PANEL_ID} .row .actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }
      #${PANEL_ID}.collapsed .body {
        display: none;
      }
      #${PANEL_ID}.collapsed .status {
        display: none;
      }
      #${PANEL_ID}.collapsed {
        width: auto;
        max-height: none;
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.84);
        color: #111827;
        border-color: rgba(255, 255, 255, 0.72);
        backdrop-filter: blur(18px) saturate(1.18);
        -webkit-backdrop-filter: blur(18px) saturate(1.18);
      }
      #${PANEL_ID}.collapsed .bar {
        background: rgba(255, 255, 255, 0.52);
        border-bottom-color: rgba(17, 24, 39, 0.08);
      }
      #${PANEL_ID}.collapsed .title {
        color: #111827;
      }
      #${PANEL_ID} .controls button.secondary[data-action="toggle"] {
        background: #F48FAC;
        color: #3a1020;
        border-color: #F48FAC;
      }
      #${PANEL_ID} .controls button.secondary[data-action="toggle"]:hover {
        filter: brightness(1.04);
      }
      #${PANEL_ID}.collapsed .controls button.secondary[data-action="toggle"] {
        background: #F48FAC;
        color: #3a1020;
        border-color: #F48FAC;
      }
    `;
    (document.head || document.documentElement).appendChild(style);
  }

  function ensurePanel() {
    if (document.getElementById(PANEL_ID)) {
      return;
    }

    const panel = document.createElement('div');
    panel.id = PANEL_ID;
    panel.innerHTML = `
      <div class="bar">
        <div>
          <div class="title">BiliDrown</div>
          <div class="status" data-role="status">正在初始化...</div>
        </div>
        <div class="controls">
          <button class="secondary" data-action="toggle">展开</button>
        </div>
      </div>
      <div class="body">
        <div class="meta">
          <div class="card">
            <h4>视频标题</h4>
            <div class="value" data-role="page-title">-</div>
          </div>
        </div>
        <div class="empty" data-role="empty" style="display:none"></div>
        <div class="card">
          <h4>下载</h4>
          <div class="download-actions">
            <button class="primary" data-action="download-video">下载视频</button>
            <button class="primary" data-action="download-audio">下载音频</button>
            <button class="primary cover-button" data-action="download-cover">保存封面</button>
            <button class="secondary log-toggle" data-action="toggle-logs">展开日志</button>
          </div>
          <ul class="stream" data-role="streams"></ul>
          <div class="log-panel" data-role="parse-log">
            <h4>日志内容</h4>
            <ul class="log-list" data-role="parse-log-list"></ul>
          </div>
        </div>
      </div>
    `;

    const toggleButton = panel.querySelector('[data-action="toggle"]');
    const applyCollapsedState = collapsed => {
      panel.classList.toggle('collapsed', collapsed);
      if (toggleButton) {
        toggleButton.textContent = collapsed ? '展开' : '收起';
      }
      try {
        localStorage.setItem(PANEL_COLLAPSED_STORAGE_KEY, collapsed ? '1' : '0');
      } catch (_) { }
    };

    applyCollapsedState(readCollapsedState());
    toggleButton?.addEventListener('click', () => {
      applyCollapsedState(!panel.classList.contains('collapsed'));
    });

    panel.querySelector('[data-action="toggle-logs"]')?.addEventListener('click', () => {
      panel.classList.toggle('logs-open');
      const logToggle = panel.querySelector('[data-action="toggle-logs"]');
      if (logToggle) {
        logToggle.textContent = panel.classList.contains('logs-open') ? '收起日志' : '展开日志';
      }
    });

    panel.addEventListener('click', event => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) {
        return;
      }
      const action = target.getAttribute('data-action');
      if (!action || !action.startsWith('download')) {
        return;
      }
      event.preventDefault();
      startCurrentDownload(target, action);
    });

    (document.body || document.documentElement).appendChild(panel);
    state.installed = true;
  }

  function removePanel() {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      panel.remove();
    }
  }

  function setStatus(text) {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) {
      return;
    }
    const status = panel.querySelector('[data-role="status"]');
    if (status) {
      status.style.display = 'block';
      status.textContent = text;
    }
  }

  function readCollapsedState() {
    try {
      return localStorage.getItem(PANEL_COLLAPSED_STORAGE_KEY) === '1';
    } catch (_) {
      return false;
    }
  }

  function readPageMeta() {
    const pageIdentity = getCurrentPageIdentity();
    const title = cleanTitle(document.title || 'B站视频');
    return {
      title,
      pageType: /\/bangumi\/play\//i.test(location.pathname) ? '番剧/影视' : '投稿视频',
      pageKey: `${location.pathname}${location.search}`,
      identity: pageIdentity,
    };
  }

  function cleanTitle(title) {
    return title
      .replace(/_哔哩哔哩.*$/i, '')
      .replace(/ - 哔哩哔哩.*$/i, '')
      .replace(/ \| 哔哩哔哩.*$/i, '')
      .trim();
  }

  function isPlayurlRequest(url) {
    return typeof url === 'string' && /\/playurl(?:\?|$)/i.test(url);
  }

  function normalizeRequestUrl(input) {
    if (typeof input === 'string') {
      return input;
    }
    if (input instanceof URL) {
      return input.href;
    }
    if (input && typeof input.url === 'string') {
      return input.url;
    }
    return '';
  }

  function capturePayload(requestUrl, rawText) {
    if (!rawText) {
      return;
    }

    let payload;
    try {
      payload = JSON.parse(rawText);
    } catch (_) {
      return;
    }

    if (!isMatchingPlayurlRequest(requestUrl)) {
      console.log('[B站下载助手] 忽略不匹配的 playurl 响应:', requestUrl);
      return;
    }

    const normalized = normalizePayload(payload, requestUrl, state.currentPageKey || readPageMeta().pageKey);
    if (state.currentPageKey && normalized.pageKey !== state.currentPageKey) {
      console.log('[B站下载助手] 忽略过期的 playurl 响应:', normalized.pageKey, state.currentPageKey);
      return;
    }

    state.currentPayloadKey = normalized.pageKey;
    state.currentPayload = normalized;
    renderPayload(state.currentPayload, state.currentMeta || readPageMeta());
  }

  function hydratePayloadFromPageGlobals() {
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
    const candidates = [
      pageWindow.__playinfo__,
      pageWindow.__playInfo__,
      pageWindow.__INITIAL_STATE__?.playinfo,
      pageWindow.__INITIAL_STATE__?.playInfo,
      pageWindow.__INITIAL_STATE__?.videoData?.playinfo,
    ];

    for (const candidate of candidates) {
      if (!candidate) {
        continue;
      }
      let payload = candidate;
      if (typeof candidate === 'string') {
        try {
          payload = JSON.parse(candidate);
        } catch (_) {
          continue;
        }
      }
      const normalized = normalizePayload(payload, location.href);
      if (normalized.dash || normalized.durl) {
        console.log('[B站下载助手] 从页面全局数据中恢复 playurl:', normalized.query);
        if (state.currentPageKey && normalized.pageKey !== state.currentPageKey) {
          continue;
        }
        state.currentPayloadKey = normalized.pageKey;
        state.currentPayload = normalized;
        return true;
      }
    }

    return false;
  }

  function getCurrentPageIdentity() {
    const pathname = location.pathname;
    const searchParams = new URL(location.href).searchParams;
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
    const initialState = pageWindow.__INITIAL_STATE__ || {};
    const videoData = initialState.videoData || {};
    const pages = Array.isArray(videoData.pages) ? videoData.pages : [];
    const pageIndex = Math.max(1, Number(searchParams.get('p') || 1)) - 1;
    const currentPage = pages[pageIndex] || pages[0] || null;
    const aid = videoData.aid || initialState.aid || currentPage?.aid || '';
    const bvid = videoData.bvid || initialState.bvid || currentPage?.bvid || '';
    const cid = currentPage?.cid || videoData.cid || initialState.cid || searchParams.get('cid') || '';

    const videoMatch = pathname.match(/\/video\/(av\d+|BV[0-9A-Za-z]+)/i);
    if (videoMatch) {
      const videoId = videoMatch[1];
      return {
        type: 'video',
        avid: /^av\d+$/i.test(videoId) ? videoId.slice(2) : String(aid || '').replace(/^av/i, ''),
        bvid: /^bv[0-9a-z]+$/i.test(videoId) ? videoId.toUpperCase() : String(bvid || '').toUpperCase(),
        cid: String(cid || ''),
        pageKey: `${pathname}${location.search}`,
      };
    }

    const epMatch = pathname.match(/\/bangumi\/play\/(ep\d+)/i);
    if (epMatch) {
      return {
        type: 'bangumi',
        ep_id: epMatch[1],
        cid: String(cid || searchParams.get('cid') || ''),
        pageKey: `${pathname}${location.search}`,
      };
    }

    return {
      type: 'unknown',
      avid: aid ? String(aid).replace(/^av/i, '') : '',
      bvid: String(bvid || '').toUpperCase(),
      cid: String(cid || ''),
      pageKey: `${pathname}${location.search}`,
    };
  }

  function isMatchingPlayurlRequest(requestUrl) {
    const requestParams = new URL(requestUrl, location.href).searchParams;
    const pageIdentity = getCurrentPageIdentity();
    if (!pageIdentity) {
      return true;
    }

    if (pageIdentity.bvid) {
      const requestBvid = (requestParams.get('bvid') || '').toUpperCase();
      if (requestBvid && requestBvid !== pageIdentity.bvid) {
        return false;
      }
    }

    if (pageIdentity.avid) {
      const requestAvid = requestParams.get('avid') || '';
      if (requestAvid && requestAvid !== pageIdentity.avid) {
        return false;
      }
    }

    if (pageIdentity.ep_id) {
      const requestEpId = requestParams.get('ep_id') || '';
      if (requestEpId && requestEpId !== pageIdentity.ep_id) {
        return false;
      }
    }

    if (pageIdentity.cid) {
      const requestCid = requestParams.get('cid') || '';
      if (requestCid && requestCid !== pageIdentity.cid) {
        return false;
      }
    }

    return true;
  }

  function normalizePayload(payload, requestUrl, pageKey = `${location.pathname}${location.search}`) {
    const query = new URL(requestUrl, location.href).searchParams;
    const data = payload?.data ?? payload?.result?.video_info ?? payload?.result ?? payload;
    const dash = data?.dash ?? data?.video_info?.dash ?? data?.dash_info ?? null;
    const durl = data?.durl ?? data?.video_info?.durl ?? null;
    const supportFormats = data?.support_formats ?? dash?.support_formats ?? [];
    const quality = toNumber(data?.quality ?? data?.current_quality ?? query.get('qn'));
    const videoCodecid = toNumber(data?.video_codecid ?? data?.videoCodecid ?? data?.video_codecid_id);
    const videoList = Array.isArray(dash?.video) ? dash.video : [];
    const audioList = Array.isArray(dash?.audio) ? dash.audio : [];
    const selectedFormat = supportFormats.find(item => toNumber(item?.quality) === quality);

    const video = selectDashVideo(videoList, quality, videoCodecid);
    const audio = audioList[0] || null;

    return {
      code: payload?.code ?? data?.code ?? 0,
      message: payload?.message ?? data?.message ?? '',
      title: state.currentMeta?.title || cleanTitle(document.title || 'B站视频'),
      pageType: /\/bangumi\/play\//i.test(location.pathname) ? '番剧/影视' : '投稿视频',
      pageKey,
      quality,
      videoCodecid,
      query: {
        avid: query.get('avid'),
        bvid: query.get('bvid'),
        cid: query.get('cid'),
        ep_id: query.get('ep_id'),
      },
      dash: dash ? {
        video,
        audio,
        videoList,
        audioList,
      } : null,
      durl: Array.isArray(durl) ? durl : null,
      qualityDescription: data?.quality_description || data?.quality_desc || selectedFormat?.new_description || selectedFormat?.display_desc || QUALITY_LABELS[quality] || '',
      supportFormats,
      raw: payload,
    };
  }

  function toNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function selectDashVideo(videoList, quality, videoCodecid) {
    if (!Array.isArray(videoList) || videoList.length === 0) {
      return null;
    }

    const qualityMatches = quality != null ? videoList.filter(entry => String(entry?.id) === String(quality)) : videoList;
    const codecidMatches = videoCodecid != null ? qualityMatches.filter(entry => String(entry?.codecid) === String(videoCodecid)) : qualityMatches;
    return codecidMatches[0] || qualityMatches[0] || videoList[0] || null;
  }

  function renderPayload(payload, meta) {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) {
      return;
    }

    const status = panel.querySelector('[data-role="status"]');
    const pageTitle = panel.querySelector('[data-role="page-title"]');
    const streams = panel.querySelector('[data-role="streams"]');
    const empty = panel.querySelector('[data-role="empty"]');
    const parseLogList = panel.querySelector('[data-role="parse-log-list"]');

    if (pageTitle) {
      pageTitle.textContent = meta?.title || payload.title || '-';
    }

    if (payload.code && payload.code !== 0) {
      if (status) {
        status.textContent = `解析失败：${payload.message || payload.code}`;
        status.style.display = 'block';
      }
      if (streams) {
        streams.innerHTML = '';
      }
      if (empty) {
        empty.textContent = payload.message || '没有拿到可下载的资源。';
        empty.style.display = 'block';
      }
      return;
    }

    if (status) {
      status.textContent = '';
      status.style.display = 'none';
    }

    if (payload.dash) {
      renderDashStreams(streams, empty, payload);
      renderParseLog(parseLogList, payload, meta);
      return;
    }

    if (payload.durl) {
      renderDurlStreams(streams, empty, payload);
      renderParseLog(parseLogList, payload, meta);
      return;
    }

    if (streams) {
      streams.innerHTML = '';
    }
    if (empty) {
      empty.textContent = '当前 playurl 响应中没有 dash 或 durl 字段。';
      empty.style.display = 'block';
    }
  }

  function renderDashStreams(streams, empty, payload) {
    if (!streams) {
      return;
    }
    const video = payload.dash.video;
    const audio = payload.dash.audio;
    streams.innerHTML = `
      <li class="row">
        <div class="label">
          <strong>视频 + 音频</strong>
          <span>${escapeHtml(describeStream(video))} + ${escapeHtml(describeStream(audio))}</span>
        </div>
      </li>
    `;
    if (empty) {
      empty.style.display = 'none';
    }
  }

  function renderDurlStreams(streams, empty, payload) {
    if (!streams) {
      return;
    }
    const list = (payload.durl || []).map((segment, index) => {
      const url = chooseUrl(segment);
      const filename = `${safeName(payload.title)}_${payload.durl.length > 1 ? `part${index + 1}` : 'video'}${getMediaExtension(url)}`;
      return `
      <li class="row">
        <div class="label">
          <strong>${escapeHtml(payload.durl.length > 1 ? `分段 ${index + 1}` : '单段视频')}</strong>
          <span>${escapeHtml(describeSegment(segment, index + 1))}</span>
        </div>
        <div class="size">${formatSize(segment.size)}</div>
        <div class="actions">
          <a class="btn" href="${escapeHtml(url)}" download="${escapeHtml(filename)}">下载</a>
        </div>
      </li>
    `;
    });

    streams.innerHTML = list.join('') || '<li class="empty">没有可下载的分段资源。</li>';
    if (empty) {
      empty.style.display = 'none';
    }
  }

  function renderParseLog(container, payload, meta) {
    if (!container) {
      return;
    }

    const lines = [];
    const query = payload.query || {};
    const identity = meta?.identity || {};
    const av = query.avid || identity.avid || '-';
    const bvid = query.bvid || identity.bvid || '-';
    const cid = query.cid || identity.cid || '-';

    lines.push(`<li><strong>av：</strong>${escapeHtml(av)} <strong>bvid：</strong>${escapeHtml(bvid)} <strong>cid：</strong>${escapeHtml(cid)}</li>`);

    if (payload.dash?.video) {
      const videoMain = chooseUrl(payload.dash.video);
      if (videoMain) {
        lines.push(`<li><strong>视频主链接：</strong>${escapeHtml(videoMain)}</li>`);
      }
      if (Array.isArray(payload.dash.video.backup_url) && payload.dash.video.backup_url.length) {
        payload.dash.video.backup_url.forEach((url, index) => {
          lines.push(`<li><strong>视频备用链接 ${index + 1}：</strong>${escapeHtml(url)}</li>`);
        });
      }
    }

    if (payload.dash?.audio) {
      const audioMain = chooseUrl(payload.dash.audio);
      if (audioMain) {
        lines.push(`<li><strong>音频主链接：</strong>${escapeHtml(audioMain)}</li>`);
      }
      if (Array.isArray(payload.dash.audio.backup_url) && payload.dash.audio.backup_url.length) {
        payload.dash.audio.backup_url.forEach((url, index) => {
          lines.push(`<li><strong>音频备用链接 ${index + 1}：</strong>${escapeHtml(url)}</li>`);
        });
      }
    }

    if (payload.durl?.length) {
      payload.durl.forEach((segment, index) => {
        const segmentMain = chooseUrl(segment);
        if (segmentMain) {
          lines.push(`<li><strong>分段主链接 ${index + 1}：</strong>${escapeHtml(segmentMain)}</li>`);
        }
        if (Array.isArray(segment.backup_url) && segment.backup_url.length) {
          segment.backup_url.forEach((url, backupIndex) => {
            lines.push(`<li><strong>分段备用链接 ${index + 1}.${backupIndex + 1}：</strong>${escapeHtml(url)}</li>`);
          });
        }
      });
    }

    container.innerHTML = lines.join('');
  }

  function getCoverImageUrl() {
    const metaImage = getMetaContentByProperty('og:image') || getMetaContentByProperty('twitter:image');
    if (!metaImage) {
      return '';
    }
    const normalized = metaImage.split('@')[0];
    return normalized.startsWith('//') ? `https:${normalized}` : normalized;
  }

  function getMetaContentByProperty(property) {
    const metaTags = document.getElementsByTagName('meta');
    for (let i = 0; i < metaTags.length; i++) {
      const metaTag = metaTags[i];
      if (metaTag.getAttribute('property') === property) {
        return metaTag.getAttribute('content');
      }
    }
    return null;
  }

  async function downloadCover(payload, taskId) {
    const coverUrl = getCoverImageUrl();
    if (!coverUrl) {
      throw new Error('未找到封面地址');
    }

    const baseName = safeName(payload.title || readPageMeta().title || 'bilibili-cover');
    const coverExtension = getMediaExtension(coverUrl).replace(/\.m4s$/i, '.jpg');
    const filename = `${baseName}_cover${coverExtension}`;

    setStatus('正在保存封面...');
    const coverBytes = await fetchBinary(coverUrl, progress => {
      if (taskId === state.activeTaskId) {
        const percent = progress.total > 0 ? Math.round((progress.received / progress.total) * 100) : 0;
        setStatus(`封面下载中：${progress.received}/${progress.total > 0 ? progress.total : '?'} ${progress.total > 0 ? `${percent}%` : ''}`.trim());
      }
    });

    if (taskId !== state.activeTaskId) {
      return;
    }

    await saveBlob(new Blob([coverBytes], { type: 'image/jpeg' }), filename);
    setStatus(`✓ 已保存封面: ${filename}`);
  }

  function chooseUrl(entry) {
    return entry?.base_url || entry?.baseUrl || entry?.url || (Array.isArray(entry?.backup_url) ? entry.backup_url[0] : '') || '';
  }

  function describeStream(entry) {
    const bandwidth = entry?.bandwidth ? `${Math.round(entry.bandwidth / 1000)} kbps` : '';
    const codecid = entry?.codecid ? `codecid ${entry.codecid}` : '';
    const resolution = entry?.width && entry?.height ? `${entry.width}x${entry.height}` : '';
    return [resolution, bandwidth, codecid].filter(Boolean).join(' · ') || 'DASH 流';
  }

  function describeSegment(segment, index) {
    const parts = [`分段 ${index}`];
    if (segment?.size) {
      parts.push(formatSize(segment.size));
    }
    return parts.join(' · ');
  }

  function formatSize(value) {
    const size = Number(value);
    if (!Number.isFinite(size) || size <= 0) {
      return '未知大小';
    }
    if (size >= 1024 * 1024 * 1024) {
      return `${(size / (1024 * 1024 * 1024)).toFixed(2)} GB`;
    }
    if (size >= 1024 * 1024) {
      return `${(size / (1024 * 1024)).toFixed(2)} MB`;
    }
    if (size >= 1024) {
      return `${(size / 1024).toFixed(2)} KB`;
    }
    return `${size} B`;
  }

  function safeName(name) {
    return String(name || 'bilibili-video').replace(/[\\/:*?"<>|\s]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
  }

  function getMediaExtension(url) {
    try {
      const pathname = new URL(url, location.href).pathname;
      const match = pathname.match(/\.[a-z0-9]+$/i);
      if (match) {
        return match[0].toLowerCase();
      }
    } catch (_) {
      // fall through to the default extension
    }
    return '.m4s';
  }

  function getStreamCandidates(entry) {
    const urls = [];
    const primary = chooseUrl(entry);
    if (primary) {
      urls.push(primary);
    }
    if (Array.isArray(entry?.backup_url)) {
      for (const candidate of entry.backup_url) {
        if (candidate && typeof candidate === 'string' && !urls.includes(candidate)) {
          urls.push(candidate);
        }
      }
    }
    console.log('[B站下载助手] 从 entry 提取候选URL:', {
      entryKeys: Object.keys(entry || {}),
      baseUrl: entry?.base_url?.substring(0, 100),
      backupUrlCount: Array.isArray(entry?.backup_url) ? entry.backup_url.length : 0,
      resultCount: urls.length
    });
    return urls;
  }

  async function loadRemoteText(sourceUrl) {
    if (typeof GM_xmlhttpRequest === 'function') {
      return await new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: 'GET',
          url: sourceUrl,
          onload: response => {
            const status = response.status || 0;
            if (status < 200 || status >= 300) {
              reject(new Error(`无法加载 ffmpeg 资源: HTTP ${status}`));
              return;
            }
            resolve(response.responseText || '');
          },
          onerror: error => {
            reject(new Error(error?.error || error?.message || '无法加载 ffmpeg 文本资源'));
          },
          ontimeout: () => {
            reject(new Error('无法加载 ffmpeg 文本资源: 超时'));
          },
        });
      });
    }

    const response = await fetch(sourceUrl);
    if (!response.ok) {
      throw new Error(`无法加载 ffmpeg 资源: HTTP ${response.status}`);
    }
    return await response.text();
  }

  async function loadRemoteBinary(sourceUrl) {
    if (typeof GM_xmlhttpRequest === 'function') {
      return await new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: 'GET',
          url: sourceUrl,
          responseType: 'arraybuffer',
          onload: response => {
            const status = response.status || 0;
            if (status < 200 || status >= 300) {
              reject(new Error(`无法加载 ffmpeg 资源: HTTP ${status}`));
              return;
            }
            if (!(response.response instanceof ArrayBuffer)) {
              reject(new Error('无法加载 ffmpeg 二进制资源'));
              return;
            }
            resolve(response.response);
          },
          onerror: error => {
            reject(new Error(error?.error || error?.message || '无法加载 ffmpeg 二进制资源'));
          },
          ontimeout: () => {
            reject(new Error('无法加载 ffmpeg 二进制资源: 超时'));
          },
        });
      });
    }

    const response = await fetch(sourceUrl);
    if (!response.ok) {
      throw new Error(`无法加载 ffmpeg 资源: HTTP ${response.status}`);
    }
    return await response.arrayBuffer();
  }

  async function toBlobURL(sourceUrl, mimeType) {
    const isBinary = mimeType === 'application/wasm';
    const blob = isBinary
      ? new Blob([await loadRemoteBinary(sourceUrl)], { type: mimeType })
      : new Blob([await loadRemoteText(sourceUrl)], { type: mimeType });
    return URL.createObjectURL(blob);
  }

  async function loadFfmpegModule() {
    const pageWindow = typeof unsafeWindow !== 'undefined' ? unsafeWindow : window;
    if (pageWindow.FFmpegWASM?.FFmpeg) {
      return pageWindow.FFmpegWASM;
    }

    const source = await loadRemoteText(`${FFMPEG_BASE_URL}/ffmpeg.js`);
    const patchedSource = source.replace('new URL(e.p+e.u(814),e.b)', 'r.workerLoadURL');
    const moduleUrl = URL.createObjectURL(new Blob([patchedSource], { type: 'text/javascript' }));
    state.ffmpegModuleUrl = moduleUrl;

    if (!state.ffmpegModuleCleanupBound) {
      state.ffmpegModuleCleanupBound = true;
      window.addEventListener('beforeunload', () => {
        const urlKeys = [
          'ffmpegModuleUrl',
          'ffmpegCoreUrl',
          'ffmpegWorkerUrl',
          'ffmpegWasmUrl',
          'ffmpegWorkerLoadUrl',
        ];
        for (const key of urlKeys) {
          if (state[key]) {
            URL.revokeObjectURL(state[key]);
            state[key] = '';
          }
        }
      }, { once: true });
    }

    await new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = moduleUrl;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error('无法加载 ffmpeg 主模块'));
      (document.head || document.documentElement).appendChild(script);
    });

    if (!pageWindow.FFmpegWASM?.FFmpeg) {
      throw new Error('无法初始化 ffmpeg 主模块');
    }

    return pageWindow.FFmpegWASM;
  }

  async function getFfmpegInstance() {
    if (!state.ffmpegPromise) {
      state.ffmpegPromise = (async () => {
        const FFmpegWASM = await loadFfmpegModule();
        const ffmpeg = new FFmpegWASM.FFmpeg();
        if (typeof ffmpeg.on === 'function') {
          ffmpeg.on('log', ({ message }) => console.log('[B站下载助手][ffmpeg]', message));
          ffmpeg.on('progress', progress => console.log('[B站下载助手][ffmpeg-progress]', progress));
        }

        const baseFFmpegUrl = FFMPEG_BASE_URL;
        const coreBaseUrl = window.crossOriginIsolated ? FFMPEG_MT_CORE_BASE_URL : FFMPEG_CORE_BASE_URL;
        const coreUrl = await toBlobURL(`${coreBaseUrl}/ffmpeg-core.js`, 'text/javascript');
        const wasmUrl = await toBlobURL(`${coreBaseUrl}/ffmpeg-core.wasm`, 'application/wasm');
        const workerLoadUrl = await toBlobURL(`${baseFFmpegUrl}/814.ffmpeg.js`, 'text/javascript');
        state.ffmpegCoreUrl = coreUrl;
        state.ffmpegWasmUrl = wasmUrl;
        state.ffmpegWorkerLoadUrl = workerLoadUrl;

        if (window.crossOriginIsolated) {
          const workerUrl = await toBlobURL(`${coreBaseUrl}/ffmpeg-core.worker.js`, 'text/javascript');
          state.ffmpegWorkerUrl = workerUrl;
          await ffmpeg.load({
            coreURL: coreUrl,
            wasmURL: wasmUrl,
            workerURL: workerUrl,
            workerLoadURL: workerLoadUrl,
          });
        } else {
          await ffmpeg.load({
            coreURL: coreUrl,
            wasmURL: wasmUrl,
            workerLoadURL: workerLoadUrl,
          });
        }
        return ffmpeg;
      })();
    }
    return state.ffmpegPromise;
  }

  function toUint8Array(data) {
    if (data instanceof Uint8Array) {
      return data;
    }
    if (data instanceof ArrayBuffer) {
      return new Uint8Array(data);
    }
    if (ArrayBuffer.isView(data)) {
      return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    }
    return new Uint8Array();
  }

  async function mergeVideoAndAudioToMp4(videoBytes, audioBytes, taskId) {
    const ffmpeg = await getFfmpegInstance();
    const stamp = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const videoPath = `${stamp}_video.mp4`;
    const audioPath = `${stamp}_audio.mp4`;
    const outputPath = `${stamp}_merged.mp4`;
    const cleanup = async () => {
      await Promise.all([
        ffmpeg.deleteFile(videoPath).catch(() => { }),
        ffmpeg.deleteFile(audioPath).catch(() => { }),
        ffmpeg.deleteFile(outputPath).catch(() => { }),
      ]);
    };

    try {
      if (taskId !== state.activeTaskId) {
        throw new Error('下载已取消');
      }
      await ffmpeg.writeFile(videoPath, toUint8Array(videoBytes));
      await ffmpeg.writeFile(audioPath, toUint8Array(audioBytes));
      await ffmpeg.exec(['-i', videoPath, '-i', audioPath, '-vcodec', 'copy', '-acodec', 'copy', outputPath]);
      const mergedBytes = await ffmpeg.readFile(outputPath);
      return toUint8Array(mergedBytes);
    } finally {
      await cleanup();
    }
  }

  async function convertAudioToMp3(audioBytes, taskId) {
    const ffmpeg = await getFfmpegInstance();
    const stamp = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    const inputPath = `${stamp}_audio_input.mp4`;
    const outputPath = `${stamp}_audio.mp3`;
    const cleanup = async () => {
      await Promise.all([
        ffmpeg.deleteFile(inputPath).catch(() => { }),
        ffmpeg.deleteFile(outputPath).catch(() => { }),
      ]);
    };

    try {
      if (taskId !== state.activeTaskId) {
        throw new Error('下载已取消');
      }
      await ffmpeg.writeFile(inputPath, toUint8Array(audioBytes));
      await ffmpeg.exec(['-i', inputPath, '-vn', '-acodec', 'libmp3lame', '-q:a', '2', outputPath]);
      const mp3Bytes = await ffmpeg.readFile(outputPath);
      return toUint8Array(mp3Bytes);
    } finally {
      await cleanup();
    }
  }

  async function startCurrentDownload(button, action) {
    const payload = state.currentPayload;
    if (!payload) {
      setStatus('没有可下载的 playurl 数据');
      return;
    }
    if (payload.pageKey && state.currentPageKey && payload.pageKey !== state.currentPageKey) {
      state.currentPayload = null;
      state.currentPayloadKey = '';
      setStatus('当前页面的资源已过期，请重新等待解析');
      return;
    }

    const taskId = ++state.activeTaskId;
    if (button) {
      button.disabled = true;
      button.textContent = '处理中...';
    }

    try {
      // 根据 action 确定下载类型
      if (action === 'download-video') {
        // 只下载视频
        await downloadVideoOnly(payload, taskId);
      } else if (action === 'download-audio') {
        // 只下载音频
        await downloadAudioOnly(payload, taskId);
      } else if (action === 'download-cover') {
        await downloadCover(payload, taskId);
      } else {
        // 兼容旧的单按钮方式
        if (payload.dash?.video && payload.dash?.audio) {
          await downloadDashSeparate(payload, taskId);
        } else if (payload.durl?.length) {
          await downloadSingleStream(payload, taskId);
        } else {
          throw new Error('当前资源没有可下载的音视频流');
        }
      }
      setStatus('下载完成');
    } catch (error) {
      console.error('[B站下载助手]', error);
      setStatus(`下载失败：${error?.message || error}`);
      alert(`下载失败：${error?.message || error}`);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = action === 'download-video' ? '下载视频' : action === 'download-audio' ? '下载音频' : action === 'download-cover' ? '保存封面' : '下载';
      }
    }
  }

  // 只下载视频，完成后用 ffmpeg 合并为 mp4
  async function downloadVideoOnly(payload, taskId) {
    if (!payload.dash?.video) {
      throw new Error('当前资源没有视频流');
    }

    const videoEntry = payload.dash.video;
    const videoCandidates = getStreamCandidates(videoEntry);

    console.log('[B站下载助手] 只下载视频');
    console.log('[B站下载助手] 视频候选URL:', videoCandidates);

    setStatus('正在下载视频流...');
    const [videoBytes, videoUrl] = await downloadBinaryWithFallback(videoCandidates, '视频流', taskId);
    console.log('[B站下载助手] 视频字节数:', videoBytes?.byteLength);

    if (taskId !== state.activeTaskId) {
      return;
    }

    setStatus('正在下载音频流...');
    const audioEntry = payload.dash.audio;
    if (!audioEntry) {
      throw new Error('当前资源没有音频流');
    }
    const audioCandidates = getStreamCandidates(audioEntry);
    console.log('[B站下载助手] 音频候选URL:', audioCandidates);
    const [audioBytes, audioUrl] = await downloadBinaryWithFallback(audioCandidates, '音频流', taskId);
    console.log('[B站下载助手] 音频字节数:', audioBytes?.byteLength);

    if (taskId !== state.activeTaskId) {
      return;
    }

    const baseName = safeName(payload.title);
    const videoFilename = `${baseName}.mp4`;

    setStatus('正在合并并保存视频...');
    const mergedBytes = await mergeVideoAndAudioToMp4(videoBytes, audioBytes, taskId);
    if (taskId !== state.activeTaskId) {
      return;
    }

    setStatus(`正在保存视频: ${videoFilename}`);
    await saveBlob(new Blob([mergedBytes], { type: 'video/mp4' }), videoFilename);
    console.log('[B站下载助手] 已保存视频:', videoFilename);
    setStatus(`✓ 已下载视频: ${videoFilename}`);
  }

  // 只下载音频，完成后转为 mp3
  async function downloadAudioOnly(payload, taskId) {
    if (!payload.dash?.audio) {
      throw new Error('当前资源没有音频流');
    }

    const audioEntry = payload.dash.audio;
    const audioCandidates = getStreamCandidates(audioEntry);

    console.log('[B站下载助手] 只下载音频');
    console.log('[B站下载助手] 音频候选URL:', audioCandidates);

    setStatus('正在下载音频流...');
    const [audioBytes, audioUrl] = await downloadBinaryWithFallback(audioCandidates, '音频流', taskId);
    console.log('[B站下载助手] 音频字节数:', audioBytes?.byteLength);

    if (taskId !== state.activeTaskId) {
      return;
    }

    const baseName = safeName(payload.title);
    const audioFilename = `${baseName}.mp3`;

    setStatus('正在转换为 MP3...');
    const mp3Bytes = await convertAudioToMp3(audioBytes, taskId);
    if (taskId !== state.activeTaskId) {
      return;
    }

    setStatus(`正在保存音频: ${audioFilename}`);
    await saveBlob(new Blob([mp3Bytes], { type: 'audio/mpeg' }), audioFilename);
    console.log('[B站下载助手] 已保存音频:', audioFilename);
    setStatus(`✓ 已下载音频: ${audioFilename}`);
  }

  // 分别下载 DASH 格式的视频和音频（不合并）
  async function downloadDashSeparate(payload, taskId) {
    const videoEntry = payload.dash.video;
    const audioEntry = payload.dash.audio;

    console.log('[B站下载助手] DASH 格式：分别下载视频和音频');

    const videoCandidates = getStreamCandidates(videoEntry);
    const audioCandidates = getStreamCandidates(audioEntry);

    console.log('[B站下载助手] 视频候选URL:', videoCandidates);
    console.log('[B站下载助手] 音频候选URL:', audioCandidates);

    // 下载视频
    setStatus('正在下载视频流...');
    const [videoBytes, videoUrl] = await downloadBinaryWithFallback(videoCandidates, '视频流', taskId);
    console.log('[B站下载助手] 视频字节数:', videoBytes?.byteLength);

    if (taskId !== state.activeTaskId) {
      return;
    }

    // 下载音频
    setStatus('正在下载音频流...');
    const [audioBytes, audioUrl] = await downloadBinaryWithFallback(audioCandidates, '音频流', taskId);
    console.log('[B站下载助手] 音频字节数:', audioBytes?.byteLength);

    if (taskId !== state.activeTaskId) {
      return;
    }

    // 分别保存视频和音频
    const videoExt = getMediaExtension(videoUrl);
    const audioExt = getMediaExtension(audioUrl);
    const baseName = safeName(payload.title);

    const videoFilename = `${baseName}_video${videoExt}`;
    const audioFilename = `${baseName}_audio${audioExt}`;

    setStatus(`正在保存视频: ${videoFilename}`);
    await saveBlob(new Blob([videoBytes], { type: 'video/mp4' }), videoFilename);
    console.log('[B站下载助手] 已保存视频:', videoFilename);

    setStatus(`正在保存音频: ${audioFilename}`);
    await saveBlob(new Blob([audioBytes], { type: 'audio/mp4' }), audioFilename);
    console.log('[B站下载助手] 已保存音频:', audioFilename);

    setStatus(`✓ 已下载：${videoFilename} 和 ${audioFilename}`);
  }

  async function downloadSingleStream(payload, taskId) {
    const segment = payload.durl[0];
    const candidates = getStreamCandidates(segment);
    const [bytes, url] = await downloadBinaryWithFallback(candidates, '视频流', taskId);
    const filename = `${safeName(payload.title)}${getMediaExtension(url)}`;
    await saveBlob(new Blob([bytes], { type: 'application/octet-stream' }), filename);
    setStatus(`已生成 ${filename}`);
  }

  async function downloadBinaryWithFallback(urls, label, taskId) {
    console.log('[B站下载助手]', label, '候选 URL 列表:', urls);
    if (!urls || urls.length === 0) {
      throw new Error(`${label}没有可用的 URL 候选列表`);
    }

    const errors = [];
    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];
      if (taskId !== state.activeTaskId) {
        throw new Error('下载已取消');
      }
      console.log(`[B站下载助手] 尝试 ${label} 候选 ${i + 1}/${urls.length}: ${url}`);
      try {
        const bytes = await fetchBinary(url, progress => {
          if (taskId === state.activeTaskId) {
            const percent = progress.total > 0 ? Math.round((progress.received / progress.total) * 100) : 0;
            setStatus(`${label}下载中：${progress.received}/${progress.total > 0 ? progress.total : '?'} ${progress.total > 0 ? `${percent}%` : ''}`.trim());
          }
        });
        console.log(`[B站下载助手] ${label} 下载成功，字节数:`, bytes?.byteLength);
        return [bytes, url];
      } catch (error) {
        console.warn(`[B站下载助手] ${label} 候选 ${i + 1} 失败:`, error?.message || error);
        errors.push(`${url} -> ${error?.message || error}`);
      }
    }
    const errorMsg = `${label}下载失败：${errors.join('；')}`;
    console.error('[B站下载助手]', errorMsg);
    throw new Error(errorMsg);
  }

  async function fetchBinary(url, onProgress) {
    console.log('[B站下载助手] 开始下载:', url);
    if (typeof GM_xmlhttpRequest === 'function') {
      console.log('[B站下载助手] 使用 GM_xmlhttpRequest 下载');
      return await new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
          method: 'GET',
          url,
          responseType: 'arraybuffer',
          timeout: 60000,
          headers: {
            Referer: 'https://www.bilibili.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
          },
          onprogress: event => {
            const received = event.loaded || 0;
            const total = event.lengthComputable ? (event.total || -1) : -1;
            onProgress?.({ received, total });
          },
          onload: response => {
            const status = response.status || 0;
            if (status < 200 || status >= 300) {
              reject(new Error(`HTTP ${status}`));
              return;
            }
            const buffer = response.response;
            if (!(buffer instanceof ArrayBuffer)) {
              reject(new Error('GM_xmlhttpRequest 未返回 ArrayBuffer'));
              return;
            }
            onProgress?.({ received: buffer.byteLength, total: buffer.byteLength });
            console.log('[B站下载助手] 下载完成，大小:', buffer.byteLength);
            resolve(buffer);
          },
          onerror: error => {
            reject(new Error(error?.error || error?.message || 'GM_xmlhttpRequest 请求失败'));
          },
          ontimeout: () => {
            reject(new Error('GM_xmlhttpRequest 请求超时'));
          },
        });
      });
    }

    console.log('[B站下载助手] GM_xmlhttpRequest 不可用，回退到 fetch');
    const response = await fetch(url, {
      credentials: 'include',
      headers: {
        'Referer': 'https://www.bilibili.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      }
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const contentLength = response.headers.get('content-length');
    const total = contentLength ? Number(contentLength) : -1;
    console.log('[B站下载助手] Content-Length:', contentLength, 'total:', total);

    const buffer = await response.arrayBuffer();
    onProgress?.({ received: buffer.byteLength, total: buffer.byteLength });
    console.log('[B站下载助手] 下载完成，大小:', buffer.byteLength);
    return buffer;
  }

  async function saveBlob(blob, filename) {
    const objectUrl = URL.createObjectURL(blob);
    try {
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = filename;
      anchor.rel = 'noreferrer';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } finally {
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    }
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

})();
