#!/usr/bin/env python3
"""
ZAM Bootstrap Script for Ruijie Switches
This runs ON the switch via cli-python insmod
"""

import os
import sys
import urllib.request
import urllib.error
import json
import hashlib
import time
import logging
from datetime import datetime

# Configuration - read from environment with fallbacks
ZAM_SERVER = os.environ.get("ZAM_SERVER", "192.168.1.100")
ZAM_API_PORT = os.environ.get("ZAM_API_PORT", "8000")
TFTP_SERVER = os.environ.get("TFTP_SERVER", ZAM_SERVER)
LOG_FILE = os.environ.get("ZAM_LOG_FILE", "/flash/zam.log")

# Retry configuration
MAX_RETRIES = int(os.environ.get("ZAM_MAX_RETRIES", "5"))
RETRY_DELAY_BASE = int(os.environ.get("ZAM_RETRY_DELAY", "5"))

def log(msg):
    """Simple logging"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] ZAM: {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

def get_serial():
    """Get device serial number"""
    try:
        with os.popen("show version | include Serial") as f:
            line = f.read()
            parts = line.split(":")
            if len(parts) > 1:
                return parts[1].strip()
    except Exception as e:
        log(f"Error getting serial: {e}")
    return "UNKNOWN"

def get_mac():
    """Get management MAC address"""
    try:
        with os.popen("show interface vlan 1 | include address") as f:
            for line in f:
                if "address" in line:
                    parts = line.split()
                    for p in parts:
                        if ":" in p:
                            return p.strip()
    except Exception as e:
        log(f"Error getting MAC: {e}")
    return "00:00:00:00:00:00"

def get_ip():
    """Get current IP address"""
    try:
        with os.popen("show interface vlan 1 | include inet") as f:
            line = f.read()
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "inet":
                    return parts[i+1].split("/")[0]
    except Exception as e:
        log(f"Error getting IP: {e}")
    return "0.0.0.0"

def execute_cli(cmd):
    """Execute a CLI command"""
    try:
        with os.popen(f"cli {cmd}") as f:
            return f.read()
    except Exception as e:
        log(f"CLI error: {e}")
        return ""

def http_request(url, data=None, method="GET", max_retries=None):
    """Make HTTP request to provisioner with retry logic"""
    max_retries = max_retries or MAX_RETRIES
    delay = RETRY_DELAY_BASE
    
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode() if data else None,
                headers={"Content-Type": "application/json"},
                method=method
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            # HTTP errors (4xx, 5xx) - do not retry 4xx
            if 400 <= e.code < 500:
                log(f"HTTP error {e.code}: {e.reason}")
                return None
            log(f"HTTP {e.code} error (attempt {attempt+1}/{max_retries}): {e.reason}")
        except Exception as e:
            log(f"HTTP error (attempt {attempt+1}/{max_retries}): {e}")
        
        if attempt < max_retries - 1:
            log(f"Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2  # Exponential backoff
    
    log(f"Max retries ({max_retries}) exceeded for {url}")
    return None

def register_device(sn, mac, ip):
    """Register device with provisioner"""
    url = f"http://{ZAM_SERVER}:{ZAM_API_PORT}/register"
    data = {"sn": sn, "mac": mac, "ip": ip}
    
    log(f"Registering device: {sn}")
    resp = http_request(url, data, "POST")
    
    if resp:
        log(f"Registered: {resp}")
        return True
    return False

def get_config(sn):
    """Get configuration from provisioner"""
    url = f"http://{ZAM_SERVER}:{ZAM_API_PORT}/config/{sn}"
    
    log(f"Getting config for {sn}")
    resp = http_request(url)
    
    if resp:
        log(f"Got config deployment_id={resp.get('deployment_id')}")
        return resp
    return None

def download_files(files_config, sn):
    """Download config files via TFTP"""
    downloaded = []
    
    for file_type, remote_path in files_config.items():
        local_path = f"/flash/poap_{file_type}.tmp"
        tftp_url = f"tftp://{TFTP_SERVER}{remote_path}"
        
        log(f"Downloading {file_type}: {tftp_url} -> {local_path}")
        
        try:
            # Use CLI copy command
            result = execute_cli(f"copy {tftp_url} {local_path}")
            log(f"Download result: {result[:200]}")
            downloaded.append((file_type, local_path, remote_path))
        except Exception as e:
            log(f"Download failed: {e}")
            return None
    
    return downloaded

def apply_config(cfg_file):
    """Apply configuration file with validation"""
    log(f"Applying config from {cfg_file}")
    
    # Validate config file before applying
    if not os.path.exists(cfg_file):
        log(f"ERROR: Config file does not exist: {cfg_file}")
        return False
    
    try:
        file_stat = os.stat(cfg_file)
        if file_stat.st_size == 0:
            log(f"ERROR: Config file is empty: {cfg_file}")
            return False
        
        with open(cfg_file, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
        
        min_lines = int(os.environ.get("ZAM_MIN_CONFIG_LINES", "5"))
        if len(lines) < min_lines:
            log(f"ERROR: Config file has only {len(lines)} lines, minimum is {min_lines}")
            return False
        
        log(f"Config validation passed: {len(lines)} lines, {file_stat.st_size} bytes")
    except Exception as e:
        log(f"ERROR: Failed to validate config file: {e}")
        return False
    
    try:
        # Copy to startup-config
        result = execute_cli(f"copy {cfg_file} startup-config")
        log(f"Copied to startup-config: {result[:200]}")
        
        # Validate (optional)
        result = execute_cli("show startup-config")
        log(f"Config lines: {len(result.splitlines())}")
        
        return True
    except Exception as e:
        log(f"Apply config failed: {e}")
        return False

def report_status(deployment_id, status, report=None):
    """Report deployment status back to provisioner"""
    url = f"http://{ZAM_SERVER}:{ZAM_API_PORT}/callback/{deployment_id}"
    data = {"status": status, "report": report or {}}
    
    log(f"Reporting status: {status}")
    resp = http_request(url, data, "POST")
    return resp is not None

def upload_logs(sn):
    """Upload ZAM logs to server"""
    try:
        if os.path.exists(LOG_FILE):
            tftp_url = f"tftp://{TFTP_SERVER}/POAP_LOG/{sn}.log"
            result = execute_cli(f"copy {LOG_FILE} {tftp_url}")
            log(f"Log upload: {result[:100]}")
    except Exception as e:
        log(f"Log upload failed: {e}")

def main():
    """Main ZAM workflow"""
    log("=" * 50)
    log("ZAM v2 Bootstrap Starting")
    log("=" * 50)
    
    # Step 1: Get device identity
    sn = get_serial()
    mac = get_mac()
    ip = get_ip()
    
    log(f"Device SN: {sn}")
    log(f"Device MAC: {mac}")
    log(f"Device IP: {ip}")
    
    # Step 2: Register with provisioner
    if not register_device(sn, mac, ip):
        log("Registration failed, will retry on next boot")
        return 1
    
    # Step 3: Get configuration
    config_response = get_config(sn)
    if not config_response:
        log("Failed to get configuration")
        return 1
    
    deployment_id = config_response.get("deployment_id")
    files = config_response.get("files", {})
    config_data = config_response.get("config", {})
    
    # Step 4: Report applying status
    report_status(deployment_id, "applying", {"step": "downloading_files"})
    
    # Step 5: Download files
    downloaded = download_files(files, sn)
    if not downloaded:
        log("File download failed")
        report_status(deployment_id, "failed", {"error": "download_failed"})
        return 1
    
    # Step 6: Apply config
    report_status(deployment_id, "applying", {"step": "applying_config"})
    
    # Find the cfg file in downloads
    cfg_file = None
    for ftype, local, remote in downloaded:
        if ftype == "config":
            cfg_file = local
            break
    
    if cfg_file and apply_config(cfg_file):
        # Step 7: Upload logs
        upload_logs(sn)
        
        # Step 8: Report success
        report_status(deployment_id, "done", {
            "files_downloaded": len(downloaded),
            "reboot_scheduled": True
        })
        
        log("Configuration applied successfully")
        
        # Check if user wants to skip auto-reboot (for testing)
        if os.environ.get("ZAM_SKIP_RELOAD", "").lower() in ("1", "true", "yes"):
            log("ZAM_SKIP_RELOAD set, skipping reload. Manual reload required.")
            upload_logs(sn)
            report_status(deployment_id, "done", {
                "files_downloaded": len(downloaded),
                "reboot_scheduled": False,
                "skip_reload": True
            })
            return 0
        
        # Otherwise auto-reboot
        log("Rebooting in 5 seconds...")
        upload_logs(sn)
        time.sleep(5)
        execute_cli("reload force")
    else:
        report_status(deployment_id, "failed", {
            "error": "config_apply_failed",
            "cfg_file": cfg_file
        })
        return 1
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"FATAL ERROR: {e}")
