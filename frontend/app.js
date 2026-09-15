// Configuration
const pathParts = window.location.pathname.split('/').filter(Boolean);
const SECRET_PREFIX = pathParts.length > 0 ? '/' + pathParts[0] : '';
const API_BASE = SECRET_PREFIX + '/api';

// Utility: API Client
async function api(path, options = {}) {
    const url = API_BASE + path;
    const defaultHeaders = { 'Content-Type': 'application/json' };
    
    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...options.headers,
        },
    };

    if (config.body && typeof config.body === 'object') {
        config.body = JSON.stringify(config.body);
    }

    try {
        const response = await fetch(url, config);
        const data = await response.json().catch(() => ({}));
        
        if (!response.ok) {
            throw new Error(data.detail || data.error || `HTTP error ${response.status}`);
        }
        
        return data;
    } catch (error) {
        showToast(error.message, 'error');
        throw error;
    }
}

// Utility: Toast Notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerText = message;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Utility: Formatters
function formatDuration(seconds) {
    if (!seconds) return '00:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

function formatSize(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDate(ts) {
    if (!ts) return 'N/A';
    // Handle both unix timestamps and ISO strings
    const date = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts);
    return date.toLocaleString('zh-CN', { 
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit'
    });
}

function formatImageUrl(url) {
    if (!url) return '';
    if (url.startsWith('//')) return 'https:' + url;
    if (url.startsWith('http://')) return url.replace('http://', 'https://');
    return url;
}

function getImageProxyUrl(url) {
    if (!url) return '';
    return `${API_BASE}/proxy/image?url=${encodeURIComponent(formatImageUrl(url))}`;
}

/* ==========================================================================
   APP STATE & LOGIC
   ========================================================================== */

let currentVideoPage = 1;
let currentSearch = '';
let currentSource = '';

let exploreUid = '';
let explorePage = 1;

document.addEventListener('DOMContentLoaded', () => {
    // Detect page
    const isExplore = document.getElementById('explore-page') !== null;
    
    if (isExplore) {
        initExplorePage();
    } else {
        initIndexPage();
    }
});

/* ================== INDEX PAGE LOGIC ================== */

function initIndexPage() {
    const navExplore = document.getElementById('nav-explore-btn');
    if (navExplore) {
        navExplore.href = (SECRET_PREFIX || '') + '/explore';
    }

    // Tab switching
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            e.target.classList.add('active');
            const targetId = e.target.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
            
            // Load content based on tab
            if (targetId === 'tab-library') loadVideos(1);
            if (targetId === 'tab-uploaders') loadUploaders();
            if (targetId === 'tab-status') loadStatus();
        });
    });

    // Library Events
    document.getElementById('btn-search')?.addEventListener('click', () => {
        currentSearch = document.getElementById('search-input').value.trim();
        currentSource = document.getElementById('filter-source').value;
        loadVideos(1);
    });

    document.getElementById('btn-prev-page')?.addEventListener('click', () => {
        if (currentVideoPage > 1) loadVideos(currentVideoPage - 1);
    });

    document.getElementById('btn-next-page')?.addEventListener('click', () => {
        loadVideos(currentVideoPage + 1);
    });

    // Uploader Events
    document.getElementById('btn-add-uploader')?.addEventListener('click', async () => {
        const mid = document.getElementById('input-uid').value.trim();
        if (!mid) return showToast('请输入UID', 'error');
        
        try {
            await api('/uploaders', { method: 'POST', body: { mid: parseInt(mid) } });
            showToast('添加追踪成功', 'success');
            document.getElementById('input-uid').value = '';
            loadUploaders();
        } catch (e) {
            // Error handled in api wrapper
        }
    });

    // Initial load
    loadVideos(1);
    loadStatus();
    setInterval(loadStatus, 30000); // 30s refresh for status
}

async function loadVideos(page) {
    try {
        currentVideoPage = page;
        const query = new URLSearchParams({
            page: page,
            per_page: 20
        });
        if (currentSearch) query.append('search', currentSearch);
        if (currentSource) query.append('source', currentSource);

        const res = await api(`/videos?${query.toString()}`);
        
        document.getElementById('page-info').innerText = `第 ${res.page} 页 / 共 ${res.pages} 页`;
        const grid = document.getElementById('video-grid');
        grid.innerHTML = '';

        if (!res.videos || res.videos.length === 0) {
            grid.innerHTML = `<div class="empty-state">未找到视频</div>`;
            return;
        }

        res.videos.forEach(video => {
            const card = document.createElement('div');
            card.className = 'card';
            
            const sourceBadge = video.source === 'auto' 
                ? `<span class="badge badge-auto">🤖 自动</span>`
                : `<span class="badge badge-manual">👤 手动</span>`;
                
            let statusBadge = '';
            if (video.status === 'done') statusBadge = `<span class="badge badge-done">✅ 完成</span>`;
            else if (video.status === 'downloading') statusBadge = `<span class="badge badge-downloading">⏳ 下载中</span>`;
            else if (video.status === 'failed') statusBadge = `<span class="badge badge-failed">❌ 失败</span>`;
            else statusBadge = `<span class="badge badge-pending">🕐 等待中</span>`;

            card.innerHTML = `
                <div class="card-thumb" id="thumb-${video.bvid}" onclick="playVideo('${video.bvid}')">
                    <img src="${API_BASE}/thumbnail/${video.bvid}" referrerpolicy="no-referrer" alt="Cover" onerror="this.onerror=null; this.src='${getImageProxyUrl(video.thumbnail_url)}'">
                    <div class="card-duration">${formatDuration(video.duration)}</div>
                </div>
                <div class="card-body">
                    <div class="badge-group">${sourceBadge} ${statusBadge}</div>
                    <div class="card-title" title="${video.title}">${video.title}</div>
                    <div class="card-meta">
                        <span>UP: ${video.uploader_name || video.mid}</span>
                        <span>尺寸: ${formatSize(video.file_size)}</span>
                        <span>时间: ${formatDate(video.downloaded_at || video.upload_time)}</span>
                    </div>
                    <div class="card-actions">
                        ${video.status === 'done' ? `<button class="btn btn-sm btn-primary" onclick="window.open('${API_BASE}/download/${video.bvid}', '_blank')">⬇ 下载文件</button>` : ''}
                        <button class="btn btn-sm btn-secondary" onclick="redownloadVideo('${video.bvid}')" title="重新下载此视频 (4K HEVC/H.264)">🔄 重下</button>
                        <button class="btn btn-sm btn-danger" onclick="deleteVideo('${video.bvid}')">🗑 删除</button>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });

    } catch (e) {
        console.error("Failed to load videos", e);
    }
}

function playVideo(bvid) {
    const thumbContainer = document.getElementById(`thumb-${bvid}`);
    if (!thumbContainer) return;
    
    // Replace content with video player
    thumbContainer.onclick = null;
    thumbContainer.innerHTML = `
        <video class="inline-player" controls autoplay playsinline>
            <source src="${API_BASE}/stream/${bvid}" type="video/mp4" onerror="handleVideoPlayError(this.parentElement, '${bvid}')">
            浏览器不支持视频播放。
        </video>
    `;
    const video = thumbContainer.querySelector('video');
    if (video) {
        video.onerror = () => handleVideoPlayError(thumbContainer, bvid);
    }
}

function handleVideoPlayError(container, bvid) {
    if (!container) return;
    container.innerHTML = `
        <div style="background: rgba(15,23,42,0.95); color: #f87171; padding: 1rem; border-radius: 8px; font-size: 0.85rem; text-align: left; line-height: 1.5; border: 1px solid rgba(239,68,68,0.3);">
            <div style="font-weight: bold; margin-bottom: 0.4rem; font-size: 0.95rem; color: #ef4444;">⚠️ 播放失败：当前设备无法解码该视频</div>
            <div style="color: #cbd5e1; margin-bottom: 0.6rem; font-size: 0.8rem;">常见原因：该视频可能由旧版下载为 AV1 编码（Safari / QuickTime 不支持 AV1 MP4）。</div>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <button class="btn btn-sm btn-primary" onclick="redownloadVideo('${bvid}')">🔄 重新下载 (兼容4K HEVC)</button>
                <button class="btn btn-sm btn-secondary" onclick="window.open('${API_BASE}/download/${bvid}', '_blank')">⬇ 下载原文件</button>
            </div>
        </div>
    `;
}

async function redownloadVideo(bvid) {
    if (!confirm('重新下载将删除旧文件，并从 B 站下载兼容全平台播放的 4K HEVC/H.264 版本，是否继续？')) return;
    try {
        await api(`/videos/${bvid}/redownload`, { method: 'POST' });
        showToast('已加入重新下载队列，正在后台下载...', 'success');
        loadVideos(currentVideoPage);
        loadStatus();
    } catch (e) {
        showToast('重新下载失败: ' + e.message, 'error');
    }
}

async function deleteVideo(bvid) {
    if (!confirm('确定要删除这个视频吗？文件也会被一并删除。')) return;
    try {
        await api(`/videos/${bvid}`, { method: 'DELETE' });
        showToast('删除成功', 'success');
        loadVideos(currentVideoPage);
        loadStatus();
    } catch (e) {}
}

async function loadUploaders() {
    try {
        const res = await api('/uploaders');
        const list = document.getElementById('uploader-list');
        list.innerHTML = '';
        
        if (!res.uploaders || res.uploaders.length === 0) {
            list.innerHTML = `<div class="empty-state">暂无追踪的UP主</div>`;
            return;
        }

        res.uploaders.forEach(up => {
            const item = document.createElement('div');
            item.className = 'list-item';
            
            const fallbackAvatar = `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1' fill='%23334155'%3E%3Crect width='1' height='1'/%3E%3C/svg%3E`;
            const avatarUrl = up.face_url || fallbackAvatar;

            item.innerHTML = `
                <img src="${formatImageUrl(avatarUrl)}" referrerpolicy="no-referrer" class="avatar" alt="Avatar" onerror="this.onerror=null; this.src='${getImageProxyUrl(avatarUrl)}'">
                <div class="list-info">
                    <div style="font-weight: bold; font-size: 1.1rem;">${up.name || '未知UP主'} (UID: ${up.mid})</div>
                    <div style="font-size: 0.875rem; color: var(--text-muted); margin-top: 0.25rem;">
                        视频数: ${up.video_count || 0} | 追踪自: ${formatDate(up.tracked_since)} | 最后检查: ${formatDate(up.last_check)}
                    </div>
                </div>
                <div style="display:flex; gap:0.5rem;">
                    <a href="${SECRET_PREFIX}/explore?mid=${up.mid}" class="btn btn-primary">浏览视频</a>
                    <button class="btn btn-danger" onclick="untrackUploader('${up.mid}')">取消追踪</button>
                </div>
            `;
            list.appendChild(item);
        });
    } catch (e) {
        console.error("Failed to load uploaders", e);
    }
}

async function untrackUploader(mid) {
    if (!confirm('确定要取消追踪该UP主吗？已下载的视频不会被删除。')) return;
    try {
        await api(`/uploaders/${mid}`, { method: 'DELETE' });
        showToast('已取消追踪', 'success');
        loadUploaders();
    } catch (e) {}
}

async function loadStatus() {
    try {
        const res = await api('/status');
        
        // Update Indicator
        const indicator = document.getElementById('status-indicator');
        if (indicator) {
            if (res.poller_running) {
                indicator.classList.add('active');
                indicator.title = 'Poller Running';
            } else {
                indicator.classList.remove('active');
                indicator.title = 'Poller Stopped';
            }
        }
        
        // Update DOM elements if on index
        if (document.getElementById('stat-poller')) {
            document.getElementById('stat-poller').innerText = res.poller_running ? '运行中 ✅' : '已停止 ❌';
            document.getElementById('stat-interval').innerText = `轮询间隔: ${res.poll_interval || 0} 秒`;
            
            if (res.disk) {
                document.getElementById('stat-disk-used').innerText = `${formatSize(res.disk.used)} / ${formatSize(res.disk.total)}`;
                document.getElementById('stat-disk-bar').style.width = `${res.disk.percent || 0}%`;
                
                if (res.disk.percent > 90) {
                    document.getElementById('stat-disk-bar').style.backgroundColor = 'var(--danger-color)';
                } else if (res.disk.percent > 75) {
                    document.getElementById('stat-disk-bar').style.backgroundColor = 'var(--warning-color)';
                } else {
                    document.getElementById('stat-disk-bar').style.backgroundColor = 'var(--primary-color)';
                }
            }
            
            document.getElementById('stat-queue').innerText = res.queue_count || 0;
            document.getElementById('stat-videos').innerText = res.video_count || 0;
        }
    } catch (e) {
        console.error("Failed to load status", e);
    }
}

/* ================== EXPLORE PAGE LOGIC ================== */

window.quickFill = function(val) {
    const input = document.getElementById('explore-input');
    if (input) {
        input.value = val;
        handleExploreQuery();
    }
};

function initExplorePage() {
    const backLink = document.getElementById('back-home-link');
    if (backLink) {
        backLink.href = (SECRET_PREFIX || '') + '/';
    }

    const input = document.getElementById('explore-input');
    const queryBtn = document.getElementById('btn-explore-query');

    queryBtn?.addEventListener('click', () => handleExploreQuery());
    input?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleExploreQuery();
    });

    document.getElementById('btn-explore-prev')?.addEventListener('click', () => {
        if (explorePage > 1 && exploreUid) queryExplore(exploreUid, explorePage - 1);
    });

    document.getElementById('btn-explore-next')?.addEventListener('click', () => {
        if (exploreUid) queryExplore(exploreUid, explorePage + 1);
    });

    // Check query params (?mid=xxx or ?bvid=xxx)
    const urlParams = new URLSearchParams(window.location.search);
    const midParam = urlParams.get('mid');
    const bvidParam = urlParams.get('bvid');
    
    if (bvidParam) {
        if (input) input.value = bvidParam;
        searchByBvid(bvidParam);
    } else if (midParam) {
        if (input) input.value = midParam;
        queryExplore(midParam, 1);
    }
}

function extractBvid(str) {
    if (!str) return null;
    const match = str.match(/BV[a-zA-Z0-9]{10}/i);
    return match ? match[0] : null;
}

function handleExploreQuery() {
    const input = document.getElementById('explore-input');
    if (!input) return;
    const raw = input.value.trim();
    if (!raw) return showToast('请输入BV号或UP主UID', 'info');

    const bvid = extractBvid(raw);
    if (bvid) {
        searchByBvid(bvid);
        return;
    }

    // Check if it's numeric UID
    const digitsOnly = raw.replace(/\D/g, '');
    if (digitsOnly && (raw.length === digitsOnly.length || raw.toLowerCase().includes('space.bilibili.com') || raw.toLowerCase().includes('uid'))) {
        queryExplore(digitsOnly, 1);
        return;
    }

    // Default fallback: if has digits, treat as UID
    if (digitsOnly) {
        queryExplore(digitsOnly, 1);
    } else {
        showToast('未能识别BV号或UID，请检查输入', 'error');
    }
}

/* --- Search Video by BVID --- */
async function searchByBvid(bvid) {
    const bvContainer = document.getElementById('bv-result-container');
    const upContainer = document.getElementById('up-profile-container');
    const videoGrid = document.getElementById('explore-video-grid');
    const pagination = document.getElementById('explore-pagination');

    upContainer.innerHTML = '';
    videoGrid.innerHTML = '';
    pagination.style.display = 'none';

    bvContainer.style.display = 'block';
    bvContainer.innerHTML = `<div class="empty-state">⏳ 正在解析视频 ${bvid} ...</div>`;

    try {
        const res = await api(`/bili/video/${bvid}`);
        const v = res.video;
        const uploader = v.uploader || {};

        let downloadBadge = res.is_downloaded
            ? `<span class="badge badge-done">✅ 已在下载库 (${res.video_status || '完成'})</span>`
            : `<span class="badge badge-pending">未下载到VPS</span>`;

        let trackBadge = res.is_tracked
            ? `<span class="badge badge-auto">📌 该UP主已在追更列表中</span>`
            : `<span class="badge badge-manual">未追更该UP主</span>`;

        bvContainer.innerHTML = `
            <div class="bv-card">
                <div class="bv-card-thumb">
                    <img src="${formatImageUrl(v.pic)}" referrerpolicy="no-referrer" alt="Cover" onerror="this.onerror=null; this.src='${getImageProxyUrl(v.pic)}'">
                    <div class="card-duration">${formatDuration(v.duration)}</div>
                </div>
                <div class="bv-card-content">
                    <div>
                        <div class="badge-group" style="margin-bottom: 0.5rem;">
                            ${downloadBadge}
                            ${trackBadge}
                        </div>
                        <div class="bv-card-title">${v.title}</div>
                        <div class="card-meta" style="margin-top: 0.5rem;">
                            <span>BV号: <b>${v.bvid}</b></span>
                            <span>发布时间: ${formatDate(v.upload_time)}</span>
                            <span>播放量: ${(v.stat?.view || 0).toLocaleString()}</span>
                            <span>点赞: ${(v.stat?.like || 0).toLocaleString()}</span>
                        </div>
                    </div>

                    <div class="bv-uploader-info">
                        <img src="${formatImageUrl(uploader.face_url)}" referrerpolicy="no-referrer" class="bv-uploader-avatar" alt="Avatar" onerror="this.onerror=null; this.src='${getImageProxyUrl(uploader.face_url)}'">
                        <div style="flex-grow: 1;">
                            <div style="font-weight: 600;">${uploader.name || 'UP主'}</div>
                            <div style="font-size: 0.85rem; color: var(--text-muted);">UID: ${uploader.mid}</div>
                        </div>
                        <button class="btn btn-sm btn-secondary" onclick="queryExplore('${uploader.mid}', 1)">浏览TA的全部视频</button>
                    </div>

                    <div class="bv-actions">
                        <button id="btn-dl-only" class="btn btn-success" onclick='triggerBiliAction("download_only", ${JSON.stringify(v).replace(/'/g, "&#39;")}, this)'>
                            ⬇️ 仅下载本视频 (不追更)
                        </button>
                        <button id="btn-track-only" class="btn btn-purple" ${res.is_tracked ? 'disabled' : ''} onclick='triggerBiliAction("track_only", ${JSON.stringify(v).replace(/'/g, "&#39;")}, this)'>
                            ${res.is_tracked ? '✅ 已在追更列表中' : '➕ 仅追踪此UP主 (不下载)'}
                        </button>
                        <button id="btn-dl-track" class="btn btn-gradient" onclick='triggerBiliAction("download_and_track", ${JSON.stringify(v).replace(/'/g, "&#39;")}, this)'>
                            🚀 下载此视频并开启追更
                        </button>
                    </div>
                </div>
            </div>
        `;
    } catch (e) {
        bvContainer.innerHTML = `<div class="empty-state" style="color: var(--danger-color);">❌ 查询视频失败: ${e.message}</div>`;
    }
}

async function triggerBiliAction(action, videoData, btn) {
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = '⏳ 处理中...';

    const uploader = videoData.uploader || {};
    const payload = {
        action: action,
        bvid: videoData.bvid,
        mid: parseInt(uploader.mid || 0),
        title: videoData.title,
        thumbnail_url: videoData.pic,
        duration: videoData.duration || 0,
        upload_time: videoData.upload_time,
        description: videoData.description || '',
        uploader_name: uploader.name,
        uploader_face: uploader.face_url
    };

    try {
        const res = await api('/bili/action', {
            method: 'POST',
            body: payload
        });
        showToast(res.message || '操作成功', 'success');
        // Refresh BV card to update states
        setTimeout(() => searchByBvid(videoData.bvid), 600);
    } catch (e) {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

/* --- Search UP by UID --- */
async function queryExplore(mid, page) {
    const bvContainer = document.getElementById('bv-result-container');
    const profileContainer = document.getElementById('up-profile-container');
    const grid = document.getElementById('explore-video-grid');
    const pag = document.getElementById('explore-pagination');

    bvContainer.style.display = 'none';
    profileContainer.innerHTML = `<div class="empty-state">⏳ 正在获取UP主 UID: ${mid} 的资料与投稿...</div>`;
    grid.innerHTML = '';
    pag.style.display = 'none';

    exploreUid = mid;
    explorePage = page;

    try {
        const res = await api(`/explore/${mid}?pn=${page}&ps=20`);

        // Render Profile Card with dedicated Tracking Action
        if (res.uploader) {
            const isTracked = res.is_tracked;
            profileContainer.innerHTML = `
                <div class="up-profile" style="justify-content: space-between; flex-wrap: wrap;">
                    <div style="display: flex; align-items: center; gap: 1.5rem;">
                        <img src="${formatImageUrl(res.uploader.face_url)}" referrerpolicy="no-referrer" class="avatar" style="width:80px; height:80px;" onerror="this.onerror=null; this.src='${getImageProxyUrl(res.uploader.face_url)}'">
                        <div>
                            <h2 style="margin-bottom: 0.25rem;">${res.uploader.name}</h2>
                            <div style="color: var(--text-muted);">UID: ${mid} · 总投稿数: ${res.page?.count || 0}</div>
                        </div>
                    </div>
                    <div style="display: flex; gap: 1rem; align-items: center;">
                        <button id="btn-toggle-up" class="btn ${isTracked ? 'btn-secondary' : 'btn-purple'}" onclick="toggleUploaderTrack(${mid}, this)">
                            ${isTracked ? '✅ 正在追更此UP主 (点击取消)' : '➕ 开启此UP主自动追更'}
                        </button>
                    </div>
                </div>
            `;
        }

        // Render Pagination info
        const totalPages = Math.ceil((res.page?.count || 0) / (res.page?.ps || 20));
        if (totalPages > 1) {
            pag.style.display = 'flex';
            document.getElementById('explore-page-info').innerText = `第 ${res.page.pn} 页 / 共 ${totalPages} 页 (总共 ${res.page.count} 个视频)`;
            document.getElementById('btn-explore-prev').disabled = (res.page.pn <= 1);
            document.getElementById('btn-explore-next').disabled = (res.page.pn >= totalPages);
        }

        // Render Videos
        grid.innerHTML = '';
        if (!res.videos || res.videos.length === 0) {
            grid.innerHTML = `<div class="empty-state">未找到视频投稿</div>`;
            return;
        }

        res.videos.forEach(video => {
            const card = document.createElement('div');
            card.className = 'card';

            const isDownloaded = video.downloaded;
            const actionBtn = isDownloaded
                ? `<button class="btn btn-sm btn-secondary" disabled>✅ 已在库中</button>`
                : `<button class="btn btn-sm btn-primary" onclick='triggerDownload(${JSON.stringify({
                    bvid: video.bvid,
                    mid: parseInt(mid),
                    title: video.title,
                    thumbnail_url: video.pic,
                    duration: video.duration || 0,
                    upload_time: video.created
                }).replace(/'/g, "&#39;")}, this)'>⬇ 下载到VPS</button>`;

            card.innerHTML = `
                <div class="card-thumb">
                    <img src="${formatImageUrl(video.pic)}" referrerpolicy="no-referrer" alt="Cover" onerror="this.onerror=null; this.src='${getImageProxyUrl(video.pic)}'">
                    <div class="card-duration">${video.length || formatDuration(video.duration)}</div>
                </div>
                <div class="card-body">
                    <div class="card-title" title="${video.title}">${video.title}</div>
                    <div class="card-meta">
                        <span>BV号: ${video.bvid}</span>
                        <span>发布时间: ${formatDate(video.created)}</span>
                        <span>播放量: ${(video.play || 0).toLocaleString()}</span>
                    </div>
                    <div class="card-actions">
                        ${actionBtn}
                        <button class="btn btn-sm btn-secondary" onclick="searchByBvid('${video.bvid}')">🔍 详情 / 追更</button>
                    </div>
                </div>
            `;
            grid.appendChild(card);
        });

    } catch (e) {
        profileContainer.innerHTML = `<div class="empty-state" style="color: var(--danger-color);">❌ 获取UP主资料失败: ${e.message}</div>`;
    }
}

async function toggleUploaderTrack(mid, btn) {
    try {
        btn.disabled = true;
        const res = await api('/uploaders/toggle', {
            method: 'POST',
            body: { mid: parseInt(mid) }
        });
        showToast(res.message, 'success');
        btn.disabled = false;
        if (res.is_tracked) {
            btn.className = 'btn btn-secondary';
            btn.innerText = '✅ 正在追更此UP主 (点击取消)';
        } else {
            btn.className = 'btn btn-purple';
            btn.innerText = '➕ 开启此UP主自动追更';
        }
    } catch (e) {
        btn.disabled = false;
    }
}

async function triggerDownload(videoData, btnElement) {
    try {
        btnElement.innerText = "⏳ 提交中...";
        btnElement.disabled = true;
        
        await api('/explore/download', {
            method: 'POST',
            body: videoData
        });
        
        showToast('已加入下载队列', 'success');
        btnElement.innerText = "⏳ 下载中";
        btnElement.classList.replace('btn-primary', 'btn-secondary');
    } catch (e) {
        btnElement.innerText = "⬇ 下载到VPS";
        btnElement.disabled = false;
    }
}
