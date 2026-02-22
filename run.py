#!/usr/bin/env python3
"""
ZAM v2 Provisioner - Main Entry Point
Starts both HTTP API and TFTP server
"""

import subprocess
import sys
import os
import signal
import socket
import time
import configparser
from pathlib import Path

# Configuration - environment variables with fallbacks
HTTP_PORT = int(os.environ.get("ZAM_HTTP_PORT", "8000"))
TFTP_PORT = int(os.environ.get("ZAM_TFTP_PORT", "69"))
HTTP_HOST = os.environ.get("ZAM_HTTP_HOST", "0.0.0.0")
TFTP_HOST = os.environ.get("ZAM_TFTP_HOST", "0.0.0.0")

# Optional config file support
def load_config():
    """Load configuration from zam.conf if it exists"""
    config = configparser.ConfigParser()
    config_path = Path(__file__).parent / "zam.conf"
    
    if config_path.exists():
        config.read(config_path)
        global HTTP_PORT, TFTP_PORT, HTTP_HOST, TFTP_HOST
        
        if config.has_option('server', 'http_port'):
            HTTP_PORT = config.getint('server', 'http_port')
        if config.has_option('server', 'tftp_port'):
            TFTP_PORT = config.getint('server', 'tftp_port')
        if config.has_option('server', 'http_host'):
            HTTP_HOST = config.get('server', 'http_host')
        if config.has_option('server', 'tftp_host'):
            TFTP_HOST = config.get('server', 'tftp_host')
        
        print(f"[+] Loaded configuration from zam.conf")

# Process tracking
processes = []

def check_tftp_health(host="0.0.0.0", port=69, timeout=2):
    """Check if TFTP server is responding"""
    try:
        # Send a TFTP read request (will fail but confirms server listening)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(b'\x00\x01test\x00octet\x00', (host, port))
        sock.close()
        return True
    except socket.timeout:
        # Timeout means server is listening but no response (expected)
        return True
    except Exception as e:
        print(f"[!] TFTP health check error: {e}")
        return False

def check_http_health(host="localhost", port=8000, timeout=5):
    """Check if HTTP server is responding"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout)
        return True
    except Exception as e:
        print(f"[!] HTTP health check error: {e}")
        return False

def graceful_shutdown(signum=None, frame=None):
    """Handle shutdown signals gracefully"""
    print("\n[!] Shutdown signal received, stopping servers...")
    
    for proc in processes:
        if proc and proc.poll() is None:
            print(f"[*] Terminating process {proc.pid}...")
            proc.terminate()
    
    # Wait for processes to terminate
    deadline = time.time() + 10
    for proc in processes:
        if proc and proc.poll() is None:
            remaining = deadline - time.time()
            if remaining > 0:
                try:
                    proc.wait(timeout=min(remaining, 5))
                except subprocess.TimeoutExpired:
                    print(f"[!] Force killing process {proc.pid}...")
                    proc.kill()
    
    print("[+] All servers stopped")
    sys.exit(0)

def main():
    """Start both API and TFTP servers"""
    global processes
    
    # Load config file if exists
    load_config()
    
    project_root = Path(__file__).parent
    
    print("=" * 60)
    print("ZAM v2 Provisioner")
    print("=" * 60)
    print(f"[*] Configuration:")
    print(f"    HTTP: {HTTP_HOST}:{HTTP_PORT}")
    print(f"    TFTP: {TFTP_HOST}:{TFTP_PORT}")
    print("=" * 60)
    
    # Change to project directory
    os.chdir(project_root)
    
    # Ensure TFTP directories exist
    (project_root / "files" / "POAP_CFG").mkdir(parents=True, exist_ok=True)
    (project_root / "files" / "POAP_IMAGE").mkdir(parents=True, exist_ok=True)
    (project_root / "files" / "POAP_STARTUP").mkdir(parents=True, exist_ok=True)
    (project_root / "files" / "POAP_LOG").mkdir(parents=True, exist_ok=True)
    (project_root / "files" / "POAP_STATUS").mkdir(parents=True, exist_ok=True)
    
    # Copy zam.py to TFTP root
    zam_src = project_root / "scripts" / "zam.py"
    zam_dst = project_root / "files" / "zam.py"
    if zam_src.exists() and not zam_dst.exists():
        import shutil
        shutil.copy(zam_src, zam_dst)
        print(f"[+] Copied zam.py to TFTP root")
    
    # Set up signal handlers
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    
    # Start TFTP server (background)
    print(f"\n[*] Starting TFTP server on {TFTP_HOST}:{TFTP_PORT}...")
    tftp_process = subprocess.Popen(
        [sys.executable, "tftp/server.py", "--port", str(TFTP_PORT), "--host", TFTP_HOST],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    processes.append(tftp_process)
    
    # Wait and verify TFTP started
    time.sleep(2)
    
    # Check if TFTP process is still running
    if tftp_process.poll() is not None:
        print("[!] ERROR: TFTP server process exited unexpectedly")
        stdout, _ = tftp_process.communicate()
        if stdout:
            print(f"    Output: {stdout.decode()[:500]}")
        graceful_shutdown()
        sys.exit(1)
    
    # Health check TFTP server
    if check_tftp_health(TFTP_HOST, TFTP_PORT):
        print(f"[+] TFTP server healthy on port {TFTP_PORT}")
    else:
        print("[!] WARNING: TFTP health check failed, but process is running")
    
    # Start HTTP API
    print(f"[*] Starting HTTP API on {HTTP_HOST}:{HTTP_PORT}...")
    
    api_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", 
         "--host", HTTP_HOST, "--port", str(HTTP_PORT), "--reload"],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    processes.append(api_process)
    
    # Wait for HTTP server to start
    time.sleep(2)
    
    # Check if API process is still running
    if api_process.poll() is not None:
        print("[!] ERROR: HTTP API process exited unexpectedly")
        graceful_shutdown()
        sys.exit(1)
    
    # Health check HTTP server
    max_http_retries = 5
    for attempt in range(max_http_retries):
        if check_http_health("localhost", HTTP_PORT):
            print(f"[+] HTTP API healthy on port {HTTP_PORT}")
            break
        print(f"[*] HTTP health check attempt {attempt + 1}/{max_http_retries} failed, retrying...")
        time.sleep(2)
    else:
        print("[!] WARNING: HTTP health check failed after all retries")
    
    print("\n" + "=" * 60)
    print("Running! Ctrl+C to stop.")
    print("=" * 60 + "\n")
    
    try:
        # Wait for interrupt
        api_process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        graceful_shutdown()

if __name__ == "__main__":
    main()
