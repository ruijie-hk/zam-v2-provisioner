#!/usr/bin/env python3
"""
Generate switch configuration files from JSON config
"""

import json
import sys
from pathlib import Path

def generate_ruijie_config(config: dict, sn: str) -> str:
    """Generate Ruijie CLI config from JSON"""
    lines = []
    
    # Hostname
    hostname = config.get("hostname", f"switch-{sn[-6:]}")
    lines.append(f"hostname {hostname}")
    lines.append("")
    
    # VLANs
    vlans = config.get("vlans", [])
    for vlan in vlans:
        lines.append(f"vlan {vlan['id']}")
        if vlan.get("name"):
            lines.append(f" name {vlan['name']}")
        lines.append("!")
    
    lines.append("")
    
    # SVIs (VLAN interfaces)
    svis = config.get("svis", [])
    for svi in svis:
        lines.append(f"interface vlan {svi['vlan']}")
        if svi.get("ip"):
            lines.append(f" ip address {svi['ip']} {svi.get('mask', '255.255.255.0')}")
        if svi.get("description"):
            lines.append(f" description {svi['description']}")
        lines.append("!")
    
    lines.append("")
    
    # Access ports
    access_ports = config.get("access_ports", [])
    for port in access_ports:
        lines.append(f"interface {port['interface']}")
        lines.append(" switchport mode access")
        lines.append(f" switchport access vlan {port['vlan']}")
        if port.get("description"):
            lines.append(f" description {port['description']}")
        lines.append("!")
    
    lines.append("")
    
    # Trunk ports
    trunk_ports = config.get("trunk_ports", [])
    for port in trunk_ports:
        lines.append(f"interface {port['interface']}")
        lines.append(" switchport mode trunk")
        if port.get("allowed_vlans"):
            lines.append(f" switchport trunk allowed vlan {port['allowed_vlans']}")
        if port.get("description"):
            lines.append(f" description {port['description']}")
        lines.append("!")
    
    lines.append("")
    
    # SNMP
    if config.get("snmp"):
        snmp = config["snmp"]
        if snmp.get("community"):
            lines.append(f"snmp-server community {snmp['community']} rw")
        if snmp.get("location"):
            lines.append(f"snmp-server location {snmp['location']}")
        if snmp.get("contact"):
            lines.append(f"snmp-server contact {snmp['contact']}")
    
    lines.append("")
    
    # NTP
    if config.get("ntp_server"):
        lines.append(f"ntp server {config['ntp_server']}")
    
    lines.append("")
    
    # DNS
    if config.get("dns_servers"):
        for dns in config["dns_servers"]:
            lines.append(f"ip name-server {dns}")
    
    lines.append("")
    lines.append("end")
    
    return "\n".join(lines)

def generate_params_file(config: dict, sn: str, zam_server: str) -> str:
    """Generate .params file for device"""
    lines = [
        f"[poap]",
        f"cfg_file=POAP_CFG/{sn}.cfg",
        f"post_execution_reboot=true",
        "",
        "[upgrade]",
    ]
    
    if config.get("firmware_version"):
        lines.append(f"yes=true")
        lines.append(f"image_file=POAP_IMAGE/{config['firmware_version']}.bin")
    else:
        lines.append(f"no=true")
    
    return "\n".join(lines)

def write_device_files(sn: str, config: dict, zam_server: str = "192.168.1.100"):
    """Write config files for a device"""
    base_path = Path(__file__).parent / "files" / "POAP_CFG"
    base_path.mkdir(parents=True, exist_ok=True)
    
    # Write config file
    cfg_content = generate_ruijie_config(config, sn)
    cfg_path = base_path / f"{sn}.cfg"
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    print(f"[+] Wrote {cfg_path}")
    
    # Write params file
    params_content = generate_params_file(config, sn, zam_server)
    params_path = base_path / f"{sn}.params"
    with open(params_path, "w") as f:
        f.write(params_content)
    print(f"[+] Wrote {params_path}")

if __name__ == "__main__":
    # Example usage
    example_config = {
        "hostname": "edge-sw-01",
        "vlans": [
            {"id": 10, "name": "Management"},
            {"id": 20, "name": "Users"},
            {"id": 30, "name": "Servers"}
        ],
        "svis": [
            {"vlan": 10, "ip": "10.0.10.1", "mask": "255.255.255.0", "description": "Management"}
        ],
        "access_ports": [
            {"interface": "GigabitEthernet 0/1", "vlan": 20},
            {"interface": "GigabitEthernet 0/2", "vlan": 20}
        ],
        "trunk_ports": [
            {"interface": "GigabitEthernet 0/24", "allowed_vlans": "10,20,30", "description": "Uplink"}
        ],
        "snmp": {
            "community": "public",
            "location": "Data Center",
            "contact": "admin@example.com"
        },
        "ntp_server": "10.0.10.10",
        "dns_servers": ["8.8.8.8", "8.8.4.4"]
    }
    
    if len(sys.argv) > 1:
        sn = sys.argv[1]
    else:
        sn = "G1NQ7UW700483"
    
    write_device_files(sn, example_config)
