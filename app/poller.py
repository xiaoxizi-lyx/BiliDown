import asyncio
import logging
from datetime import datetime
from app.wbi import fetch_creator_videos
from app.downloader import download_video

log = logging.getLogger("bilidown.poller")

class Poller:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self._task = None
        self._running = False

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())
            log.info("Poller started")

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            log.info("Poller stopped")

    @property
    def is_running(self):
        return self._running and self._task and not self._task.done()

    async def _poll_loop(self):
        while self._running:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Error in poll loop: {e}")
            
            # Sleep for interval
            interval = self.config.poll_interval_minutes * 60
            await asyncio.sleep(interval)

    async def poll_once(self):
        log.info("Starting poll cycle")
        tracked = await self.db.get_tracked_uploaders()
        
        for up in tracked:
            log.info(f"Checking updates for uploader {up['name']} (mid: {up['mid']})")
            
            try:
                data = await fetch_creator_videos(up["mid"], page=1, page_size=20)
                videos = data.get("list", {}).get("vlist", [])
                
                tracked_since_str = up["tracked_since"]
                # Parse datetime string from sqlite
                if isinstance(tracked_since_str, str):
                    try:
                        tracked_since = datetime.fromisoformat(tracked_since_str)
                    except ValueError:
                        # Fallback for old sqlite format
                        tracked_since = datetime.strptime(tracked_since_str, "%Y-%m-%d %H:%M:%S")
                else:
                    tracked_since = tracked_since_str
                
                for v in videos:
                    upload_time = datetime.fromtimestamp(v["created"])
                    
                    if upload_time <= tracked_since:
                        continue
                        
                    if await self.db.video_exists(v["bvid"]):
                        continue
                        
                    log.info(f"Found new video {v['bvid']} from {up['name']}")
                    await self.db.insert_video(v, source="auto", status="pending")
                    
                await self.db.update_last_check(up["mid"])
                
            except Exception as e:
                log.error(f"Failed to process uploader {up['mid']}: {e}")
                
            await asyncio.sleep(2) # rate limit friendly
            
        # Process pending downloads
        pending = await self.db.get_pending_videos(limit=self.config.max_concurrent_downloads)
        
        for video in pending:
            asyncio.create_task(self._safe_download(video))

    async def _safe_download(self, video):
        try:
            await download_video(video["bvid"], self.config, self.db, source=video["source"])
        except Exception as e:
            log.error(f"Background download failed for {video['bvid']}: {e}")
