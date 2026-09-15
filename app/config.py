import os
import yaml
import secrets
import string
from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class Config:
    secret_path: str = ""
    tls_cert: str = "./certs/origin.pem"
    tls_key: str = "./certs/origin-key.pem"
    port: int = 8443
    cookies_file: str = "./cookies.txt"
    download_dir: str = "./data/videos"
    preferred_quality: int = 2160
    max_concurrent_downloads: int = 2
    poll_interval_minutes: int = 5
    tracked_uploaders: List[Dict[str, Any]] = field(default_factory=list)
    disk_reserve_mb: int = 500

def load_config(config_path: str = "config.yaml") -> Config:
    if not os.path.exists(config_path):
        return Config()
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Auto-generate secret_path if empty
    secret_path = data.get("secret_path", "")
    if not secret_path:
        secret_path = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
        data["secret_path"] = secret_path
        
        # Write back to file
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    config = Config(
        secret_path=secret_path,
        tls_cert=data.get("tls_cert", "./certs/origin.pem"),
        tls_key=data.get("tls_key", "./certs/origin-key.pem"),
        port=data.get("port", 8443),
        cookies_file=data.get("cookies_file", "./cookies.txt"),
        download_dir=data.get("download_dir", "./data/videos"),
        preferred_quality=data.get("preferred_quality", 2160),
        max_concurrent_downloads=data.get("max_concurrent_downloads", 2),
        poll_interval_minutes=data.get("poll_interval_minutes", 5),
        tracked_uploaders=data.get("tracked_uploaders", []),
        disk_reserve_mb=data.get("disk_reserve_mb", 500)
    )
    return config
