#!/bin/bash
# Test CSV import with port configuration

set -e

API_URL="http://localhost:8000"

echo "=== ZAM v2 CSV Import with Ports Test ==="
echo ""

# Check if server is running
if ! curl -s "$API_URL/docs" > /dev/null 2>&1; then
    echo "Error: API server not running at $API_URL"
    echo "Start with: cd /home/user/.openclaw/workspace/zam-v2 && uvicorn api.main:app --reload"
    exit 1
fi

echo "1. Importing devices_with_ports.csv..."
RESULT=$(curl -s -X POST "$API_URL/admin/csv/upload" \
    -F "file=@/home/user/.openclaw/workspace/zam-v2/examples/devices_with_ports.csv")
echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"
echo ""

echo "2. Verifying device G1NQ7UW700483..."
DEVICE=$(curl -s "$API_URL/admin/devices/G1NQ7UW700483")
echo "$DEVICE" | python3 -m json.tool 2>/dev/null || echo "$DEVICE"
echo ""

echo "3. Getting effective config for G1NQ7UW700483..."
CONFIG=$(curl -s "$API_URL/config/G1NQ7UW700483")
echo "$CONFIG" | python3 -m json.tool 2>/dev/null || echo "$CONFIG"
echo ""

echo "4. Verifying device G1NQ7UW700487 (minimal info with ports)..."
DEVICE=$(curl -s "$API_URL/admin/devices/G1NQ7UW700487")
echo "$DEVICE" | python3 -m json.tool 2>/dev/null || echo "$DEVICE"
echo ""

echo "=== Test Complete ==="
