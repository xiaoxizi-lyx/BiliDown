import os
import sys
import argparse
import asyncio
import subprocess
import logging
from app.config import load_config
from app.database import Database
from app.downloader import ensure_mp4_compatibility, download_video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("bilidown.repair")

def probe_video(file_path: str):
    """Probe video stream codec and tag using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,codec_tag_string,width,height",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
        codec = lines[0].lower() if len(lines) > 0 else "unknown"
        tag = lines[1].lower() if len(lines) > 1 else ""
        width = lines[2] if len(lines) > 2 else "?"
        height = lines[3] if len(lines) > 3 else "?"
        return {
            "codec": codec,
            "tag": tag,
            "resolution": f"{width}x{height}",
            "raw": lines
        }
    except Exception as e:
        return {"error": str(e), "codec": "error", "tag": ""}

async def repair_all(redownload_av1: bool = False, transcode_av1: bool = False):
    config = load_config()
    video_dir = config.download_dir
    
    if not os.path.isdir(video_dir):
        log.error(f"Download directory {video_dir} does not exist.")
        return

    db = Database()
    await db.init()

    log.info(f"Scanning video directory: {video_dir}")
    files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
    
    if not files:
        log.info("No MP4 files found.")
        return

    log.info(f"Found {len(files)} MP4 file(s). Inspecting codecs...")
    
    for filename in sorted(files):
        file_path = os.path.join(video_dir, filename)
        info = probe_video(file_path)
        
        if "error" in info:
            log.warning(f"[{filename}] Probe error: {info['error']}")
            continue

        codec = info["codec"]
        tag = info["tag"]
        res = info["resolution"]
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        
        # Extract bvid from filename (usually title_bvid.mp4)
        bvid = None
        base = filename.rsplit(".", 1)[0]
        if "_" in base:
            possible_bvid = base.rsplit("_", 1)[1]
            if possible_bvid.startswith("BV"):
                bvid = possible_bvid

        log.info(f"[{filename}] Codec: {codec}, Tag: {tag}, Res: {res}, Size: {size_mb:.1f}MB")

        # Case 1: HEVC with non-hvc1 tag (e.g. hev1)
        if "hevc" in codec and tag != "hvc1":
            log.info(f"  -> Remuxing HEVC '{tag}' to 'hvc1' for QuickTime/Safari playback...")
            ensure_mp4_compatibility(file_path)
            new_info = probe_video(file_path)
            log.info(f"  -> Result: Codec: {new_info['codec']}, Tag: {new_info['tag']} [OK]")
            if bvid:
                new_size = os.path.getsize(file_path)
                try:
                    await db.execute(
                        "UPDATE videos SET file_size = ? WHERE bvid = ?",
                        (new_size, bvid)
                    )
                except Exception:
                    pass

        # Case 2: AV1
        elif "av1" in codec or "av01" in tag:
            log.warning(f"  -> WARNING: AV1 encoding is incompatible with macOS QuickTime Player and Safari!")
            
            if redownload_av1 and bvid:
                log.info(f"  -> Redownloading {bvid} in 4K HEVC from Bilibili...")
                try:
                    os.remove(file_path)
                    await download_video(bvid, config, db, source="manual")
                    log.info(f"  -> Successfully re-downloaded {bvid} in compatible format!")
                except Exception as e:
                    log.error(f"  -> Failed to re-download {bvid}: {e}")
            elif transcode_av1:
                log.info(f"  -> Transcoding AV1 to HEVC (hvc1)... This may take some time.")
                temp_trans = f"{file_path}.transcode.mp4"
                cmd = [
                    "ffmpeg", "-y", "-i", file_path,
                    "-c:v", "libx265", "-crf", "20", "-preset", "fast",
                    "-tag:v", "hvc1",
                    "-c:a", "copy",
                    "-movflags", "+faststart",
                    temp_trans
                ]
                res = subprocess.run(cmd)
                if res.returncode == 0 and os.path.exists(temp_trans):
                    os.replace(temp_trans, file_path)
                    log.info(f"  -> Successfully transcoded {filename} to HEVC hvc1!")
                else:
                    log.error(f"  -> Transcode failed for {filename}")
            else:
                log.info(f"  -> Tip: Run with --redownload-av1 to re-download from Bilibili in 4K HEVC, or delete and re-download in Web UI.")

        # Case 3: H.264 (AVC) or HEVC (hvc1)
        else:
            log.info(f"  -> Compatible format ({codec}/{tag}). No changes needed.")

    await db.close()
    log.info("Finished scan and repair.")

def main():
    parser = argparse.ArgumentParser(description="BiliDown video compatibility checker and repair tool")
    parser.add_argument("--redownload-av1", action="store_true", help="Automatically re-download AV1 videos in 4K HEVC from B站")
    parser.add_argument("--transcode-av1", action="store_true", help="Transcode AV1 videos to HEVC using ffmpeg (slow)")
    args = parser.parse_args()

    asyncio.run(repair_all(redownload_av1=args.redownload_av1, transcode_av1=args.transcode_av1))

if __name__ == "__main__":
    main()
