#!/usr/bin/env python3
"""Generate switch configuration files from JSON config"""

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
            mask = svi.get("mask", "255.255.255.0")
            lines.append(f" ip address {svi['ip']} {mask}")
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
        if port.get("native_vlan"):
            lines.append(f" switchport trunk native vlan {port['native_vlan']}")
        if port.get("allowed_vlans"):
            vlan_mode = port.get("vlan_mode", "only")
            lines.append(f" switchport trunk allowed vlan {vlan_mode} {port['allowed_vlans']}")
        if port.get("description"):
            lines.append(f" description {port['description']}")
        lines.append("!")
    lines.append("")

    # Aggregate ports (LACP)
    aggregate_ports = config.get("aggregate_ports", [])
    for ag in aggregate_ports:
        ag_id = ag.get("id", 1)
        lines.append(f"interface aggregateport {ag_id}")
        if ag.get("description"):
            lines.append(f" description {ag['description']}")
        lines.append(f" switchport mode {ag.get('switchport_mode', 'trunk')}")
        if ag.get("allowed_vlans"):
            vlan_mode = ag.get("vlan_mode", "only")
            lines.append(f" switchport trunk allowed vlan {vlan_mode} {ag['allowed_vlans']}")
        if ag.get("native_vlan"):
            lines.append(f" switchport trunk native vlan {ag['native_vlan']}")
        lines.append("!")
    lines.append("")

    # Aggregate member ports
    for ag in aggregate_ports:
        ag_id = ag.get("id", 1)
        for member in ag.get("members", []):
            lines.append(f"interface {member}")
            lines.append(f" port-group {ag_id}")
            lines.append("!")
    lines.append("")

    # SNMP
    snmp = config.get("snmp", {})
    if snmp:
        if snmp.get("community"):
            access = snmp.get("access", "rw")
            lines.append(f"snmp-server community {snmp['community']} {access}")
        if snmp.get("location"):
            lines.append(f"snmp-server location {snmp['location']}")
        if snmp.get("contact"):
            lines.append(f"snmp-server contact {snmp['contact']}")
        lines.append("")

    # SNTP (Ruijie uses SNTP, not NTP)
    if config.get("sntp_server"):
        lines.append(f"sntp server {config['sntp_server']}")
        lines.append("sntp enable")
        lines.append("")
    elif config.get("ntp_server"):
        lines.append(f"ntp server {config['ntp_server']}")
        lines.append("")

    # Timezone
    if config.get("timezone"):
        tz = config["timezone"]
        name = tz.get("name", "UTC")
        offset_hours = tz.get("offset_hours", 8)
        offset_mins = tz.get("offset_mins", 0)
        sign = "+" if offset_hours >= 0 else ""
        lines.append(f"clock timezone {name} {sign}{offset_hours} {offset_mins}")
        lines.append("")

    # DNS
    if config.get("dns_servers"):
        for dns in config["dns_servers"]:
            lines.append(f"ip name-server {dns}")
        lines.append("")

    # SSH Server
    ssh = config.get("ssh", {})
    if ssh.get("enabled", True):
        lines.append("enable service ssh-server")
        if ssh.get("scp_server"):
            lines.append("ip scp server enable")
        lines.append("")

    # Users
    users = config.get("users", [])
    for user in users:
        username = user.get("username", "admin")
        password = user.get("password", "changeme")
        privilege = user.get("privilege", 15)
        lines.append(f"username {username} privilege {privilege} secret {password}")
    lines.append("")

    # Enable secret
    enable_secret = config.get("enable_secret")
    if enable_secret:
        lines.append(f"enable secret {enable_secret}")
        lines.append("")

    # Line VTY
    vty = config.get("vty", {})
    lines.append("line vty 0 4")
    lines.append(" exec-timeout 30 0")
    transport = vty.get("transport", "ssh")
    lines.append(f" transport input {transport}")
    if users:
        lines.append(" login local")
    else:
        lines.append(" login")
        lines.append(" password ruijie")
    lines.append("!")
    lines.append("")

    lines.append("end")
    return "\n".join(lines)


def generate_params_file(config: dict, sn: str, zam_server: str) -> str:
    """Generate .params file for device"""
    result = [
        "[poap]",
        f"cfg_file=POAP_CFG/{sn}.cfg",
        "post_execution_reboot=true",
        "",
        "[upgrade]",
    ]
    if config.get("firmware_version"):
        result.append("yes=true")
        result.append(f"image_file=POAP_IMAGE/{config['firmware_version']}.bin")
    else:
        result.append("no=true")
    return "\n".join(result)


def write_device_files(sn: str, config: dict, zam_server: str = "192.168.1.100"):
    """Write config files for a device"""
    base_path = Path(__file__).parent / "files" / "POAP_CFG"
    base_path.mkdir(parents=True, exist_ok=True)

    cfg_content = generate_ruijie_config(config, sn)
    cfg_path = base_path / f"{sn}.cfg"
    with open(cfg_path, "w") as f:
        f.write(cfg_content)
    print(f"[+] Wrote {cfg_path}")

    params_content = generate_params_file(config, sn, zam_server)
    params_path = base_path / f"{sn}.params"
    with open(params_path, "w") as f:
        f.write(params_content)
    print(f"[+] Wrote {params_path}")


if __name__ == "__main__":
    example_config = {
        "hostname": "C03SW1",
        "vlans": [
            {"id": 1, "name": "Network_MGMT"},
            {"id": 396, "name": "WiFi7-MC1"},
        ],
        "trunk_ports": [
            {
                "interface": "TenGigabitEthernet 0/1",
                "description": "Uplink",
                "native_vlan": 396,
                "allowed_vlans": "396-399",
            }
        ],
        "sntp_server": "10.1.1.1",
        "timezone": {"name": "HongKong", "offset_hours": 8, "offset_mins": 0},
        "ssh": {"enabled": True},
        "users": [{"username": "admin", "password": "Admin123!", "privilege": 15}],
    }

    sn = sys.argv[1] if len(sys.argv) > 1 else "G1NQ7UW700483"
    write_device_files(sn, example_config)
