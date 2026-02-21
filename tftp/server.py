#!/usr/bin/env python3
"""
TFTP server for ZAM file delivery.
Serves files from ./files/ directory structure.
"""

import tftpy
import os
import threading
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tftpd")

TFTP_ROOT = Path(__file__).parent.parent / "files"
TFTP_PORT = 69

class ZamtftpServer:
    def __init__(self, root_dir: str = str(TFTP_ROOT), port: int = TFTP_PORT):
        self.root = Path(root_dir)
        self.port = port
        self.server = None
        self._thread = None
        
    def _ensure_dirs(self):
        """Ensure required TFTP directories exist"""
        dirs = [
            "POAP_CFG",
            "POAP_IMAGE",
            "POAP_STARTUP",
            "POAP_LOG",
            "POAP_STATUS"
        ]
        for d in dirs:
            (self.root / d).mkdir(parents=True, exist_ok=True)
    
    def _setup_zam_py(self):
        """Ensure zam.py exists in TFTP root"""
        zam_dst = self.root / "zam.py"
        zam_src = Path(__file__).parent.parent / "scripts" / "zam.py"
        
        if not zam_dst.exists() and zam_src.exists():
            import shutil
            shutil.copy(zam_src, zam_dst)
            logger.info(f"Copied zam.py to {zam_dst}")
    
    def _handler_callback(self, fname, raddress, rport, **kwargs):
        """Called for every TFTP request"""
        logger.info(f"TFTP request from {raddress}:{rport} for {fname}")
        
        # Log uploads (device sending files to us)
        if kwargs.get("mode") == "write":
            if "POAP_STARTUP" in fname:
                # Device booted and is registering
                sn = os.path.basename(fname).replace(".POAP", "")
                logger.info(f"Device {sn} sent startup POAP file")
            elif "POAP_LOG" in fname:
                logger.info(f"Device uploaded log: {fname}")
    
    def start(self):
        """Start TFTP server in background thread"""
        self._ensure_dirs()
        self._setup_zam_py()
        
        self.server = tftpy.Tftpserver(
            str(self.root),
            dyn_func_files={},
            port=self.port
        )
        
        logger.info(f"TFTP server starting on port {self.port}, root: {self.root}")
        
        self._thread = threading.Thread(target=self.server.listen, daemon=True)
        self._thread.start()
        
    def stop(self):
        """Stop the TFTP server"""
        if self.server:
            self.server.stop()
            logger.info("TFTP server stopped")


if __name__ == "__main__":
    server = ZamtftpServer()
    try:
        server.start()
        print(f"TFTP server running on port {TFTP_PORT}")
        input("Press Enter to stop...")
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
