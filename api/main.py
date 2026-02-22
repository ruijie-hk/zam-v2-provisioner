from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from db.models import get_db, Device, Template, DeviceOverride, Deployment
from datetime import datetime
import hashlib
import json
import yaml

app = FastAPI(title="ZAM v2 Provisioner")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and startup verification"""
    return {"status": "ok"}

# Pydantic models
class DeviceRegister(BaseModel):
    sn: str
    mac: Optional[str] = None
    ip: Optional[str] = None

class DeviceOverrideModel(BaseModel):
    config: Dict[str, Any]

class TemplateCreate(BaseModel):
    id: str
    name: str
    description: str = ""
    base_config: Dict[str, Any]

class DeviceStatusUpdate(BaseModel):
    status: str
    report: Optional[Dict[str, Any]] = None

# Switch-facing endpoints
@app.post("/register")
def register_device(data: DeviceRegister, db: Session = Depends(get_db)):
    """Device boots and calls this to register itself"""
    device = db.query(Device).filter(Device.sn == data.sn).first()
    if not device:
        device = Device(
            sn=data.sn,
            mac=data.mac,
            ip=data.ip,
            last_seen=datetime.utcnow()
        )
        db.add(device)
    else:
        device.mac = data.mac or device.mac
        device.ip = data.ip or device.ip
        device.last_seen = datetime.utcnow()
    
    db.commit()
    return {"device_id": data.sn, "status": "registered"}

@app.get("/config/{sn}")
def get_config(sn: str, db: Session = Depends(get_db)):
    """Device polls this to get its config"""
    device = db.query(Device).filter(Device.sn == sn).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Build effective config: template + overrides
    effective = {}
    
    if device.template_id:
        template = db.query(Template).filter(Template.id == device.template_id).first()
        if template:
            effective = dict(template.base_config)
    
    # Apply overrides
    override = db.query(DeviceOverride).filter(DeviceOverride.sn == sn).first()
    if override:
        effective.update(override.config)
    
    # Create deployment record
    config_str = json.dumps(effective, sort_keys=True)
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]
    
    deployment = Deployment(
        sn=sn,
        template_id=device.template_id,
        config_hash=config_hash,
        status="pending"
    )
    db.add(deployment)
    db.commit()
    db.refresh(deployment)
    
    # Update device status
    device.status = "pending"
    db.commit()
    
    return {
        "deployment_id": deployment.id,
        "config": effective,
        "files": generate_file_list(effective, sn)
    }

def generate_file_list(config: dict, sn: str) -> dict:
    """Generate TFTP file paths based on config"""
    files = {
        "params": f"/POAP_CFG/{sn}.params",
        "config": f"/POAP_CFG/{sn}.cfg"
    }
    if config.get("firmware_version"):
        files["image"] = f"/POAP_IMAGE/{config['firmware_version']}.bin"
    return files

@app.post("/callback/{deployment_id}")
def deployment_callback(deployment_id: int, data: DeviceStatusUpdate, db: Session = Depends(get_db)):
    """Device reports back after applying config"""
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    deployment.status = data.status
    deployment.switch_report = data.report
    deployment.completed_at = datetime.utcnow()
    
    # Update device status
    device = db.query(Device).filter(Device.sn == deployment.sn).first()
    if device:
        device.status = data.status
        device.last_seen = datetime.utcnow()
    
    db.commit()
    return {"status": "recorded"}


# Admin-facing endpoints
@app.get("/admin/devices")
def list_devices(db: Session = Depends(get_db)):
    devices = db.query(Device).all()
    return [{"sn": d.sn, "mac": d.mac, "ip": d.ip, "status": d.status, "template": d.template_id} for d in devices]

@app.get("/admin/devices/{sn}")
def get_device(sn: str, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.sn == sn).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    override = db.query(DeviceOverride).filter(DeviceOverride.sn == sn).first()
    
    return {
        "sn": device.sn,
        "mac": device.mac,
        "ip": device.ip,
        "status": device.status,
        "template_id": device.template_id,
        "last_seen": device.last_seen,
        "overrides": override.config if override else {}
    }

@app.put("/admin/devices/{sn}")
def update_device(sn: str, data: dict, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.sn == sn).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    if "template_id" in data:
        device.template_id = data["template_id"]
    db.commit()
    return {"status": "updated"}

@app.post("/admin/devices/{sn}/override")
def set_override(sn: str, data: DeviceOverrideModel, db: Session = Depends(get_db)):
    override = db.query(DeviceOverride).filter(DeviceOverride.sn == sn).first()
    if override:
        override.config = data.config
        override.updated_at = datetime.utcnow()
    else:
        override = DeviceOverride(sn=sn, config=data.config)
        db.add(override)
    db.commit()
    return {"status": "override set"}

@app.delete("/admin/devices/{sn}/override")
def clear_override(sn: str, db: Session = Depends(get_db)):
    override = db.query(DeviceOverride).filter(DeviceOverride.sn == sn).first()
    if override:
        db.delete(override)
        db.commit()
    return {"status": "override cleared"}


# Template management
@app.get("/admin/templates")
def list_templates(db: Session = Depends(get_db)):
    return db.query(Template).all()

@app.post("/admin/templates")
def create_template(data: TemplateCreate, db: Session = Depends(get_db)):
    template = Template(
        id=data.id,
        name=data.name,
        description=data.description,
        base_config=data.base_config
    )
    db.add(template)
    db.commit()
    return {"status": "created"}

@app.get("/admin/templates/{id}")
def get_template(id: str, db: Session = Depends(get_db)):
    template = db.query(Template).filter(Template.id == id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


# CSV Import
def parse_access_ports(value: str) -> List[Dict[str, Any]]:
    """
    Parse access_ports column: "port:vlan:desc,port:vlan:desc"
    Example: "Gi0/1:20:Office,Gi0/2:30:Desk"
    Returns: [{"interface": "GigabitEthernet 0/1", "vlan": 20, "description": "Office"}, ...]
    """
    if not value or not value.strip():
        return []
    
    result = []
    for entry in value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        
        parts = entry.split(":")
        if len(parts) < 2:
            continue
        
        port_raw = parts[0].strip()
        vlan_str = parts[1].strip()
        desc = parts[2].strip() if len(parts) > 2 else ""
        
        # Expand port shorthand (Gi0/1 -> GigabitEthernet 0/1)
        interface = expand_port_name(port_raw)
        
        try:
            vlan = int(vlan_str)
        except ValueError:
            continue  # Skip invalid vlan
        
        port_config = {"interface": interface, "vlan": vlan}
        if desc:
            port_config["description"] = desc
        result.append(port_config)
    
    return result


def parse_trunk_ports(value: str) -> List[Dict[str, Any]]:
    """
    Parse trunk_ports column: "port:vlans:desc;port:vlans:desc"
    vlans is comma-separated list of VLAN IDs
    Use semicolons to separate port entries, commas for VLAN lists
    Example: "Gi0/24:1,10,20:Uplink;Gi0/23:10,20,30:Server"
    Returns: [{"interface": "GigabitEthernet 0/24", "allowed_vlans": "1,10,20", "description": "Uplink"}, ...]
    """
    if not value or not value.strip():
        return []
    
    result = []
    # Use semicolon as entry separator to allow commas in VLAN lists
    for entry in value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        
        # Format: port:vlans:desc where vlans can be "1,10,20"
        # Find first colon (port) and last colon (optional desc)
        first_colon = entry.find(":")
        if first_colon == -1:
            continue
        
        port_raw = entry[:first_colon].strip()
        remaining = entry[first_colon + 1:]
        
        # Find the last colon for description (if any)
        last_colon = remaining.rfind(":")
        if last_colon == -1:
            # No description, everything after port is vlans
            vlans_str = remaining.strip()
            desc = ""
        else:
            # Check if what's after last colon looks like a VLAN list or description
            potential_desc = remaining[last_colon + 1:].strip()
            potential_vlans = remaining[:last_colon].strip()
            
            # If the "potential desc" contains only digits and commas, it's part of vlans
            if potential_desc and all(c.isdigit() or c == "," for c in potential_desc):
                vlans_str = potential_vlans + "," + potential_desc if potential_vlans else potential_desc
                desc = ""
            else:
                vlans_str = potential_vlans
                desc = potential_desc
        
        # Validate vlans (should be comma-separated digits)
        if not vlans_str or not all(c.isdigit() or c == "," for c in vlans_str):
            continue
        
        interface = expand_port_name(port_raw)
        
        port_config = {"interface": interface, "allowed_vlans": vlans_str}
        if desc:
            port_config["description"] = desc
        result.append(port_config)
    
    return result


def parse_aggregate_ports(value: str) -> List[Dict[str, Any]]:
    """
    Parse aggregate_ports column: "id:members:mode:vlans:desc;id:members:mode:vlans:desc"
    
    Format for each aggregate port: "id:member1,member2:mode:vlans:description[:native_vlan]"
    - id: aggregate port ID (integer)
    - members: comma-separated list of member ports
    - mode: switchport mode (trunk or access)
    - vlans: allowed VLANs (comma-separated)
    - description: optional description
    - native_vlan: optional native VLAN (only for trunk mode)
    
    Use semicolons to separate multiple aggregate ports.
    
    Example: "1:Gi0/1,Gi0/2:trunk:1,10,20:Uplink;2:Gi0/3,Gi0/4:access:30:Server"
    
    Returns: [
        {
            "id": 1,
            "members": ["GigabitEthernet 0/1", "GigabitEthernet 0/2"],
            "switchport_mode": "trunk",
            "allowed_vlans": "1,10,20",
            "description": "Uplink"
        },
        ...
    ]
    """
    if not value or not value.strip():
        return []
    
    result = []
    # Use semicolon as entry separator
    for entry in value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        
        parts = entry.split(":")
        if len(parts) < 4:
            continue  # Need at least id, members, mode, vlans
        
        try:
            ag_id = int(parts[0].strip())
        except ValueError:
            continue  # Skip invalid ID
        
        members_raw = parts[1].strip()
        mode = parts[2].strip().lower()
        vlans = parts[3].strip()
        
        # Validate mode
        if mode not in ("trunk", "access"):
            continue
        
        # Parse members (comma-separated)
        members = [expand_port_name(m.strip()) for m in members_raw.split(",") if m.strip()]
        if not members:
            continue
        
        ag_config = {
            "id": ag_id,
            "members": members,
            "switchport_mode": mode,
            "allowed_vlans": vlans
        }
        
        # Optional description (position 4)
        if len(parts) > 4:
            desc = parts[4].strip()
            if desc:
                ag_config["description"] = desc
        
        # Optional native_vlan (position 5, only for trunk)
        if len(parts) > 5 and mode == "trunk":
            try:
                native_vlan = int(parts[5].strip())
                ag_config["native_vlan"] = native_vlan
            except ValueError:
                pass
        
        result.append(ag_config)
    
    return result


def expand_port_name(shorthand: str) -> str:
    """
    Expand port shorthand to full interface name.
    Gi0/1 -> GigabitEthernet 0/1
    Fa0/1 -> FastEthernet 0/1
    Te0/1 -> TenGigabitEthernet 0/1
    """
    shorthand = shorthand.strip()
    
    # Map of prefixes to full names
    prefixes = {
        "Gi": "GigabitEthernet",
        "Fa": "FastEthernet",
        "Te": "TenGigabitEthernet",
        "Fo": "FortyGigabitEthernet",
        "Hu": "HundredGigabitEthernet",
        "Eth": "Ethernet",
    }
    
    for prefix, full_name in prefixes.items():
        if shorthand.startswith(prefix):
            rest = shorthand[len(prefix):]
            return f"{full_name} {rest}"
    
    # If no prefix matched, return as-is (might already be full name)
    return shorthand


@app.post("/admin/csv/upload")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Bulk import with optional port configuration.
    
    Required columns: sn
    Optional columns: mac, ip, template_id, access_ports, trunk_ports, aggregate_ports
    
    Port column formats:
    - access_ports: "port:vlan:desc,port:vlan:desc" (e.g., "Gi0/1:20:Office,Gi0/2:30")
    - trunk_ports: "port:vlans:desc" (e.g., "Gi0/24:1,10,20:Uplink")
    - aggregate_ports: "id:members:mode:vlans:desc[:native_vlan];..."
      (e.g., "1:Gi0/1,Gi0/2:trunk:1,10,20:Uplink")
    
    Port shorthand supported: Gi, Fa, Te, Fo, Hu, Eth
    """
    import csv
    from io import StringIO
    
    content = await file.read()
    text = content.decode()
    
    reader = csv.DictReader(StringIO(text))
    imported = 0
    updated = 0
    port_configs_applied = 0
    warnings = []
    
    for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
        sn = row.get("sn", "").strip()
        if not sn:
            warnings.append(f"Row {row_num}: Missing serial number, skipping")
            continue
        
        # Create or update device
        device = db.query(Device).filter(Device.sn == sn).first()
        is_new = device is None
        
        if is_new:
            device = Device(
                sn=sn,
                mac=row.get("mac", "").strip() or None,
                ip=row.get("ip", "").strip() or None,
                template_id=row.get("template_id", "").strip() or None
            )
            db.add(device)
            imported += 1
        else:
            # Update existing device
            if row.get("mac", "").strip():
                device.mac = row.get("mac", "").strip()
            if row.get("ip", "").strip():
                device.ip = row.get("ip", "").strip()
            if row.get("template_id", "").strip():
                device.template_id = row.get("template_id", "").strip()
            updated += 1
        
        # Parse port configuration
        access_ports_raw = row.get("access_ports", "")
        trunk_ports_raw = row.get("trunk_ports", "")
        aggregate_ports_raw = row.get("aggregate_ports", "")
        aggregate_ports_raw = row.get("aggregate_ports", "")
        
        access_ports = parse_access_ports(access_ports_raw)
        trunk_ports = parse_trunk_ports(trunk_ports_raw)
        aggregate_ports = parse_aggregate_ports(aggregate_ports_raw)
        
        # Create or update DeviceOverride if ports specified
        if access_ports or trunk_ports or aggregate_ports:
            override_config = {}
            if access_ports:
                override_config["access_ports"] = access_ports
            if trunk_ports:
                override_config["trunk_ports"] = trunk_ports
            if aggregate_ports:
                override_config["aggregate_ports"] = aggregate_ports
            
            override = db.query(DeviceOverride).filter(DeviceOverride.sn == sn).first()
            if override:
                # Merge with existing override config
                existing = dict(override.config) if override.config else {}
                existing.update(override_config)
                override.config = existing
                override.updated_at = datetime.utcnow()
            else:
                override = DeviceOverride(sn=sn, config=override_config)
                db.add(override)
            
            port_configs_applied += 1
    
    db.commit()
    
    result = {
        "imported": imported,
        "updated": updated,
        "port_configs_applied": port_configs_applied
    }
    
    if warnings:
        result["warnings"] = warnings
    
    return result
