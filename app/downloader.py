import yt_dlp
import asyncio
import os
import logging
import subprocess
from typing import Dict, Any, Optional
from app.disk import ensure_disk_space
from app.cookie_helper import get_netscape_cookie_path

log = logging.getLogger("bilidown.downloader")

def get_format_selector(preferred_quality: int = 2160) -> str:
    """
    Format selection string for Bilibili:
    Prioritize HEVC (hev1/hvc1) and AVC (avc1) up to preferred_quality, strictly excluding AV1 (av01/av1)
    because Apple QuickTime Player and Safari do not support AV1 in MP4 containers.
    Fallback to any codec only if no non-AV1 streams exist.
    """
    return (
        f"bestvideo[height<={preferred_quality}][vcodec!*='av01'][vcodec!*='av1']+bestaudio/"
        f"bestvideo[height<={preferred_quality}]+bestaudio/best"
    )

def ensure_mp4_compatibility(file_path: str) -> None:
    """
    Ensure the MP4 file is compatible with Apple QuickTime, Safari, and browsers.
    If the video stream is HEVC (H.265) but tagged as hev1 (Bilibili's default),
    Apple QuickTime Player and Safari will refuse to decode it (error: '不兼容的部分媒体').
    Remuxing to tag 'hvc1' with -movflags +faststart fixes this instantly without re-encoding.
    """
    if not os.path.exists(file_path):
        return

    try:
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,codec_tag_string",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        if not lines:
            return

        codec_name = lines[0].lower()
        tag_string = lines[1].lower() if len(lines) > 1 else ""

        if "hevc" in codec_name and tag_string != "hvc1":
            log.info(f"Remuxing HEVC video {file_path} from tag '{tag_string}' to 'hvc1' for QuickTime/Safari compatibility")
            temp_path = f"{file_path}.remux.mp4"
            remux_cmd = [
                "ffmpeg", "-y", "-i", file_path,
                "-c", "copy",
                "-tag:v", "hvc1",
                "-movflags", "+faststart",
                temp_path
            ]
            remux_res = subprocess.run(remux_cmd, capture_output=True, text=True, timeout=120)
            if remux_res.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                os.replace(temp_path, file_path)
                log.info(f"Successfully remuxed {file_path} with hvc1 tag")
            else:
                log.warning(f"Failed to remux {file_path}: {remux_res.stderr}")
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
        elif "av1" in codec_name or "av01" in tag_string:
            log.warning(f"Video {file_path} is encoded in AV1, which is incompatible with Safari and macOS QuickTime Player.")
    except Exception as e:
        log.warning(f"Could not check or fix MP4 compatibility for {file_path}: {e}")

def _extract_info(url: str, cookies_file: str, preferred_quality: int = 2160) -> Dict[str, Any]:
    cookiefile = get_netscape_cookie_path(cookies_file)
    opts = {
        "format": get_format_selector(preferred_quality),
        "cookiefile": cookiefile,
        "quiet": True,
        "no_warnings": True
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

async def extract_video_info(url: str, cookies_file: str, preferred_quality: int = 2160) -> Dict[str, Any]:
    return await asyncio.to_thread(_extract_info, url, cookies_file, preferred_quality)

def _download(url: str, config, progress_callback=None) -> Dict[str, Any]:
    quality = get_format_selector(config.preferred_quality)
    cookiefile = get_netscape_cookie_path(config.cookies_file)
    
    opts = {
        "format": quality,
        "format_sort": ["res", "fps", "vcodec:hevc", "vcodec:h264"],
        "merge_output_format": "mp4",
        "outtmpl": f"{config.download_dir}/%(title)s_%(id)s.%(ext)s",
        "cookiefile": cookiefile,
        "writethumbnail": True,
        "noplaylist": True,
        "postprocessor_args": {"merger": ["-movflags", "+faststart"]},
        "quiet": True,
        "no_warnings": True
    }

    if progress_callback:
        opts["progress_hooks"] = [progress_callback]

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # yt-dlp prepare_filename gives the raw video filename, need to account for merge to mp4
        base_name = ydl.prepare_filename(info).rsplit(".", 1)[0]
        file_path = f"{base_name}.mp4"
        
        # fallback if mp4 is not the final extension (e.g., if it was already mp4 and didn't merge)
        if not os.path.exists(file_path):
            file_path = ydl.prepare_filename(info)

        # Ensure MP4 compatibility (hvc1 tag for HEVC in QuickTime / Safari)
        ensure_mp4_compatibility(file_path)

        return {
            "file_path": file_path,
            "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "quality": f"{info.get('height', '?')}p",
        }

async def download_video(bvid: str, config, db, source: str = "auto", progress_callback=None) -> Dict[str, Any]:
    url = f"https://www.bilibili.com/video/{bvid}"
    
    try:
        log.info(f"Extracting info for {bvid}")
        info = await extract_video_info(url, config.cookies_file, config.preferred_quality)
        
        # yt-dlp filesize and filesize_approx are already in bytes
        raw_size = info.get("filesize") or info.get("filesize_approx")
        if raw_size and raw_size > 0:
            estimated_size = int(raw_size)
        else:
            # Fallback default: 300MB
            estimated_size = 300 * 1024 * 1024
            
        log.info(f"Ensuring disk space for {bvid}, estimated {estimated_size / (1024 * 1024):.1f} MB ({estimated_size} bytes)")
        await ensure_disk_space(estimated_size, config.download_dir, db, config.disk_reserve_mb)
        
        await db.update_video_status(bvid, "downloading")
        log.info(f"Starting download for {bvid}")
        
        result = await asyncio.to_thread(_download, url, config, progress_callback)
        
        await db.update_video_done(
            bvid=bvid,
            file_path=result["file_path"],
            file_size=result["file_size"],
            quality=result["quality"],
            source=source
        )
        log.info(f"Successfully downloaded {bvid} to {result['file_path']}")
        return result
        
    except Exception as e:
        log.error(f"Failed to download {bvid}: {str(e)}")
        await db.update_video_status(bvid, "failed", error_message=str(e))
        raise
