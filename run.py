#!/usr/bin/env python3
"""
ZAM v2 Provisioner - Main Entry Point
Starts both HTTP API and TFTP server
"""

import subprocess
import sys
import os
import signal
from pathlib import Path

def main():
    """Start both API and TFTP servers"""
    project_root = Path(__file__).parent
    
    print("=" * 60)
    print("ZAM v2 Provisioner")
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
    
    # Start TFTP server (background)
    print("\n[*] Starting TFTP server on port 69...")
    tftp_process = subprocess.Popen(
        [sys.executable, "tftp/server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    
    # Give TFTP a moment to start
    import time
    time.sleep(1)
    
    # Start HTTP API
    print("[*] Starting HTTP API on port 8000...")
    print("\n" + "=" * 60)
    print("Running! Ctrl+C to stop.")
    print("=" * 60 + "\n")
    
    try:
        api_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.main:app", 
             "--host", "0.0.0.0", "--port", "8000", "--reload"],
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        
        # Wait for interrupt
        api_process.wait()
    except KeyboardInterrupt:
        print("\n[!] Stopping servers...")
    finally:
        tftp_process.terminate()
        try:
            tftp_process.wait(timeout=5)
        except:
            tftp_process.kill()

if __name__ == "__main__":
    main()
