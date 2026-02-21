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
@app.post("/admin/csv/upload")
async def upload_csv(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Bulk import: sn,mac,ip,template_id"""
    import csv
    from io import StringIO
    
    content = await file.read()
    text = content.decode()
    
    reader = csv.DictReader(StringIO(text))
    imported = 0
    
    for row in reader:
        sn = row.get("sn")
        if not sn:
            continue
        
        device = db.query(Device).filter(Device.sn == sn).first()
        if not device:
            device = Device(
                sn=sn,
                mac=row.get("mac"),
                ip=row.get("ip"),
                template_id=row.get("template_id")
            )
            db.add(device)
            imported += 1
    
    db.commit()
    return {"imported": imported}
