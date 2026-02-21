#!/bin/bash
# Test the provisioner end-to-end

set -e

SERVER="http://localhost:8000"
SN="G1NQ7UW700483"

echo "=== ZAM v2 Test Script ==="
echo

# 1. Create template
echo "[1/5] Creating template..."
curl -s -X POST "$SERVER/admin/templates" -H "Content-Type: application/json" -d '{
  "id": "edge-48p",
  "name": "Edge 48-Port",
  "description": "Standard edge switch",
  "base_config": {
    "hostname": "edge-sw-test",
    "vlans": [{"id": 10, "name": "Mgmt"}, {"id": 20, "name": "Users"}],
    "svis": [{"vlan": 10, "ip": "10.0.10.5"}],
    "snmp": {"community": "public"}
  }
}' | jq .

# 2. Register device
echo "[2/5] Registering device..."
curl -s -X POST "$SERVER/register" -H "Content-Type: application/json" -d "{
  \"sn\": \"$SN\",
  \"mac\": \"00:11:22:33:44:55\",
  \"ip\": \"10.0.10.50\"
}" | jq .

# 3. Assign template
echo "[3/5] Assigning template..."
curl -s -X PUT "$SERVER/admin/devices/$SN" -H "Content-Type: application/json" -d '{
  "template_id": "edge-48p"
}' | jq .

# 4. Device polls config
echo "[4/5] Getting config..."
CONFIG=$(curl -s "$SERVER/config/$SN")
echo "$CONFIG" | jq .

# Extract deployment_id
DEPLOYMENT_ID=$(echo "$CONFIG" | jq -r '.deployment_id')

# 5. Device reports completion
echo "[5/5] Reporting status..."
curl -s -X POST "$SERVER/callback/$DEPLOYMENT_ID" -H "Content-Type: application/json" -d '{
  "status": "done",
  "report": {"files_downloaded": 2, "uptime": 3600}
}' | jq .

echo
echo "=== Test Complete ==="
echo
echo "Device status:"
curl -s "$SERVER/admin/devices/$SN" | jq .
