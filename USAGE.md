# ZAM v2 Usage Guide

## Quick Start

### 1. Install Dependencies

```bash
cd zam-v2
pip install -r requirements.txt
# Or if on system Python:
pip install --break-system-packages -r requirements.txt
```

### 2. Configure the Provisioner

Before starting, you MUST update the switch bootstrap script:

```bash
# Edit scripts/zam.py
nano scripts/zam.py
```

Change this line to your provisioner's actual IP:
```python
ZAM_SERVER = "192.168.1.100"  # <-- CHANGE THIS
```

### 3. Start the Server

```bash
# Run both HTTP API and TFTP server
sudo ./run.py
```

You'll see:
```
ZAM v2 Provisioner
============================================================
[+] Copied zam.py to TFTP root
[*] Starting TFTP server on port 69...
[*] Starting HTTP API on port 8000...

============================================================
Running! Ctrl+C to stop.
============================================================
```

The server runs:
- HTTP API on port 8000
- TFTP server on port 69 (requires sudo)

### 4. Set Up DHCP

On your DHCP server, configure the pool for switches:

```
ip dhcp pool switches
 network 10.0.10.0 255.255.255.0
 default-router 10.0.10.1
 
 # ZAM Options (Critical!)
 option 66 ascii 10.0.10.100   # Your ZAM provisioner IP
 option 67 ascii zam.py          # Bootstrap script name
```

**Note:** The switch needs these DHCP options to find the ZAM server.

---

## Provisioning Workflow

### Step 1: Create a Template

Templates define the base configuration for device types (edge, core, etc.):

```bash
curl -X POST http://localhost:8000/admin/templates \
  -H "Content-Type: application/json" \
  -d '{
    "id": "edge-48p",
    "name": "Edge 48-Port",
    "description": "Standard 48-port edge access switch",
    "base_config": {
      "hostname": "edge-sw-template",
      "vlans": [
        {"id": 10, "name": "Management"},
        {"id": 20, "name": "Users"}
      ],
      "svis": [
        {"vlan": 10, "ip": "10.0.10.1", "mask": "255.255.255.0"}
      ],
      "access_ports": [
        {"interface": "GigabitEthernet 0/1", "vlan": 20},
        {"interface": "GigabitEthernet 0/2", "vlan": 20}
      ],
      "trunk_ports": [
        {"interface": "GigabitEthernet 0/48", "allowed_vlans": "10,20"}
      ],
      "snmp": {
        "community": "public"
      },
      "ntp_server": "10.0.10.10"
    }
  }'
```

### Step 2: Add Devices

#### Option A: Via API (one device)

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{
    "sn": "G1NQ7UW700483",
    "mac": "00:11:22:33:44:55",
    "ip": "10.0.10.50"
  }'
```

Then assign template:

```bash
curl -X PUT http://localhost:8000/admin/devices/G1NQ7UW700483 \
  -H "Content-Type: application/json" \
  -d '{"template_id": "edge-48p"}'
```

#### Option B: Via CSV (bulk import)

Create `devices.csv`:
```csv
sn,mac,ip,template_id
G1NQ7UW700483,00:11:22:33:44:55,10.0.10.51,edge-48p
G1NQ7UW700484,00:11:22:33:44:56,10.0.10.52,edge-48p
```

Upload:
```bash
curl -X POST http://localhost:8000/admin/csv/upload \
  -F "file=@devices.csv"
```

### Step 3: Generate Config Files

Before the switch boots, generate its config files:

```bash
python3 config_generator.py G1NQ7UW700483
```

This creates:
- `files/POAP_CFG/G1NQ7UW700483.cfg` — Switch CLI config
- `files/POAP_CFG/G1NQ7UW700483.params` — Parameters file

**Alternative:** The API can do this automatically on first `/config/{sn}` request. The `config_generator.py` is useful for pre-generating configs before switches arrive.

### Step 4: Boot the Switch

On the switch (console):

```
# Delete existing config
delete config.text
Do you want to delete [flash:/config.text]? [Y/N]: y
Delete success.

# Enable ZAM (usually on by default)
configure terminal
zam
end

# Reboot
reload
```

The switch will:
1. Boot with no config
2. Get IP from DHCP (with Option 66/67)
3. TFTP download `zam.py` from your server
4. Execute the script which:
   - Registers with `/register`
   - Downloads config via TFTP
   - Applies config
   - Reports status via `/callback`
   - Reboots

### Step 5: Monitor

Check device status:
```bash
# List all devices
curl http://localhost:8000/admin/devices | jq .

# Get specific device
curl http://localhost:8000/admin/devices/G1NQ7UW700483 | jq .

# Check deployment history
curl http://localhost:8000/admin/devices/G1NQ7UW700483/deployments
```

---

## Customizing Device Config

### Per-Device Overrides

If a device needs config different from its template:

```bash
curl -X POST http://localhost:8000/admin/devices/G1NQ7UW700483/override \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "hostname": "custom-edge-sw-01",
      "vlans": [
        {"id": 10, "name": "Management"},
        {"id": 20, "name": "Users"},
        {"id": 30, "name": "Special"}
      ]
    }
  }'
```

The override merges with the template (overrides win).

### Clear Override

```bash
curl -X DELETE http://localhost:8000/admin/devices/G1NQ7UW700483/override
```

---

## Configuration Schema

Templates and overrides use this JSON structure:

```json
{
  "hostname": "switch-name",
  
  "vlans": [
    {"id": 10, "name": "Management"},
    {"id": 20, "name": "Users"}
  ],
  
  "svis": [
    {
      "vlan": 10,
      "ip": "10.0.10.1",
      "mask": "255.255.255.0",
      "description": "Management"
    }
  ],
  
  "access_ports": [
    {
      "interface": "GigabitEthernet 0/1",
      "vlan": 20,
      "description": "Desk port"
    }
  ],
  
  "trunk_ports": [
    {
      "interface": "GigabitEthernet 0/48",
      "allowed_vlans": "10,20,30",
      "description": "Uplink"
    }
  ],
  
  "snmp": {
    "community": "public",
    "location": "Data Center",
    "contact": "ops@example.com"
  },
  
  "ntp_server": "10.0.10.10",
  "dns_servers": ["8.8.8.8", "8.8.4.4"],
  
  "firmware_version": "S5350e_RGOS12.6"  // Triggers firmware upgrade
}
```

---

## Troubleshooting

### Switch doesn't download zam.py

**Check:**
```bash
# Verify TFTP server is running
sudo netstat -uln | grep :69

# Check zam.py exists in TFTP root
ls -la files/zam.py

# Test TFTP manually
tftp 10.0.10.100
tftp> get zam.py
```

### Switch gets zam.py but fails to register

**Check:**
1. `ZAM_SERVER` in `scripts/zam.py` matches your provisioner IP
2. Provisioner is reachable from switch network
3. HTTP API is running: `curl http://<ip>:8000/admin/devices`

### Config doesn't apply

**Check:**
1. Config file was generated: `ls files/POAP_CFG/{SN}.cfg`
2. TFTP can serve it: `tftp <ip> -c get POAP_CFG/{SN}.cfg`
3. Check switch logs: `show zam log` (if available) or check `files/POAP_LOG/{SN}.log`

### View API logs

```bash
# If running directly:
python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --log-level debug
```

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/register` | POST | Device registers itself |
| `/config/{sn}` | GET | Device polls for config |
| `/callback/{id}` | POST | Device reports deployment status |
| `/admin/devices` | GET | List all devices |
| `/admin/devices/{sn}` | GET/PUT | Device details/update |
| `/admin/devices/{sn}/override` | POST/DELETE | Per-device config |
| `/admin/templates` | GET/POST | List/create templates |
| `/admin/templates/{id}` | GET | Template details |
| `/admin/csv/upload` | POST | Bulk import |

---

## Files Generated

| File | Purpose |
|------|---------|
| `zam.db` | SQLite database |
| `files/POAP_CFG/{SN}.cfg` | Switch CLI config |
| `files/POAP_CFG/{SN}.params` | Parameters file |
| `files/POAP_STARTUP/{SN}.POAP` | Device startup file |
| `files/POAP_LOG/{SN}.log` | Switch ZAM logs |