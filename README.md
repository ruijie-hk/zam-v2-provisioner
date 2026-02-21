# ZAM v2 Provisioner

Zero Automatic Manager (ZAM) v2 - A modern device provisioner for Ruijie switches with REST API, templates, per-device overrides, and full deployment tracking.

## Overview

This is a hybrid provisioner that combines:
- **HTTP REST API** - for admin operations and device callbacks
- **TFTP Server** - for file delivery to switches (required by Ruijie ZAM)
- **Custom `zam.py`** - Python script that runs on switches, provides JSON feedback, logs, and structured callbacks

## Features

- ✅ Template-based configuration with per-device overrides
- ✅ RESTful API for device management
- ✅ Full deployment lifecycle tracking (registered → pending → applying → done/failed)
- ✅ JSON config → Ruijie CLI conversion
- ✅ CSV bulk import
- ✅ Switch-side agent that can make HTTP callbacks
- ✅ Centralized logging from switches

## Quick Start

### Prerequisites

```bash
pip install -r requirements.txt
```

### Start the Server

```bash
./run.py
```

This starts:
- HTTP API on port 8000
- TFTP server on port 69 (requires root or sudo for port 69)

### API Endpoints

**Switch-facing:**
- `POST /register` - Device registers itself
- `GET /config/{sn}` - Device polls for configuration
- `POST /callback/{deployment_id}` - Device reports deployment status

**Admin-facing:**
- `GET /admin/devices` - List all devices
- `GET /admin/devices/{sn}` - Get device details
- `PUT /admin/devices/{sn}` - Update device
- `POST /admin/devices/{sn}/override` - Set per-device config override
- `GET /admin/templates` - List templates
- `POST /admin/templates` - Create template
- `POST /admin/csv/upload` - Bulk import devices

## Example Usage

### 1. Create a Template

```bash
curl -X POST http://localhost:8000/admin/templates \
  -H "Content-Type: application/json" \
  -d '{
    "id": "edge-48p",
    "name": "Edge 48-Port",
    "description": "Standard edge switch config",
    "base_config": {
      "vlans": [{"id": 10, "name": "Mgmt"}, {"id": 20, "name": "Users"}],
      "svis": [{"vlan": 10, "ip": "10.0.10.1"}],
      "snmp": {"community": "public"}
    }
  }'
```

### 2. Add a Device

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"sn": "G1NQ7UW700483", "mac": "00:00:00:00:00:00", "ip": "10.0.10.50"}'
```

### 3. Assign Template & Generate Config Files

```bash
# Assign template
curl -X PUT http://localhost:8000/admin/devices/G1NQ7UW700483 \
  -H "Content-Type: application/json" \
  -d '{"template_id": "edge-48p"}'

# Generate config files
python config_generator.py G1NQ7UW700483
```

### 4. Device Boots (Simulate)

```bash
# Device registers
curl -X POST http://localhost:8000/register \
  -d '{"sn": "G1NQ7UW700483", "mac": "00:11:22:33:44:55", "ip": "10.0.10.50"}'

# Device polls for config
curl http://localhost:8000/config/G1NQ7UW700483

# Device reports status back
curl -X POST http://localhost:8000/callback/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "done", "report": {"files_downloaded": 2}}'
```

## Switch Configuration

On the Ruijie switch:

```
# Enable ZAM
configure terminal
zam
end

# Delete config and reboot
delete config.text
reload
```

The switch will:
1. DHCP and get Option 66 (ZAM server IP) + Option 67 (`zam.py`)
2. TFTP download `zam.py` from your server
3. Execute the script
4. The script registers, downloads config via TFTP, applies it, and reports back

**Important:** Edit `scripts/zam.py` and update:
- `ZAM_SERVER` - your provisioner IP
- `ZAM_API_PORT` - your API port (8000)

## Directory Structure

```
zam-v2/
├── api/
│   └── main.py              # FastAPI application
├── db/
│   ├── __init__.py
│   └── models.py            # SQLAlchemy models
├── tftp/
│   └── server.py            # TFTP server wrapper
├── scripts/
│   └── zam.py               # Switch bootstrap script
├── files/
│   ├── zam.py               # (auto-copied on start)
│   ├── POAP_CFG/            # Config files (.cfg, .params)
│   ├── POAP_IMAGE/          # Firmware binaries
│   ├── POAP_STARTUP/        # SN files from switches
│   ├── POAP_LOG/            # Logs from switches
│   └── POAP_STATUS/         # Status files
├── config_generator.py      # JSON → CLI converter
├── run.py                   # Main entry point
└── README.md
```

## Configuration Schema

Templates and device configs follow this JSON structure:

```json
{
  "hostname": "switch-name",
  "vlans": [
    {"id": 10, "name": "Management"}
  ],
  "svis": [
    {"vlan": 10, "ip": "10.0.10.1", "mask": "255.255.255.0"}
  ],
  "access_ports": [
    {"interface": "GigabitEthernet 0/1", "vlan": 20}
  ],
  "trunk_ports": [
    {"interface": "GigabitEthernet 0/24", "allowed_vlans": "10,20"}
  ],
  "snmp": {
    "community": "public",
    "location": "DC",
    "contact": "admin@example.com"
  },
  "ntp_server": "10.0.0.1",
  "dns_servers": ["8.8.8.8"]
}
```

## Production Notes

- Use PostgreSQL instead of SQLite for production
- Add authentication to admin endpoints
- Run behind nginx or traefik with TLS
- TFTP uses UDP port 69 (requires root or capability)
- The switch bootstrap uses HTTP (not HTTPS) - add TLS termination if needed

## License

MIT
