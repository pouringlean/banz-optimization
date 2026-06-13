#!/usr/bin/env python3
"""
BANZ OPTIMIZATION Beta v1
Requirements: Python 3.6+ with tkinter (standard on Windows/Mac/Linux)
Run:          python banz_optimization_beta1.py
"""

import tkinter as tk
from tkinter import ttk
import threading, time, subprocess, platform, socket
import os, re, collections, statistics, sys
import math
from datetime import datetime

OS = platform.system()

# ─────────────────────────────────────────────────────────────────────────────
# Ping helpers
# ─────────────────────────────────────────────────────────────────────────────
def system_ping(host):
    try:
        if OS == "Windows":
            cmd = ["ping", "-n", "1", "-w", "2000", host]
        else:
            cmd = ["ping", "-c", "1", "-W", "2", host]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        out = r.stdout
        if OS == "Windows":
            m = (re.search(r"[Aa]verage\s*=\s*(\d+)ms", out)
                 or re.search(r"time[=<](\d+)ms", out))
        else:
            m = re.search(r"time[=<]([\d.]+)\s*ms", out)
        if m:
            return round(float(m.group(1)), 1)
    except Exception:
        pass
    return None

def tcp_ping(host, port=80, timeout=2):
    try:
        start = time.time()
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return round((time.time() - start) * 1000, 1)
    except Exception:
        return None

def smart_ping(host, port=80):
    result = system_ping(host)
    if result is None:
        result = tcp_ping(host, port)
    return result

def run_cmd(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def run_cmd_output(cmd, timeout=10):
    """Run a command and return its stdout."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                           text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""

# ─────────────────────────────────────────────────────────────────────────────
# Network adapter info helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_adapter_info():
    """Return a list of dicts with adapter info."""
    adapters = []
    if OS == "Windows":
        out = run_cmd_output("netsh interface show interface")
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] in ("Enabled", "Disabled"):
                state   = parts[0]
                conn    = parts[1]
                kind    = parts[2]
                name    = " ".join(parts[3:])
                adapters.append({"name": name, "state": state,
                                 "connected": conn, "type": kind})
    elif OS == "Linux":
        out = run_cmd_output("ip link show")
        for line in out.splitlines():
            m = re.match(r"\d+:\s+(\S+):", line)
            if m:
                iface = m.group(1)
                state = "UP" if "UP" in line else "DOWN"
                adapters.append({"name": iface, "state": state,
                                 "connected": state, "type": "?"})
    elif OS == "Darwin":
        out = run_cmd_output("networksetup -listallnetworkservices")
        for line in out.splitlines():
            if line and not line.startswith("*") and "An asterisk" not in line:
                adapters.append({"name": line, "state": "Enabled",
                                 "connected": "?", "type": "?"})
    return adapters

def get_active_adapter_name():
    """Best-guess at the primary connected adapter name."""
    if OS == "Windows":
        out = run_cmd_output('netsh interface show interface')
        for line in out.splitlines():
            if "Connected" in line:
                parts = line.split()
                if len(parts) >= 4:
                    return " ".join(parts[3:])
    elif OS == "Linux":
        out = run_cmd_output("ip route | grep default | awk '{print $5}'")
        return out.strip() or "eth0"
    elif OS == "Darwin":
        out = run_cmd_output("route get default | grep interface | awk '{print $2}'")
        return out.strip() or "en0"
    return "Wi-Fi"

def get_ip_info():
    """Return local IP and public IP."""
    local_ip = "—"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return local_ip

def get_connection_type():
    """Heuristic: check if ethernet or wifi."""
    if OS == "Windows":
        out = run_cmd_output("netsh interface show interface")
        for line in out.splitlines():
            if "Connected" in line:
                if "Ethernet" in line or "LAN" in line or "Local Area" in line:
                    return "Ethernet 🔌"
                if "Wi-Fi" in line or "Wireless" in line or "WLAN" in line:
                    return "Wi-Fi 📶"
        return "Unknown"
    elif OS == "Linux":
        iface = get_active_adapter_name()
        if iface.startswith("eth") or iface.startswith("en"):
            return "Ethernet 🔌"
        if iface.startswith("wl"):
            return "Wi-Fi 📶"
        return iface
    elif OS == "Darwin":
        iface = get_active_adapter_name()
        if iface.startswith("en0"):
            return "Wi-Fi / Ethernet 📶"
        return iface
    return "Unknown"

# ─────────────────────────────────────────────────────────────────────────────
# Tweak data
# ─────────────────────────────────────────────────────────────────────────────
SERVERS = [
    {"name": "Google DNS",             "host": "8.8.8.8",            "port": 53},
    {"name": "Cloudflare DNS",         "host": "1.1.1.1",            "port": 53},
    {"name": "US East (NY)",           "host": "208.67.222.222",     "port": 443},
    {"name": "EU West (Frankfurt)",    "host": "google.de",          "port": 80},
    {"name": "Asia Pacific (Tokyo)",   "host": "jp.yahoo.com",       "port": 80},
    {"name": "US West (LA)",           "host": "www.cloudflare.com", "port": 80},
]

# Each tweak: id, name, desc, impact, category, cmd dict, undo_cmd dict (optional)
TWEAKS = [
    # ── DNS & Network ──────────────────────────────────────────────────────────
    {
        "id": "flush_dns",
        "name": "Flush DNS Cache",
        "desc": "Clears stale DNS entries for faster lookups",
        "impact": "LOW",
        "category": "DNS",
        "cmd": {
            "Windows": "ipconfig /flushdns",
            "Linux":   "systemd-resolve --flush-caches 2>/dev/null || resolvectl flush-caches 2>/dev/null || true",
            "Darwin":  "dscacheutil -flushcache; killall -HUP mDNSResponder",
        },
    },
    {
        "id": "fast_dns",
        "name": "Use Fast DNS  (1.1.1.1 / 8.8.8.8)",
        "desc": "Switches to Cloudflare / Google DNS for faster lookups",
        "impact": "MED",
        "category": "DNS",
        "cmd": {
            "Windows": ('netsh interface ip set dns "Ethernet" static 1.1.1.1 primary & '
                        'netsh interface ip add dns "Ethernet" 8.8.8.8 index=2 & '
                        'netsh interface ip set dns "Wi-Fi" static 1.1.1.1 primary & '
                        'netsh interface ip add dns "Wi-Fi" 8.8.8.8 index=2'),
            "Linux":   'echo "nameserver 1.1.1.1\nnameserver 8.8.8.8" | tee /etc/resolv.conf',
            "Darwin":  "networksetup -setdnsservers Wi-Fi 1.1.1.1 8.8.8.8",
        },
        "undo_cmd": {
            "Windows": ('netsh interface ip set dns "Ethernet" dhcp & '
                        'netsh interface ip set dns "Wi-Fi" dhcp'),
            "Linux":   "echo '' > /etc/resolv.conf",
            "Darwin":  "networksetup -setdnsservers Wi-Fi empty",
        },
    },
    # ── TCP Tweaks ─────────────────────────────────────────────────────────────
    {
        "id": "tcp_nodelay",
        "name": "TCP No-Delay  (disable Nagle)",
        "desc": "Reduces latency for small real-time game packets",
        "impact": "HIGH",
        "category": "TCP",
        "cmd": {
            "Windows": ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\'
                        'Tcpip\\Parameters\\Interfaces" /v TcpNoDelay /t REG_DWORD /d 1 /f & '
                        'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\'
                        'Tcpip\\Parameters\\Interfaces" /v TcpAckFrequency /t REG_DWORD /d 1 /f'),
            "Linux":   "sysctl -w net.ipv4.tcp_nodelay=1",
            "Darwin":  "sysctl -w net.inet.tcp.delayed_ack=0",
        },
        "undo_cmd": {
            "Windows": ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\'
                        'Tcpip\\Parameters\\Interfaces" /v TcpNoDelay /t REG_DWORD /d 0 /f'),
            "Linux":   "sysctl -w net.ipv4.tcp_nodelay=0",
            "Darwin":  "sysctl -w net.inet.tcp.delayed_ack=3",
        },
    },
    {
        "id": "tcp_buffer",
        "name": "Optimize TCP Buffer Sizes",
        "desc": "Increases network buffers to reduce packet loss",
        "impact": "MED",
        "category": "TCP",
        "cmd": {
            "Windows": ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AFD\\Parameters"'
                        ' /v DefaultSendWindow /t REG_DWORD /d 65536 /f & '
                        'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AFD\\Parameters"'
                        ' /v DefaultReceiveWindow /t REG_DWORD /d 65536 /f'),
            "Linux":   "sysctl -w net.core.rmem_max=16777216 net.core.wmem_max=16777216 net.core.rmem_default=262144 net.core.wmem_default=262144",
            "Darwin":  "sysctl -w kern.ipc.maxsockbuf=16777216",
        },
    },
    {
        "id": "tcp_timestamps",
        "name": "Disable TCP Timestamps",
        "desc": "Removes overhead from TCP timestamp options",
        "impact": "LOW",
        "category": "TCP",
        "cmd": {
            "Windows": ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters"'
                        ' /v Tcp1323Opts /t REG_DWORD /d 0 /f'),
            "Linux":   "sysctl -w net.ipv4.tcp_timestamps=0",
            "Darwin":  "sysctl -w net.inet.tcp.rfc1323=0",
        },
        "undo_cmd": {
            "Windows": ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters"'
                        ' /v Tcp1323Opts /t REG_DWORD /d 3 /f'),
            "Linux":   "sysctl -w net.ipv4.tcp_timestamps=1",
            "Darwin":  "sysctl -w net.inet.tcp.rfc1323=1",
        },
    },
    {
        "id": "tcp_autotuning",
        "name": "Enable TCP Auto-Tuning",
        "desc": "Lets Windows dynamically size TCP receive window",
        "impact": "MED",
        "category": "TCP",
        "cmd": {
            "Windows": "netsh int tcp set global autotuninglevel=normal",
            "Linux":   "sysctl -w net.ipv4.tcp_window_scaling=1",
            "Darwin":  "echo 'Auto-tuning enabled by default on macOS'",
        },
    },
    # ── Ethernet / Adapter ────────────────────────────────────────────────────
    {
        "id": "eth_jumbo",
        "name": "Enable Jumbo Frames  (9000 MTU)",
        "desc": "Larger packets = fewer interrupts, better throughput on LAN",
        "impact": "MED",
        "category": "Ethernet",
        "cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { Set-NetAdapterAdvancedProperty -Name $_.Name '
                        '-DisplayName \'Jumbo Packet\' -DisplayValue \'9014 Bytes\' -ErrorAction SilentlyContinue }"'),
            "Linux":   f"ip link set $(ip route | grep default | awk '{{print $5}}') mtu 9000 2>/dev/null || true",
            "Darwin":  "networksetup -setMTU Ethernet 9000 2>/dev/null || true",
        },
        "undo_cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { Set-NetAdapterAdvancedProperty -Name $_.Name '
                        '-DisplayName \'Jumbo Packet\' -DisplayValue \'Disabled\' -ErrorAction SilentlyContinue }"'),
            "Linux":   f"ip link set $(ip route | grep default | awk '{{print $5}}') mtu 1500 2>/dev/null || true",
            "Darwin":  "networksetup -setMTU Ethernet 1500 2>/dev/null || true",
        },
    },
    {
        "id": "eth_offload",
        "name": "Disable Large Send Offload  (LSO)",
        "desc": "Reduces latency spikes caused by driver-level batching",
        "impact": "HIGH",
        "category": "Ethernet",
        "cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { '
                        'Disable-NetAdapterLso -Name $_.Name -ErrorAction SilentlyContinue }"'),
            "Linux":   "ethtool -K $(ip route | grep default | awk '{print $5}') gso off gro off lro off 2>/dev/null || true",
            "Darwin":  "echo 'Use System Preferences > Network for offload settings'",
        },
    },
    {
        "id": "eth_flow_control",
        "name": "Disable Flow Control  (Ethernet)",
        "desc": "Prevents NIC pausing that causes latency spikes under load",
        "impact": "HIGH",
        "category": "Ethernet",
        "cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { Set-NetAdapterAdvancedProperty -Name $_.Name '
                        '-DisplayName \'Flow Control\' -DisplayValue \'Disabled\' -ErrorAction SilentlyContinue }"'),
            "Linux":   "ethtool -A $(ip route | grep default | awk '{print $5}') rx off tx off 2>/dev/null || true",
            "Darwin":  "echo 'Flow control managed by macOS'",
        },
    },
    {
        "id": "eth_int_moderation",
        "name": "Disable Interrupt Moderation  (Ethernet)",
        "desc": "Delivers packets to CPU instantly — reduces latency at cost of CPU",
        "impact": "HIGH",
        "category": "Ethernet",
        "cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { Set-NetAdapterAdvancedProperty -Name $_.Name '
                        '-DisplayName \'Interrupt Moderation\' -DisplayValue \'Disabled\' -ErrorAction SilentlyContinue }"'),
            "Linux":   "ethtool -C $(ip route | grep default | awk '{print $5}') rx-usecs 0 2>/dev/null || true",
            "Darwin":  "echo 'Interrupt moderation managed by macOS'",
        },
    },
    {
        "id": "eth_power_mgmt",
        "name": "Disable NIC Power Management",
        "desc": "Stops Windows from throttling your network card to save power",
        "impact": "MED",
        "category": "Ethernet",
        "cmd": {
            "Windows": ('powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                        'ForEach-Object { $dev = Get-WmiObject Win32_NetworkAdapter | '
                        'Where-Object {$_.NetConnectionID -eq $_.Name}; '
                        'Set-NetAdapterPowerManagement -Name $_.Name -WakeOnMagicPacket Disabled '
                        '-WakeOnPattern Disabled -ErrorAction SilentlyContinue }"'),
            "Linux":   "ethtool -s $(ip route | grep default | awk '{print $5}') wol d 2>/dev/null || true",
            "Darwin":  "echo 'Use System Preferences > Energy Saver'",
        },
    },
    # ── System / Windows ──────────────────────────────────────────────────────
    {
        "id": "qos",
        "name": "Set QoS Network Priority",
        "desc": "Prioritizes game traffic over background downloads",
        "impact": "HIGH",
        "category": "System",
        "cmd": {
            "Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Psched"'
                        ' /v NonBestEffortLimit /t REG_DWORD /d 0 /f'),
            "Linux":   "tc qdisc add dev $(ip route | grep default | awk '{print $5}') root fq 2>/dev/null || true",
            "Darwin":  "echo 'Use System Preferences > Network for QoS'",
        },
    },
    {
        "id": "disable_updates",
        "name": "Pause Windows Update",
        "desc": "Stops update downloads stealing bandwidth mid-game",
        "impact": "MED",
        "category": "System",
        "cmd": {
            "Windows": "sc stop wuauserv & sc config wuauserv start= disabled",
            "Linux":   "echo 'Not applicable on Linux'",
            "Darwin":  "echo 'Use System Preferences > Software Update'",
        },
        "undo_cmd": {
            "Windows": "sc config wuauserv start= auto & sc start wuauserv",
            "Linux":   "echo 'N/A'",
            "Darwin":  "echo 'N/A'",
        },
    },
    {
        "id": "disable_nagle_global",
        "name": "Disable Windows Auto-Tuning (Heuristics)",
        "desc": "Turns off heuristics that can degrade gaming performance",
        "impact": "MED",
        "category": "System",
        "cmd": {
            "Windows": "netsh int tcp set heuristics disabled & netsh int tcp set global congestionprovider=ctcp",
            "Linux":   "sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null || true",
            "Darwin":  "echo 'Managed by macOS'",
        },
    },
    {
        "id": "network_throttle",
        "name": "Remove Network Throttle Index",
        "desc": "Removes Windows multimedia throttle that limits network during media",
        "impact": "MED",
        "category": "System",
        "cmd": {
            "Windows": ('reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\'
                        'Multimedia\\SystemProfile" /v NetworkThrottlingIndex /t REG_DWORD /d 4294967295 /f'),
            "Linux":   "echo 'N/A on Linux'",
            "Darwin":  "echo 'N/A on macOS'",
        },
    },
    {
        "id": "game_priority",
        "name": "Set System Responsiveness for Games",
        "desc": "Tells Windows to prioritize real-time tasks like games",
        "impact": "MED",
        "category": "System",
        "cmd": {
            "Windows": ('reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\'
                        'Multimedia\\SystemProfile" /v SystemResponsiveness /t REG_DWORD /d 0 /f'),
            "Linux":   "echo 'N/A on Linux'",
            "Darwin":  "echo 'N/A on macOS'",
        },
    },
]

CATEGORIES = ["All", "DNS", "TCP", "Ethernet", "System"]

# ─────────────────────────────────────────────────────────────────────────────
# Fortnite-specific tweaks
# ─────────────────────────────────────────────────────────────────────────────
FORTNITE_TWEAKS = [
    # ── FPS & Rendering ───────────────────────────────────────────────────────
    {
        "id": "fn_fullscreen",
        "name": "Force Fullscreen Mode",
        "desc": "Sets Fortnite GameUserSettings to Fullscreen (FullscreenMode=1). Fullscreen gives lower input latency than windowed/borderless.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"FullscreenMode=\d\",\"FullscreenMode=1\" | Set-Content $p; '
                r'  (Get-Content $p) -replace \"LastConfirmedFullscreenMode=\d\",\"LastConfirmedFullscreenMode=1\" | Set-Content $p '
                r'} else { Write-Host \"GameUserSettings.ini not found — launch Fortnite first\" }"'
            ),
            "Linux":  "echo 'Fortnite runs via Epic Games on Windows only'",
            "Darwin": "echo 'Fortnite runs via Epic Games on Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"FullscreenMode=\d\",\"FullscreenMode=2\" | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_fps_cap_off",
        "name": "Remove FPS Cap  (unlock framerate)",
        "desc": "Sets FrameRateLimit=0 in GameUserSettings — uncaps FPS so you can hit your monitor's max refresh rate.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"FrameRateLimit=[\d.]+\",\"FrameRateLimit=0.000000\" | Set-Content $p '
                r'} else { Write-Host \"GameUserSettings.ini not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"FrameRateLimit=[\d.]+\",\"FrameRateLimit=240.000000\" | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_low_settings",
        "name": "Apply Low / Performance Graphics",
        "desc": "Sets textures, shadows, effects to Low/Off in GameUserSettings for maximum FPS.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"sg\.ShadowQuality=\d\",\"sg.ShadowQuality=0\"; '
                r'  $c = $c -replace \"sg\.TextureQuality=\d\",\"sg.TextureQuality=0\"; '
                r'  $c = $c -replace \"sg\.EffectsQuality=\d\",\"sg.EffectsQuality=0\"; '
                r'  $c = $c -replace \"sg\.PostProcessQuality=\d\",\"sg.PostProcessQuality=0\"; '
                r'  $c = $c -replace \"sg\.FoliageQuality=\d\",\"sg.FoliageQuality=0\"; '
                r'  $c = $c -replace \"sg\.AntiAliasingQuality=\d\",\"sg.AntiAliasingQuality=0\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"GameUserSettings.ini not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "fn_rendering_api",
        "name": "Switch to DirectX 12 / Performance Mode",
        "desc": "Adds -dx12 launch arg and enables Performance rendering mode for extra FPS on modern GPUs.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"PreferredGraphicsAPI=\w+\",\"PreferredGraphicsAPI=DX12\"; '
                r'  $c = $c -replace \"bPreferD3d12InVK=\w+\",\"bPreferD3d12InVK=True\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"GameUserSettings.ini not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "fn_vsync_off",
        "name": "Disable VSync",
        "desc": "Turns off VSync in GameUserSettings — eliminates input lag added by frame sync.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"bUseVSync=\w+\",\"bUseVSync=False\" | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"Not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"bUseVSync=\w+\",\"bUseVSync=True\" | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_motion_blur_off",
        "name": "Disable Motion Blur",
        "desc": "Removes motion blur from Fortnite config — clearer visuals and slightly better performance.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"bMotionBlur=\w+\",\"bMotionBlur=False\"; '
                r'  $c = $c -replace \"MotionBlurQuality=\d\",\"MotionBlurQuality=0\"; '
                r'  $c | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    # ── Network / Ping ────────────────────────────────────────────────────────
    {
        "id": "fn_ping_eac",
        "name": "Prioritize Fortnite in QoS (EpicGames)",
        "desc": "Adds a QoS policy rule that gives FortniteClient-Win64-Shipping.exe highest network priority.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                'New-NetQosPolicy -Name FortniteQoS '
                '-AppPathNameMatchCondition \\"FortniteClient-Win64-Shipping.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; Write-Host Done"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                'powershell -Command "'
                'Remove-NetQosPolicy -Name FortniteQoS -Confirm:$false -ErrorAction SilentlyContinue"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_disable_nagle",
        "name": "Disable Nagle for Fortnite  (TcpNoDelay)",
        "desc": "Ensures all Fortnite TCP packets are sent immediately without buffering delays.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpNoDelay /t REG_DWORD /d 1 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpAckFrequency /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_nodelay=1",
            "Darwin": "sysctl -w net.inet.tcp.delayed_ack=0",
        },
    },
    {
        "id": "fn_preferred_server",
        "name": "Ping Fortnite Servers & Log Best Region",
        "desc": "Pings Epic's matchmaking endpoints and logs the lowest-latency region to the activity log.",
        "category": "Network",
        "impact": "INFO",
        "cmd": {
            "Windows": (
                "ping -n 2 matchmaking.epicgames.com & "
                "ping -n 2 fortnite-public-service-prod11.ol.epicgames.com"
            ),
            "Linux":  "ping -c 2 matchmaking.epicgames.com",
            "Darwin": "ping -c 2 matchmaking.epicgames.com",
        },
    },
    {
        "id": "fn_bandwidth_reserve",
        "name": "Reserve 100% Bandwidth for Games",
        "desc": "Removes Windows' 20% QoS bandwidth reservation so Fortnite gets the full pipe.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Psched" '
                '/v NonBestEffortLimit /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    # ── CPU & Process ─────────────────────────────────────────────────────────
    {
        "id": "fn_high_priority",
        "name": "Set Fortnite Process to High Priority",
        "desc": "Uses WMIC to elevate FortniteClient-Win64-Shipping.exe CPU scheduling priority.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                '$p = Get-Process -Name FortniteClient-Win64-Shipping -ErrorAction SilentlyContinue; '
                'if ($p) { $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High; '
                'Write-Host \\"Priority set to High\\" } '
                'else { Write-Host \\"Fortnite not running — start the game first\\" }"'
            ),
            "Linux":  "echo 'Start Fortnite first, then reapply'",
            "Darwin": "echo 'macOS manages priority automatically'",
        },
    },
    {
        "id": "fn_power_plan",
        "name": "Enable High Performance Power Plan",
        "desc": "Switches Windows power plan to High Performance — prevents CPU throttling mid-game.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "Linux":   "cpupower frequency-set -g performance 2>/dev/null || true",
            "Darwin":  "echo 'macOS manages power automatically'",
        },
        "undo_cmd": {
            "Windows": "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e",
            "Linux":   "cpupower frequency-set -g powersave 2>/dev/null || true",
            "Darwin":  "echo 'N/A'",
        },
    },
    {
        "id": "fn_game_mode",
        "name": "Enable Windows Game Mode",
        "desc": "Turns on Windows Game Mode — focuses CPU/GPU resources on the foreground game.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 1 /f & '
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AllowAutoGameMode /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_disable_xbox_dvr",
        "name": "Disable Xbox Game Bar / DVR",
        "desc": "Turns off Game Bar screen capture overlay that steals CPU and causes FPS drops.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\GameDVR" '
                '/v AllowGameDVR /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_disable_fullscreen_opt",
        "name": "Disable Fullscreen Optimization (Fortnite EXE)",
        "desc": "Prevents Windows from overriding Fortnite fullscreen with a borderless window, which adds latency.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$exe = \"$env:LOCALAPPDATA\FortniteGame\Binaries\Win64\FortniteClient-Win64-Shipping.exe\"; '
                r'if (Test-Path $exe) { '
                r'  $key = \"HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers\"; '
                r'  Set-ItemProperty -Path $key -Name $exe -Value \"DISABLEDXMAXIMIZEDWINDOWEDMODE\" '
                r'  -ErrorAction SilentlyContinue; Write-Host Done '
                r'} else { Write-Host \"Fortnite exe not found — install Fortnite first\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    # ── System Cleanup ────────────────────────────────────────────────────────
    {
        "id": "fn_kill_background",
        "name": "Kill Common Background Processes",
        "desc": "Terminates Discord overlay, OneDrive sync, Teams, and Spotify — frees RAM and CPU for Fortnite.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                "taskkill /F /IM OneDrive.exe /T 2>nul & "
                "taskkill /F /IM Discord.exe /T 2>nul & "
                "taskkill /F /IM Teams.exe /T 2>nul & "
                "taskkill /F /IM Spotify.exe /T 2>nul & "
                "taskkill /F /IM chrome.exe /T 2>nul & "
                "echo Done — background apps closed"
            ),
            "Linux":  "killall discord spotify teams chromium 2>/dev/null || true",
            "Darwin": "killall Discord Spotify 'Microsoft Teams' 2>/dev/null || true",
        },
    },
    {
        "id": "fn_clear_shader_cache",
        "name": "Clear Fortnite Shader Cache",
        "desc": "Deletes cached shaders so Fortnite rebuilds them fresh — fixes stutters after updates.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$paths = @('
                r'  \"$env:LOCALAPPDATA\FortniteGame\Saved\PipelineCaches\", '
                r'  \"$env:LOCALAPPDATA\FortniteGame\Saved\ShaderCache\", '
                r'  \"$env:LOCALAPPDATA\D3DSCache\" '
                r'); foreach ($p in $paths) { '
                r'  if (Test-Path $p) { Remove-Item \"$p\*\" -Recurse -Force -ErrorAction SilentlyContinue; '
                r'  Write-Host \"Cleared $p\" } '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "fn_pagefile",
        "name": "Flush Windows Standby Memory",
        "desc": "Releases standby memory so Fortnite has more free RAM available on launch.",
        "category": "Cleanup",
        "impact": "LOW",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                '[System.GC]::Collect(); '
                '[System.GC]::WaitForPendingFinalizers(); '
                'Write-Host \\"Standby memory flushed\\""'
            ),
            "Linux":  "sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true",
            "Darwin": "purge 2>/dev/null || true",
        },
    },
    {
        "id": "fn_temp_clean",
        "name": "Clean Temp Files",
        "desc": "Deletes Windows TEMP folder contents — removes clutter that can slow disk I/O.",
        "category": "Cleanup",
        "impact": "LOW",
        "cmd": {
            "Windows": 'cmd /c "del /f /s /q %TEMP%\\* 2>nul & rd /s /q %TEMP% 2>nul & md %TEMP% 2>nul & echo Done"',
            "Linux":   "rm -rf /tmp/* 2>/dev/null || true",
            "Darwin":  "rm -rf /private/tmp/* 2>/dev/null || true",
        },
    },
    # ── Extra FPS Tweaks ──────────────────────────────────────────────────────
    {
        "id": "fn_hardware_accel_gpu",
        "name": "Enable Hardware-Accelerated GPU Scheduling (HAGS)",
        "desc": "Enables HAGS in Windows — reduces GPU latency and improves frame pacing for Fortnite on modern GPUs.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\GraphicsDrivers" '
                '/v HwSchMode /t REG_DWORD /d 2 /f'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\GraphicsDrivers" '
                '/v HwSchMode /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_nvidia_profile",
        "name": "Optimize NVIDIA Control Panel for Fortnite",
        "desc": "Sets NVIDIA Power Management to Max Performance and enables Low Latency Mode=Ultra via registry for Fortnite.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000" '
                '/v PerfLevelSrc /t REG_DWORD /d 8738 /f & '
                'powershell -Command "& {$r = \'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000\'; '
                'Set-ItemProperty -Path $r -Name PerfLevelSrc -Value 8738 -ErrorAction SilentlyContinue; Write-Host Done}"'
            ),
            "Linux":  "nvidia-settings -a '[gpu:0]/GpuPowerMizerMode=1' 2>/dev/null || true",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "fn_disable_core_parking",
        "name": "Disable CPU Core Parking",
        "desc": "Forces all CPU cores to stay active — eliminates frame drops caused by parked cores waking up during Fortnite builds.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR CPMINCORES 100; '
                'powercfg /setactive SCHEME_CURRENT; Write-Host Done"'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": (
                'powershell -Command "powercfg /setacvalueindex SCHEME_CURRENT SUB_PROCESSOR CPMINCORES 0; '
                'powercfg /setactive SCHEME_CURRENT; Write-Host Done"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "fn_texture_streaming",
        "name": "Disable Texture Streaming (Eliminate Load Stutters)",
        "desc": "Adds bUseTextureStreaming=False to Fortnite's Scalability config — loads all textures upfront, eliminating mid-game pop-in and stutters.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  if ($c -notmatch \"bUseTextureStreaming\") { Add-Content $p \"`nbUseTextureStreaming=False\" }; '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"bUseTextureStreaming=\w+\",\"bUseTextureStreaming=False\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"GameUserSettings.ini not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "fn_nvidia_lowlatency",
        "name": "Enable NVIDIA Ultra Low Latency Mode (NvCP Registry)",
        "desc": "Sets Ultra Low Latency mode in NVIDIA driver via registry — renders frames just-in-time before GPU needs them, cutting input lag by up to 33%.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\NVIDIA Corporation\\Global\\NvTweak" '
                '/v EnableMidFramePreemption /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0000" '
                '/v "OGL_MaxFramesAllowed" /t REG_SZ /d "1" /f'
            ),
            "Linux":  "__GL_YIELD=USLEEP nvidia-settings -a '[gpu:0]/GpuPowerMizerMode=1' 2>/dev/null || true",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "fn_resolution_scale",
        "name": "Set 3D Resolution to 100% (Disable Dynamic Resolution)",
        "desc": "Locks 3D resolution at 100% and disables dynamic resolution scaling in GameUserSettings — stable frame times, no resolution dips during fights.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\FortniteGame\Saved\Config\WindowsClient\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"ResolutionSizeX=\d+\",\"ResolutionSizeX=1920\"; '
                r'  $c = $c -replace \"ResolutionSizeY=\d+\",\"ResolutionSizeY=1080\"; '
                r'  $c = $c -replace \"bUseDynamicResolution=\w+\",\"bUseDynamicResolution=False\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"GameUserSettings.ini not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    # ── Extra Network / Ping Tweaks ───────────────────────────────────────────
    {
        "id": "fn_network_adapter_power",
        "name": "Disable Adapter Power Saving (Wake-on-LAN off)",
        "desc": "Turns off Wake-on-LAN and energy-efficient Ethernet on all active adapters — stops NIC from micro-sleeping and spiking ping.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                'ForEach-Object { '
                'Disable-NetAdapterPowerManagement -Name $_.Name -ErrorAction SilentlyContinue; '
                'Set-NetAdapterAdvancedProperty -Name $_.Name -DisplayName \'Energy Efficient Ethernet\' -DisplayValue \'Disabled\' -ErrorAction SilentlyContinue; '
                'Set-NetAdapterAdvancedProperty -Name $_.Name -DisplayName \'Wake on Magic Packet\' -DisplayValue \'Disabled\' -ErrorAction SilentlyContinue '
                '}; Write-Host Done"'
            ),
            "Linux":  "ethtool -s $(ip route | grep default | awk '{print $5}') wol d 2>/dev/null || true",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "fn_recv_side_scaling",
        "name": "Enable Receive Side Scaling (RSS) for Multi-Core NIC",
        "desc": "Spreads NIC interrupt processing across multiple CPU cores — reduces single-core bottleneck that causes ping spikes in Fortnite.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                'ForEach-Object { Enable-NetAdapterRss -Name $_.Name -ErrorAction SilentlyContinue }; '
                'netsh int tcp set global rss=enabled; Write-Host Done"'
            ),
            "Linux":  "ethtool -K $(ip route | grep default | awk '{print $5}') rxhash on 2>/dev/null || true",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "fn_udp_buffer",
        "name": "Boost UDP / Socket Buffer Sizes",
        "desc": "Increases Windows socket send/receive buffers for UDP — Fortnite uses UDP for game traffic; larger buffers prevent burst packet loss.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AFD\\Parameters" '
                '/v DefaultSendWindow /t REG_DWORD /d 131072 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AFD\\Parameters" '
                '/v DefaultReceiveWindow /t REG_DWORD /d 131072 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\AFD\\Parameters" '
                '/v FastSendDatagramThreshold /t REG_DWORD /d 1024 /f'
            ),
            "Linux":  "sysctl -w net.core.rmem_max=131072 net.core.wmem_max=131072 2>/dev/null || true",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "fn_fortnite_region_ping",
        "name": "Ping All Fortnite Regions & Show Best",
        "desc": "Pings all Epic Games regional matchmaking endpoints (NA-East, NA-West, EU, Asia, OCE) and logs latency so you can pick the best matchmaking region.",
        "category": "Network",
        "impact": "INFO",
        "cmd": {
            "Windows": (
                "echo === Fortnite Region Ping Test === & "
                "echo NA-East: & ping -n 2 fortnite-public-service-prod11.ol.epicgames.com & "
                "echo NA-West: & ping -n 2 fortnite-public-service-live-public-1.ol.epicgames.com & "
                "echo EU: & ping -n 2 fortnite-public-service-live-eu.ol.epicgames.com & "
                "echo Brazil: & ping -n 2 fortnite-public-service-live-br.ol.epicgames.com & "
                "echo Done"
            ),
            "Linux":  "ping -c 2 fortnite-public-service-prod11.ol.epicgames.com",
            "Darwin": "ping -c 2 fortnite-public-service-prod11.ol.epicgames.com",
        },
    },
    {
        "id": "fn_epicgames_qos_dscp",
        "name": "DSCP 46 (EF) Priority for All Epic Games Traffic",
        "desc": "Sets Expedited Forwarding DSCP tag on all traffic to Epic Games IPs — routers that honour QoS will prioritise your Fortnite packets over everything else.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                'New-NetQosPolicy -Name EpicGamesQoS '
                '-AppPathNameMatchCondition \\"EpicGamesLauncher.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; '
                'New-NetQosPolicy -Name FortniteEACQoS '
                '-AppPathNameMatchCondition \\"FortniteClient-Win64-Shipping_EAC.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; Write-Host Done"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                'powershell -Command "'
                'Remove-NetQosPolicy -Name EpicGamesQoS -Confirm:$false -ErrorAction SilentlyContinue; '
                'Remove-NetQosPolicy -Name FortniteEACQoS -Confirm:$false -ErrorAction SilentlyContinue; Write-Host Done"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
]

FN_CATEGORIES = ["All", "FPS", "Network", "CPU", "Cleanup"]

# ─────────────────────────────────────────────────────────────────────────────
# Valorant-specific tweaks
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# Rainbow Six Siege-specific tweaks
# ─────────────────────────────────────────────────────────────────────────────
R6_TWEAKS = [
    # ── FPS & Graphics ────────────────────────────────────────────────────────
    {
        "id": "r6_fps_unlock",
        "name": "Unlock FPS Cap (Remove 200 FPS Limit)",
        "desc": "Sets MaxFPS to 0 in GameSettings.ini — removes Siege's 200 FPS cap so your GPU can push your monitor's full refresh rate.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$dirs = @('
                r'  \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\", '
                r'  \"$env:LOCALAPPDATA\Ubisoft Game Launcher\" '
                r'); '
                r'$found = $false; '
                r'foreach ($base in $dirs) { '
                r'  Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'    $c = Get-Content $_.FullName; '
                r'    $c = $c -replace \"MaxFPS=\d+\",\"MaxFPS=0\"; '
                r'    $c | Set-Content $_.FullName; '
                r'    Write-Host \"Updated: $($_.FullName)\"; '
                r'    $found = $true '
                r'  } '
                r'}; '
                r'if (-not $found) { Write-Host \"GameSettings.ini not found — launch Siege first\" }"'
            ),
            "Linux":  "echo 'Siege runs on Windows/Ubisoft Connect'",
            "Darwin": "echo 'Siege runs on Windows/Ubisoft Connect'",
        },
    },
    {
        "id": "r6_vsync_off",
        "name": "Disable VSync in Siege",
        "desc": "Sets VSync=0 in GameSettings.ini — removes frame-sync input lag. Critical for low-latency peeker's advantage in Siege.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  $c = Get-Content $_.FullName; '
                r'  $c = $c -replace \"VSync=\w+\",\"VSync=0\"; '
                r'  $c = $c -replace \"VSync=True\",\"VSync=False\"; '
                r'  $c | Set-Content $_.FullName; Write-Host \"VSync disabled: $($_.FullName)\" '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  (Get-Content $_.FullName) -replace \"VSync=\w+\",\"VSync=1\" | Set-Content $_.FullName '
                r'}"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "r6_low_graphics",
        "name": "Apply Lowest Graphics for Max FPS",
        "desc": "Sets Texture, Shadow, Reflection, LOD, and Ambient Occlusion to minimum in GameSettings.ini — maximum FPS and clearer enemy visibility.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  $c = Get-Content $_.FullName; '
                r'  $c = $c -replace \"TextureQuality=\d\",\"TextureQuality=0\"; '
                r'  $c = $c -replace \"ShadowQuality=\d\",\"ShadowQuality=0\"; '
                r'  $c = $c -replace \"ReflectionQuality=\d\",\"ReflectionQuality=0\"; '
                r'  $c = $c -replace \"LensFlare=\w+\",\"LensFlare=False\"; '
                r'  $c = $c -replace \"AmbientOcclusion=\w+\",\"AmbientOcclusion=False\"; '
                r'  $c = $c -replace \"PostFXQuality=\d\",\"PostFXQuality=0\"; '
                r'  $c = $c -replace \"LODQuality=\d\",\"LODQuality=0\"; '
                r'  $c | Set-Content $_.FullName; Write-Host \"Low graphics applied: $($_.FullName)\" '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "r6_disable_dof",
        "name": "Disable Depth of Field & Chromatic Aberration",
        "desc": "Removes depth-of-field blur and chromatic aberration from Siege config — sharper image, easier to spot enemies through scopes.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  $c = Get-Content $_.FullName; '
                r'  $c = $c -replace \"DepthOfField=\w+\",\"DepthOfField=False\"; '
                r'  $c = $c -replace \"ChromaticAberration=\w+\",\"ChromaticAberration=False\"; '
                r'  $c = $c -replace \"MotionBlur=\w+\",\"MotionBlur=False\"; '
                r'  $c = $c -replace \"BloomEnabled=\w+\",\"BloomEnabled=False\"; '
                r'  $c | Set-Content $_.FullName; Write-Host Done '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "r6_fullscreen",
        "name": "Force Exclusive Fullscreen Mode",
        "desc": "Sets DisplayMode=FullScreen in GameSettings.ini — exclusive fullscreen has lowest input latency vs borderless windowed.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  $c = Get-Content $_.FullName; '
                r'  $c = $c -replace \"DisplayMode=\w+\",\"DisplayMode=FullScreen\"; '
                r'  $c | Set-Content $_.FullName; Write-Host Done '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$base = \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\"; '
                r'Get-ChildItem -Path $base -Recurse -Filter \"GameSettings.ini\" -ErrorAction SilentlyContinue | ForEach-Object { '
                r'  (Get-Content $_.FullName) -replace \"DisplayMode=\w+\",\"DisplayMode=Windowed\" | Set-Content $_.FullName '
                r'}"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "r6_dx11_flag",
        "name": "Force DirectX 11 Launch Flag (Stability + Perf)",
        "desc": "Adds -dx11 to Siege's Ubisoft Connect launch args via registry — DX11 is more stable and often faster than DX12 in Siege on most systems.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Ubisoft\\Launcher\\Installs" '
                '/v GameLaunchOptions /t REG_SZ /d "-dx11" /f 2>nul & '
                'echo Note: Also set in Ubisoft Connect > Game Properties > Launch Arguments: -dx11'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "r6_disable_fullscreen_opt",
        "name": "Disable Fullscreen Optimizations on Siege EXE",
        "desc": "Prevents Windows from converting Siege fullscreen to borderless — true exclusive fullscreen reduces input lag.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$paths = @('
                r'  \"$env:ProgramFiles(x86)\Ubisoft\Ubisoft Game Launcher\games\Tom Clancy\'s Rainbow Six Siege\RainbowSix.exe\", '
                r'  \"$env:ProgramFiles\Ubisoft\Ubisoft Game Launcher\games\Tom Clancy\'s Rainbow Six Siege\RainbowSix.exe\" '
                r'); '
                r'$key = \"HKCU:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\AppCompatFlags\\Layers\"; '
                r'if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }; '
                r'foreach ($exe in $paths) { '
                r'  if (Test-Path $exe) { '
                r'    Set-ItemProperty -Path $key -Name $exe -Value \"DISABLEDXMAXIMIZEDWINDOWEDMODE\" -ErrorAction SilentlyContinue; '
                r'    Write-Host \"Applied: $exe\" '
                r'  } '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    # ── Network / Ping ────────────────────────────────────────────────────────
    {
        "id": "r6_qos_priority",
        "name": "QoS Priority for Rainbow Six Siege (DSCP 46)",
        "desc": "Creates a Windows QoS rule giving RainbowSix.exe Expedited Forwarding (DSCP 46) — highest network priority, reducing packet queuing delay.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                'New-NetQosPolicy -Name R6SiegeQoS '
                '-AppPathNameMatchCondition \\"RainbowSix.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; '
                'New-NetQosPolicy -Name R6EACQoS '
                '-AppPathNameMatchCondition \\"RainbowSix_BE.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; Write-Host Done"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                'powershell -Command "'
                'Remove-NetQosPolicy -Name R6SiegeQoS -Confirm:$false -ErrorAction SilentlyContinue; '
                'Remove-NetQosPolicy -Name R6EACQoS -Confirm:$false -ErrorAction SilentlyContinue"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "r6_tcp_nodelay",
        "name": "Disable Nagle / TcpNoDelay for Siege",
        "desc": "Sets TcpNoDelay=1 and TcpAckFrequency=1 — Siege uses TCP for some game traffic; this ensures packets are sent instantly without buffering.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpNoDelay /t REG_DWORD /d 1 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpAckFrequency /t REG_DWORD /d 1 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters" '
                '/v TcpNoDelay /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_nodelay=1",
            "Darwin": "sysctl -w net.inet.tcp.delayed_ack=0",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpNoDelay /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_nodelay=0",
            "Darwin": "sysctl -w net.inet.tcp.delayed_ack=3",
        },
    },
    {
        "id": "r6_ping_ubisoft",
        "name": "Ping Ubisoft / Siege Servers",
        "desc": "Pings Ubisoft's matchmaking and game servers across regions — helps identify best data center for lowest Siege ping.",
        "category": "Network",
        "impact": "INFO",
        "cmd": {
            "Windows": (
                "echo === R6 Siege Server Ping Test === & "
                "echo Ubisoft Matchmaking: & ping -n 3 matchmaking.ubi.com & "
                "echo Ubisoft Services: & ping -n 3 public-ubiservices.ubi.com & "
                "echo Ubisoft CDN: & ping -n 3 cdn.ubi.com & "
                "echo Done"
            ),
            "Linux":  "ping -c 3 matchmaking.ubi.com",
            "Darwin": "ping -c 3 matchmaking.ubi.com",
        },
    },
    {
        "id": "r6_bandwidth_reserve",
        "name": "Remove Windows 20% Bandwidth Reservation",
        "desc": "Frees the bandwidth Windows holds back for background QoS — gives Siege the full pipe during ranked matches.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Psched" '
                '/v NonBestEffortLimit /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "r6_fast_dns",
        "name": "Switch to Cloudflare DNS (1.1.1.1)",
        "desc": "Sets DNS to 1.1.1.1 / 8.8.8.8 — faster Ubisoft matchmaking server resolution and potentially lower first-connection latency.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'netsh interface ip set dns "Ethernet" static 1.1.1.1 primary & '
                'netsh interface ip add dns "Ethernet" 8.8.8.8 index=2 & '
                'netsh interface ip set dns "Wi-Fi" static 1.1.1.1 primary & '
                'netsh interface ip add dns "Wi-Fi" 8.8.8.8 index=2 & '
                'ipconfig /flushdns'
            ),
            "Linux":  'echo "nameserver 1.1.1.1\nnameserver 8.8.8.8" | tee /etc/resolv.conf',
            "Darwin": "networksetup -setdnsservers Wi-Fi 1.1.1.1 8.8.8.8",
        },
        "undo_cmd": {
            "Windows": (
                'netsh interface ip set dns "Ethernet" dhcp & '
                'netsh interface ip set dns "Wi-Fi" dhcp'
            ),
            "Linux":  "echo '' > /etc/resolv.conf",
            "Darwin": "networksetup -setdnsservers Wi-Fi empty",
        },
    },
    # ── CPU & Process ─────────────────────────────────────────────────────────
    {
        "id": "r6_high_priority",
        "name": "Set Siege Process to High CPU Priority",
        "desc": "Elevates RainbowSix.exe CPU scheduling priority — OS serves Siege render loop first, reducing frame time variance.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                '$p = Get-Process -Name RainbowSix -ErrorAction SilentlyContinue; '
                'if ($p) { $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High; '
                'Write-Host \\"Priority set to High\\" } '
                'else { Write-Host \\"Siege not running — start the game first\\" }"'
            ),
            "Linux":  "echo 'Start Siege first, then reapply'",
            "Darwin": "echo 'macOS manages priority automatically'",
        },
    },
    {
        "id": "r6_power_plan",
        "name": "Activate High Performance Power Plan",
        "desc": "Switches Windows to High Performance — CPU stays at max clock during all Siege rounds, no throttle during clutch moments.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "Linux":   "cpupower frequency-set -g performance 2>/dev/null || true",
            "Darwin":  "echo 'macOS manages power automatically'",
        },
        "undo_cmd": {
            "Windows": "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e",
            "Linux":   "cpupower frequency-set -g powersave 2>/dev/null || true",
            "Darwin":  "echo 'N/A'",
        },
    },
    {
        "id": "r6_game_mode",
        "name": "Enable Windows Game Mode",
        "desc": "Activates Windows Game Mode — dedicates more CPU/GPU resources to Siege and reduces background task interference.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 1 /f & '
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AllowAutoGameMode /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": 'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 0 /f',
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "r6_disable_dvr",
        "name": "Disable Xbox Game Bar / DVR",
        "desc": "Disables Game Bar capture overlay — reclaims CPU/GPU stolen by background screen recording that drops Siege FPS.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\GameDVR" '
                '/v AllowGameDVR /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "r6_system_responsiveness",
        "name": "Max System Responsiveness for Siege",
        "desc": "Sets SystemResponsiveness=0 and removes NetworkThrottlingIndex — Windows gives real-time tasks (Siege frame loop) maximum CPU time slice.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v SystemResponsiveness /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v NetworkThrottlingIndex /t REG_DWORD /d 4294967295 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    # ── Cleanup ───────────────────────────────────────────────────────────────
    {
        "id": "r6_kill_background",
        "name": "Kill Background Apps Before Siege",
        "desc": "Closes Discord, OneDrive, Teams, Spotify, Chrome — frees RAM and prevents CPU contention that causes frame drops mid-round.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                "taskkill /F /IM OneDrive.exe /T 2>nul & "
                "taskkill /F /IM Discord.exe /T 2>nul & "
                "taskkill /F /IM Teams.exe /T 2>nul & "
                "taskkill /F /IM Spotify.exe /T 2>nul & "
                "taskkill /F /IM chrome.exe /T 2>nul & "
                "taskkill /F /IM msedge.exe /T 2>nul & "
                "echo Background apps terminated"
            ),
            "Linux":  "killall discord spotify teams chromium 2>/dev/null || true",
            "Darwin": "killall Discord Spotify 'Microsoft Teams' 2>/dev/null || true",
        },
    },
    {
        "id": "r6_clear_shader_cache",
        "name": "Clear Siege Shader Cache",
        "desc": "Deletes Siege's pipeline and shader caches — fixes compilation stutters and frame spikes after updates.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$paths = @('
                r'  \"$env:LOCALAPPDATA\PipelineCache\", '
                r'  \"$env:LOCALAPPDATA\D3DSCache\", '
                r'  \"$env:USERPROFILE\Documents\My Games\Rainbow Six Siege\" '
                r'); '
                r'foreach ($p in $paths) { '
                r'  if (Test-Path $p) { '
                r'    Get-ChildItem -Path $p -Recurse -Filter \"*.cache\" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; '
                r'    Get-ChildItem -Path $p -Recurse -Filter \"*.tmp\" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue; '
                r'    Write-Host \"Cleared: $p\" '
                r'  } '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "r6_flush_memory",
        "name": "Flush Standby RAM Before Siege",
        "desc": "Forces .NET GC and clears standby memory — gives Siege more free RAM on launch, reducing asset streaming hitches.",
        "category": "Cleanup",
        "impact": "LOW",
        "cmd": {
            "Windows": (
                'powershell -Command "[System.GC]::Collect(); '
                '[System.GC]::WaitForPendingFinalizers(); '
                'Write-Host \\"Standby memory flushed\\""'
            ),
            "Linux":  "sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true",
            "Darwin": "purge 2>/dev/null || true",
        },
    },
    {
        "id": "r6_pause_updates",
        "name": "Pause Windows Update During Session",
        "desc": "Stops Windows Update downloading in the background — prevents bandwidth and CPU spikes mid-match that spike ping.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": "sc stop wuauserv & sc config wuauserv start= disabled",
            "Linux":   "echo 'N/A on Linux'",
            "Darwin":  "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": "sc config wuauserv start= auto & sc start wuauserv",
            "Linux":   "echo 'N/A'",
            "Darwin":  "echo 'N/A'",
        },
    },
]

R6_CATEGORIES = ["All", "FPS", "Network", "CPU", "Cleanup"]

# ─────────────────────────────────────────────────────────────────────────────
# Miscellaneous Downloads — Performance Apps for a New PC
# ─────────────────────────────────────────────────────────────────────────────
MISC_DOWNLOADS = [
    # ── Browsers ──────────────────────────────────────────────────────────────
    {
        "id": "dl_brave",
        "name": "Brave Browser",
        "desc": "Privacy-focused browser with built-in ad blocker — faster page loads, no trackers, great for daily use and gaming research.",
        "category": "Browser",
        "url": "https://brave.com/download/",
        "direct_url": "https://laptop-updates.brave.com/latest/winx64",
        "color": "#fb542b",
        "icon": "🦁",
    },
    {
        "id": "dl_firefox",
        "name": "Mozilla Firefox",
        "desc": "Open-source browser with excellent privacy defaults and extension support. Lighter on RAM than Chrome — good for gaming PCs.",
        "category": "Browser",
        "url": "https://www.mozilla.org/firefox/download/",
        "direct_url": "https://download.mozilla.org/?product=firefox-latest&os=win64&lang=en-US",
        "color": "#ff7139",
        "icon": "🦊",
    },
    # ── Performance Utilities ─────────────────────────────────────────────────
    {
        "id": "dl_msi_afterburner",
        "name": "MSI Afterburner + RivaTuner",
        "desc": "The #1 GPU overclocking and monitoring tool. Shows FPS, GPU temp, VRAM usage as an in-game overlay. Essential for every gaming PC.",
        "category": "GPU Tools",
        "url": "https://www.msi.com/Landing/afterburner/graphics-cards",
        "direct_url": "https://download.msi.com/uti_exe/vga/MSIAfterburnerSetup.zip",
        "color": "#e53935",
        "icon": "🔥",
    },
    {
        "id": "dl_hwinfo",
        "name": "HWiNFO64",
        "desc": "Deep hardware monitoring tool — shows every sensor on your PC (CPU/GPU temps, clocks, power draw). Use with RTSS overlay for in-game stats.",
        "category": "System Monitor",
        "url": "https://www.hwinfo.com/download/",
        "direct_url": "https://www.hwinfo.com/download/",
        "color": "#00b0ff",
        "icon": "📊",
    },
    {
        "id": "dl_cpu_z",
        "name": "CPU-Z",
        "desc": "Shows detailed CPU, RAM, and motherboard info including actual memory frequency and XMP profile status. Essential for verifying system specs.",
        "category": "System Monitor",
        "url": "https://www.cpuid.com/softwares/cpu-z.html",
        "direct_url": "https://download.cpuid.com/cpu-z/cpu-z_2.12-en.exe",
        "color": "#0288d1",
        "icon": "🧠",
    },
    {
        "id": "dl_gpu_z",
        "name": "GPU-Z",
        "desc": "Shows GPU model, VRAM, clocks, and real-time sensor data. Verifies GPU is running at correct PCIe slot speed (Gen 3/4/5).",
        "category": "System Monitor",
        "url": "https://www.techpowerup.com/gpuz/",
        "direct_url": "https://download.techpowerup.com/GPU-Z.2.59.0.exe",
        "color": "#43a047",
        "icon": "🖥",
    },
    {
        "id": "dl_crystaldisk",
        "name": "CrystalDiskInfo",
        "desc": "Monitors SSD/HDD health via S.M.A.R.T. data — shows drive temperature, wear level, and warns before drive failure.",
        "category": "System Monitor",
        "url": "https://crystalmark.info/en/software/crystaldiskinfo/",
        "direct_url": "https://crystalmark.info/en/software/crystaldiskinfo/",
        "color": "#7b1fa2",
        "icon": "💾",
    },
    {
        "id": "dl_speccy",
        "name": "Speccy",
        "desc": "Full system specs snapshot — CPU, RAM, GPU, storage, motherboard, temps all in one view. Good for quick system overview.",
        "category": "System Monitor",
        "url": "https://www.piriform.com/speccy/download",
        "direct_url": "https://www.piriform.com/speccy/download",
        "color": "#039be5",
        "icon": "📋",
    },
    # ── Driver Tools ──────────────────────────────────────────────────────────
    {
        "id": "dl_ddu",
        "name": "Display Driver Uninstaller (DDU)",
        "desc": "The safest way to fully remove NVIDIA/AMD/Intel GPU drivers before a clean reinstall. Essential when upgrading your GPU.",
        "category": "Driver Tools",
        "url": "https://www.wagnardsoft.com/",
        "direct_url": "https://www.wagnardsoft.com/",
        "color": "#f57f17",
        "icon": "🔧",
    },
    {
        "id": "dl_nvidia_drivers",
        "name": "NVIDIA GeForce Drivers",
        "desc": "Official NVIDIA GPU drivers. Always download fresh after a new build. Recommended: use Game Ready drivers for FPS titles.",
        "category": "Driver Tools",
        "url": "https://www.nvidia.com/Download/index.aspx",
        "direct_url": "https://www.nvidia.com/Download/index.aspx",
        "color": "#76b900",
        "icon": "🟢",
    },
    {
        "id": "dl_amd_drivers",
        "name": "AMD Radeon Software / Adrenalin",
        "desc": "Official AMD GPU and chipset drivers. Includes Radeon Anti-Lag, Radeon Boost, and FSR upscaling controls.",
        "category": "Driver Tools",
        "url": "https://www.amd.com/en/support",
        "direct_url": "https://www.amd.com/en/support",
        "color": "#ed1c24",
        "icon": "🔴",
    },
    # ── Gaming Utilities ──────────────────────────────────────────────────────
    {
        "id": "dl_discord",
        "name": "Discord",
        "desc": "Voice chat, community servers, and game overlay. Essential for team comms in Fortnite, Siege, and Valorant.",
        "category": "Gaming",
        "url": "https://discord.com/download",
        "direct_url": "https://discord.com/api/downloads/distributions/app/installers/latest?channel=stable&platform=win&arch=x86",
        "color": "#5865f2",
        "icon": "💬",
    },
    {
        "id": "dl_playnite",
        "name": "Playnite (Game Library Manager)",
        "desc": "Unified game launcher for Steam, Epic, Ubisoft Connect, EA App, GOG and more — one place to launch all your games.",
        "category": "Gaming",
        "url": "https://playnite.link/download.html",
        "direct_url": "https://github.com/JosefNemec/Playnite/releases/latest",
        "color": "#e040fb",
        "icon": "🎮",
    },
    {
        "id": "dl_epic",
        "name": "Epic Games Launcher",
        "desc": "Required to play Fortnite. Also offers free games weekly. Essential download on any gaming PC.",
        "category": "Gaming",
        "url": "https://store.epicgames.com/download",
        "direct_url": "https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/installer/download/EpicGamesLauncherInstaller.msi",
        "color": "#2c2c2c",
        "icon": "🏪",
    },
    {
        "id": "dl_ubisoft_connect",
        "name": "Ubisoft Connect",
        "desc": "Required to play Rainbow Six Siege and other Ubisoft titles. Handles multiplayer and anti-cheat for Siege.",
        "category": "Gaming",
        "url": "https://ubisoftconnect.com/en-US/",
        "direct_url": "https://ubisoftconnect.com/en-US/",
        "color": "#0070ff",
        "icon": "🔷",
    },
    {
        "id": "dl_steam",
        "name": "Steam",
        "desc": "The world's largest PC gaming platform. Essential for most game libraries including CS2, Apex Legends, and thousands of others.",
        "category": "Gaming",
        "url": "https://store.steampowered.com/about/",
        "direct_url": "https://cdn.akamai.steamstatic.com/client/installer/SteamSetup.exe",
        "color": "#1b2838",
        "icon": "🎲",
    },
    # ── Utilities & Tools ─────────────────────────────────────────────────────
    {
        "id": "dl_7zip",
        "name": "7-Zip",
        "desc": "Free, open-source file archiver supporting ZIP, RAR, 7z and 60+ formats. Lighter and faster than WinRAR.",
        "category": "Utilities",
        "url": "https://www.7-zip.org/download.html",
        "direct_url": "https://www.7-zip.org/a/7z2407-x64.exe",
        "color": "#00897b",
        "icon": "📦",
    },
    {
        "id": "dl_vlc",
        "name": "VLC Media Player",
        "desc": "Plays virtually any video/audio format without extra codecs. Free, open-source, and lightweight.",
        "category": "Utilities",
        "url": "https://www.videolan.org/vlc/download-windows.html",
        "direct_url": "https://get.videolan.org/vlc/last/win64/",
        "color": "#ff8800",
        "icon": "🎬",
    },
    {
        "id": "dl_notepadpp",
        "name": "Notepad++",
        "desc": "Powerful text/code editor. Useful for editing game config files (.ini tweaks) and batch scripts.",
        "category": "Utilities",
        "url": "https://notepad-plus-plus.org/downloads/",
        "direct_url": "https://notepad-plus-plus.org/downloads/",
        "color": "#8bc34a",
        "icon": "📝",
    },
    {
        "id": "dl_winrar",
        "name": "WinRAR",
        "desc": "Popular archive manager with RAR support. Handles most compressed files including game mod archives.",
        "category": "Utilities",
        "url": "https://www.rarlab.com/download.htm",
        "direct_url": "https://www.rarlab.com/download.htm",
        "color": "#9c27b0",
        "icon": "🗜",
    },
    # ── Cleanup / Security ────────────────────────────────────────────────────
    {
        "id": "dl_malwarebytes",
        "name": "Malwarebytes (Free)",
        "desc": "On-demand malware scanner — run once after a fresh Windows install to ensure your system is clean. Free version sufficient for manual scans.",
        "category": "Security",
        "url": "https://www.malwarebytes.com/mwb-download/thankyou/",
        "direct_url": "https://www.malwarebytes.com/mwb-download/thankyou/",
        "color": "#00bcd4",
        "icon": "🛡",
    },
    {
        "id": "dl_windirstat",
        "name": "WinDirStat (Disk Usage Analyzer)",
        "desc": "Visual disk usage map — shows exactly what's eating your SSD storage. Useful for identifying large leftover game/temp files.",
        "category": "Security",
        "url": "https://windirstat.net/download.html",
        "direct_url": "https://windirstat.net/download.html",
        "color": "#ff7043",
        "icon": "📁",
    },
    {
        "id": "dl_autoruns",
        "name": "Autoruns (Microsoft Sysinternals)",
        "desc": "The most comprehensive startup program manager. Shows every autorun entry in Windows — disable unnecessary startup items to speed up boot.",
        "category": "Security",
        "url": "https://learn.microsoft.com/en-us/sysinternals/downloads/autoruns",
        "direct_url": "https://download.sysinternals.com/files/Autoruns.zip",
        "color": "#00838f",
        "icon": "⚙",
    },
    # ── Communication ─────────────────────────────────────────────────────────
    {
        "id": "dl_obs",
        "name": "OBS Studio",
        "desc": "Free and open-source software for video recording and live streaming. Essential for content creators — clips, streams, and screen recording.",
        "category": "Recording",
        "url": "https://obsproject.com/download",
        "direct_url": "https://obsproject.com/download",
        "color": "#302e31",
        "icon": "🎥",
    },
    {
        "id": "dl_sharex",
        "name": "ShareX",
        "desc": "Powerful free screenshot and screen recording tool with built-in annotation, GIF capture, and direct screenshot sharing.",
        "category": "Recording",
        "url": "https://getsharex.com/",
        "direct_url": "https://github.com/ShareX/ShareX/releases/latest",
        "color": "#1565c0",
        "icon": "📸",
    },
]

MISC_CATEGORIES = ["All", "Browser", "System Monitor", "GPU Tools", "Driver Tools", "Gaming", "Utilities", "Security", "Recording"]

VALORANT_TWEAKS = [
    # ── FPS & Graphics ────────────────────────────────────────────────────────
    {
        "id": "val_fps_cap_off",
        "name": "Unlock FPS Cap  (MaxFPS=0)",
        "desc": "Sets MaxFPS=0 and PerfMaxFPS=0 in GameUserSettings.ini — lets Valorant push your monitor's full refresh rate.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"MaxFPS=[\d.]+\",\"MaxFPS=0\"; '
                r'  $c = $c -replace \"PerfMaxFPS=[\d.]+\",\"PerfMaxFPS=0\"; '
                r'  $c = $c -replace \"FrameRateLimit=[\d.]+\",\"FrameRateLimit=0.000000\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"GameUserSettings.ini not found — launch Valorant once first\" }"'
            ),
            "Linux":  "echo 'Valorant is Windows only'",
            "Darwin": "echo 'Valorant is Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"MaxFPS=[\d.]+\",\"MaxFPS=240\"; '
                r'  $c = $c -replace \"PerfMaxFPS=[\d.]+\",\"PerfMaxFPS=240\"; '
                r'  $c | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_low_settings",
        "name": "Force Lowest Graphics Settings",
        "desc": "Sets all quality settings to 0 in GameUserSettings.ini — maximises FPS and reduces visual noise in fights.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"sg\.TextureQuality=\d\",\"sg.TextureQuality=0\"; '
                r'  $c = $c -replace \"sg\.ShadowQuality=\d\",\"sg.ShadowQuality=0\"; '
                r'  $c = $c -replace \"sg\.EffectsQuality=\d\",\"sg.EffectsQuality=0\"; '
                r'  $c = $c -replace \"sg\.PostProcessQuality=\d\",\"sg.PostProcessQuality=0\"; '
                r'  $c = $c -replace \"sg\.AntiAliasingQuality=\d\",\"sg.AntiAliasingQuality=0\"; '
                r'  $c = $c -replace \"sg\.FoliageQuality=\d\",\"sg.FoliageQuality=0\"; '
                r'  $c = $c -replace \"sg\.ViewDistanceQuality=\d\",\"sg.ViewDistanceQuality=0\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"Not found — launch Valorant first\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "val_vsync_off",
        "name": "Disable VSync  (bUseVSync=False)",
        "desc": "Kills VSync in Valorant config — eliminates the frame-sync input lag that hurts reaction time.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"bUseVSync=\w+\",\"bUseVSync=False\" | Set-Content $p; '
                r'  Write-Host Done '
                r'} else { Write-Host \"Not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"bUseVSync=\w+\",\"bUseVSync=True\" | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_fullscreen",
        "name": "Force Exclusive Fullscreen",
        "desc": "Sets FullscreenMode=1 in GameUserSettings.ini — exclusive fullscreen has the lowest input latency.",
        "category": "FPS",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"FullscreenMode=\d\",\"FullscreenMode=1\"; '
                r'  $c = $c -replace \"LastConfirmedFullscreenMode=\d\",\"LastConfirmedFullscreenMode=1\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"Not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  (Get-Content $p) -replace \"FullscreenMode=\d\",\"FullscreenMode=2\" | Set-Content $p }'
                r'"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_motion_blur_off",
        "name": "Disable Motion Blur + Bloom + Distortion",
        "desc": "Writes bMotionBlur=False, bBloom=False, bLensFlares=False to Scalability.ini — cleaner visuals, easier to track enemies.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$p = \"$env:LOCALAPPDATA\VALORANT\Saved\Config\Windows\GameUserSettings.ini\"; '
                r'if (Test-Path $p) { '
                r'  $c = Get-Content $p; '
                r'  $c = $c -replace \"bMotionBlur=\w+\",\"bMotionBlur=False\"; '
                r'  $c = $c -replace \"MotionBlurQuality=\d\",\"MotionBlurQuality=0\"; '
                r'  $c = $c -replace \"bBloom=\w+\",\"bBloom=False\"; '
                r'  $c = $c -replace \"bLensFlares=\w+\",\"bLensFlares=False\"; '
                r'  $c | Set-Content $p; Write-Host Done '
                r'} else { Write-Host \"Not found\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "val_disable_fullscreen_opt",
        "name": "Disable Fullscreen Optimizations (EXE flag)",
        "desc": "Sets DISABLEDXMAXIMIZEDWINDOWEDMODE on VALORANT-Win64-Shipping.exe — stops Windows secretly using borderless instead of true fullscreen.",
        "category": "FPS",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$exe = \"$env:LOCALAPPDATA\VALORANT\live\ShooterGame\Binaries\Win64\VALORANT-Win64-Shipping.exe\"; '
                r'$key = \"HKCU:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers\"; '
                r'if (Test-Path $exe) { '
                r'  if (-not (Test-Path $key)) { New-Item -Path $key -Force | Out-Null }; '
                r'  Set-ItemProperty -Path $key -Name $exe -Value \"DISABLEDXMAXIMIZEDWINDOWEDMODE\" '
                r'  -ErrorAction SilentlyContinue; Write-Host Done '
                r'} else { Write-Host \"VALORANT exe not found — install Valorant first\" }"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    # ── Network / Ping ────────────────────────────────────────────────────────
    {
        "id": "val_qos_priority",
        "name": "QoS Policy — Max Priority for Valorant",
        "desc": "Creates a Windows QoS rule giving VALORANT-Win64-Shipping.exe DSCP 46 (Expedited Forwarding) — highest possible network priority.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                'New-NetQosPolicy -Name ValorantQoS '
                '-AppPathNameMatchCondition \\"VALORANT-Win64-Shipping.exe\\" '
                '-IPProtocol Both -DSCPAction 46 -NetworkProfile All '
                '-ErrorAction SilentlyContinue; Write-Host Done"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
        "undo_cmd": {
            "Windows": (
                'powershell -Command "'
                'Remove-NetQosPolicy -Name ValorantQoS -Confirm:$false -ErrorAction SilentlyContinue"'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_tcp_nodelay",
        "name": "Zero-Delay TCP  (TcpNoDelay + TcpAckFrequency=1)",
        "desc": "Disables Nagle's algorithm system-wide so Valorant game packets are never buffered — direct impact on shot registration delay.",
        "category": "Network",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpNoDelay /t REG_DWORD /d 1 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpAckFrequency /t REG_DWORD /d 1 /f & '
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters" '
                '/v TcpNoDelay /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_nodelay=1",
            "Darwin": "sysctl -w net.inet.tcp.delayed_ack=0",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
                '/v TcpNoDelay /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_nodelay=0",
            "Darwin": "sysctl -w net.inet.tcp.delayed_ack=3",
        },
    },
    {
        "id": "val_bandwidth_reserve",
        "name": "Remove Windows 20% Bandwidth Reservation",
        "desc": "Frees the 20% of bandwidth Windows holds back for QoS — gives Valorant the full pipe on every shot.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Psched" '
                '/v NonBestEffortLimit /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    {
        "id": "val_fast_dns",
        "name": "Switch to Cloudflare DNS  (1.1.1.1)",
        "desc": "Sets DNS to 1.1.1.1 / 8.8.8.8 on all adapters — faster server lookups and matchmaking connections.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'netsh interface ip set dns "Ethernet" static 1.1.1.1 primary & '
                'netsh interface ip add dns "Ethernet" 8.8.8.8 index=2 & '
                'netsh interface ip set dns "Wi-Fi" static 1.1.1.1 primary & '
                'netsh interface ip add dns "Wi-Fi" 8.8.8.8 index=2 & '
                'ipconfig /flushdns'
            ),
            "Linux":  'echo "nameserver 1.1.1.1\nnameserver 8.8.8.8" | tee /etc/resolv.conf',
            "Darwin": "networksetup -setdnsservers Wi-Fi 1.1.1.1 8.8.8.8",
        },
        "undo_cmd": {
            "Windows": (
                'netsh interface ip set dns "Ethernet" dhcp & '
                'netsh interface ip set dns "Wi-Fi" dhcp'
            ),
            "Linux":  "echo '' > /etc/resolv.conf",
            "Darwin": "networksetup -setdnsservers Wi-Fi empty",
        },
    },
    {
        "id": "val_ping_servers",
        "name": "Ping Valorant Servers & Log Latency",
        "desc": "Pings Riot's matchmaking and game servers across regions — results logged to the Activity Log.",
        "category": "Network",
        "impact": "INFO",
        "cmd": {
            "Windows": (
                "ping -n 3 valorant.secure.dyn.riotgames.com & "
                "ping -n 3 na.depot.battle.net & "
                "ping -n 3 euw1.lol.riotgames.com"
            ),
            "Linux":  "ping -c 3 valorant.secure.dyn.riotgames.com",
            "Darwin": "ping -c 3 valorant.secure.dyn.riotgames.com",
        },
    },
    {
        "id": "val_disable_auto_tuning",
        "name": "Disable TCP Auto-Tuning Heuristics",
        "desc": "Turns off Windows heuristics that dynamically resize TCP windows — can cause jitter spikes during Valorant.",
        "category": "Network",
        "impact": "MED",
        "cmd": {
            "Windows": (
                "netsh int tcp set heuristics disabled & "
                "netsh int tcp set global autotuninglevel=highlyrestricted & "
                "netsh int tcp set global congestionprovider=ctcp"
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_window_scaling=0 2>/dev/null || true",
            "Darwin": "echo 'Managed by macOS'",
        },
        "undo_cmd": {
            "Windows": (
                "netsh int tcp set heuristics enabled & "
                "netsh int tcp set global autotuninglevel=normal"
            ),
            "Linux":  "sysctl -w net.ipv4.tcp_window_scaling=1 2>/dev/null || true",
            "Darwin": "echo 'N/A'",
        },
    },
    # ── CPU & Process ─────────────────────────────────────────────────────────
    {
        "id": "val_high_priority",
        "name": "Set Valorant Process to High CPU Priority",
        "desc": "Elevates VALORANT-Win64-Shipping.exe scheduling priority — CPU serves Valorant frames first.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'powershell -Command "'
                '$p = Get-Process -Name \\"VALORANT-Win64-Shipping\\" -ErrorAction SilentlyContinue; '
                'if ($p) { $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::High; '
                'Write-Host \\"Priority set to High\\" } '
                'else { Write-Host \\"Valorant not running — start the game first\\" }"'
            ),
            "Linux":  "echo 'Start Valorant first then reapply'",
            "Darwin": "echo 'macOS manages priority automatically'",
        },
    },
    {
        "id": "val_power_plan",
        "name": "Activate High Performance Power Plan",
        "desc": "Forces Windows into High Performance mode — CPU runs at maximum clock, no throttle during duels.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "Linux":   "cpupower frequency-set -g performance 2>/dev/null || true",
            "Darwin":  "echo 'macOS manages power automatically'",
        },
        "undo_cmd": {
            "Windows": "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e",
            "Linux":   "cpupower frequency-set -g powersave 2>/dev/null || true",
            "Darwin":  "echo 'N/A'",
        },
    },
    {
        "id": "val_game_mode",
        "name": "Enable Windows Game Mode",
        "desc": "Activates Game Mode — Windows dedicates more CPU and GPU resources to the active game.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 1 /f & '
                'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AllowAutoGameMode /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": 'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 0 /f',
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_disable_dvr",
        "name": "Disable Xbox Game Bar / DVR Capture",
        "desc": "Turns off screen recording overlay — reclaims CPU/GPU cycles that Game Bar steals in the background.",
        "category": "CPU",
        "impact": "HIGH",
        "cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\GameDVR" '
                '/v AllowGameDVR /t REG_DWORD /d 0 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": (
                'reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
                '/v AppCaptureEnabled /t REG_DWORD /d 1 /f'
            ),
            "Linux":  "echo 'N/A'",
            "Darwin": "echo 'N/A'",
        },
    },
    {
        "id": "val_system_responsiveness",
        "name": "Max System Responsiveness for Real-Time",
        "desc": "Sets SystemResponsiveness=0 — Windows gives real-time tasks (game render loop) maximum CPU time slice.",
        "category": "CPU",
        "impact": "MED",
        "cmd": {
            "Windows": (
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v SystemResponsiveness /t REG_DWORD /d 0 /f & '
                'reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
                '/v NetworkThrottlingIndex /t REG_DWORD /d 4294967295 /f'
            ),
            "Linux":  "echo 'N/A on Linux'",
            "Darwin": "echo 'N/A on macOS'",
        },
    },
    # ── Cleanup ───────────────────────────────────────────────────────────────
    {
        "id": "val_kill_background",
        "name": "Kill Background Apps Before Launch",
        "desc": "Closes Discord, OneDrive, Teams, Spotify, Chrome — frees RAM and prevents CPU contention during ranked.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                "taskkill /F /IM OneDrive.exe /T 2>nul & "
                "taskkill /F /IM Discord.exe /T 2>nul & "
                "taskkill /F /IM Teams.exe /T 2>nul & "
                "taskkill /F /IM Spotify.exe /T 2>nul & "
                "taskkill /F /IM chrome.exe /T 2>nul & "
                "taskkill /F /IM msedge.exe /T 2>nul & "
                "echo Background apps terminated"
            ),
            "Linux":  "killall discord spotify teams chromium 2>/dev/null || true",
            "Darwin": "killall Discord Spotify 'Microsoft Teams' 2>/dev/null || true",
        },
    },
    {
        "id": "val_clear_shader_cache",
        "name": "Clear Valorant Shader & Pipeline Cache",
        "desc": "Deletes Valorant's PipelineCaches and ShaderCache folders — eliminates compilation stutters after patches.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": (
                r'powershell -Command "'
                r'$paths = @('
                r'  \"$env:LOCALAPPDATA\VALORANT\Saved\PipelineCaches\", '
                r'  \"$env:LOCALAPPDATA\VALORANT\Saved\ShaderCache\", '
                r'  \"$env:LOCALAPPDATA\D3DSCache\" '
                r'); foreach ($p in $paths) { '
                r'  if (Test-Path $p) { Remove-Item \"$p\*\" -Recurse -Force -ErrorAction SilentlyContinue; '
                r'  Write-Host \"Cleared: $p\" } '
                r'}"'
            ),
            "Linux":  "echo 'Windows only'",
            "Darwin": "echo 'Windows only'",
        },
    },
    {
        "id": "val_flush_memory",
        "name": "Flush Standby RAM",
        "desc": "Forces .NET GC to collect and clears standby memory — gives Valorant more free RAM on launch.",
        "category": "Cleanup",
        "impact": "LOW",
        "cmd": {
            "Windows": (
                'powershell -Command "[System.GC]::Collect(); '
                '[System.GC]::WaitForPendingFinalizers(); '
                'Write-Host \\"Standby memory flushed\\""'
            ),
            "Linux":  "sync && echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true",
            "Darwin": "purge 2>/dev/null || true",
        },
    },
    {
        "id": "val_temp_clean",
        "name": "Wipe Windows Temp Folder",
        "desc": "Removes all files from %TEMP% — prevents slow disk I/O from temp file clutter during Valorant.",
        "category": "Cleanup",
        "impact": "LOW",
        "cmd": {
            "Windows": 'cmd /c "del /f /s /q %TEMP%\\* 2>nul & rd /s /q %TEMP% 2>nul & md %TEMP% 2>nul & echo Done"',
            "Linux":   "rm -rf /tmp/* 2>/dev/null || true",
            "Darwin":  "rm -rf /private/tmp/* 2>/dev/null || true",
        },
    },
    {
        "id": "val_pause_windows_update",
        "name": "Pause Windows Update During Session",
        "desc": "Stops wuauserv service so Windows Update downloads can't steal bandwidth or cause CPU spikes mid-match.",
        "category": "Cleanup",
        "impact": "MED",
        "cmd": {
            "Windows": "sc stop wuauserv & sc config wuauserv start= disabled",
            "Linux":   "echo 'N/A on Linux'",
            "Darwin":  "echo 'N/A on macOS'",
        },
        "undo_cmd": {
            "Windows": "sc config wuauserv start= auto & sc start wuauserv",
            "Linux":   "echo 'N/A'",
            "Darwin":  "echo 'N/A'",
        },
    },
]

VAL_CATEGORIES = ["All", "FPS", "Network", "CPU", "Cleanup"]

# ─────────────────────────────────────────────────────────────────────────────
# Color theme
# ─────────────────────────────────────────────────────────────────────────────
BG     = "#070a0f"
BG2    = "#0b1018"
BG3    = "#10171f"
PANEL  = "#131b24"
BORDER = "#1c2b3a"
ACCENT = "#00d4ff"
ACCENT2= "#7b2fff"
GREEN  = "#00e5a0"
YELLOW = "#ffd740"
RED    = "#ff4060"
ORANGE = "#ff8c42"
TEXT   = "#dde8f2"
TEXT2  = "#607a92"
TEXT3  = "#354d62"

# Beta badge
BETA_COL = "#ff8c00"

def ping_color(ms):
    if ms is None: return RED
    if ms < 30:    return GREEN
    if ms < 80:    return YELLOW
    return RED

# ─────────────────────────────────────────────────────────────────────────────
# Main application
# ─────────────────────────────────────────────────────────────────────────────
class PingOptimizerApp:
    def __init__(self):
        # ── Splash / loading screen ─────────────────────────────────────────
        self._show_splash()

    def _show_splash(self):
        """Animated loading screen shown while the app initialises."""
        splash = tk.Tk()
        splash.overrideredirect(True)
        splash.configure(bg=BG)
        sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
        W, H = 560, 340
        splash.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")

        # Outer glow border via nested frames
        outer = tk.Frame(splash, bg=ACCENT, padx=1, pady=1)
        outer.pack(fill="both", expand=True)
        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Top accent line inside splash
        top_line = tk.Canvas(inner, height=3, bg=BG, highlightthickness=0, bd=0)
        top_line.pack(fill="x")

        tk.Label(inner, text="BANZ", font=("Consolas", 52, "bold"),
                 fg=ACCENT, bg=BG).pack(pady=(28, 0))
        tk.Label(inner, text="O P T I M I Z A T I O N",
                 font=("Consolas", 11, "bold"), fg=ACCENT2,
                 bg=BG).pack()

        # Beta badge row
        badge_row = tk.Frame(inner, bg=BG)
        badge_row.pack(pady=(6, 0))
        tk.Label(badge_row, text=" Beta v1 ",
                 font=("Consolas", 8, "bold"), fg=BG, bg=BETA_COL,
                 padx=6, pady=2).pack(side="left")
        tk.Label(badge_row, text="  NETWORK  •  SYSTEM  •  GAMING  •  BIOS",
                 font=("Consolas", 8), fg=TEXT3, bg=BG).pack(side="left")

        # Progress bar canvas
        pb_canvas = tk.Canvas(inner, width=440, height=3,
                              bg=BG3, highlightthickness=0, bd=0)
        pb_canvas.pack(pady=(22, 6))
        pb_rect = pb_canvas.create_rectangle(0, 0, 0, 3, fill=ACCENT, outline="")

        status_lbl = tk.Label(inner, text="Initialising…",
                              font=("Consolas", 8), fg=TEXT3, bg=BG)
        status_lbl.pack()

        steps = [
            (0.15,  "Loading network drivers…"),
            (0.32,  "Scanning system profile…"),
            (0.50,  "Building optimisation matrix…"),
            (0.68,  "Calibrating ping engine…"),
            (0.85,  "Preparing debloat modules…"),
            (1.00,  "Ready."),
        ]
        step_idx = [0]

        def _tick():
            if step_idx[0] >= len(steps):
                splash.destroy()
                self._init_app()
                return
            frac, msg = steps[step_idx[0]]
            pb_canvas.coords(pb_rect, 0, 0, int(420 * frac), 4)
            status_lbl.config(text=msg)
            step_idx[0] += 1
            splash.after(340, _tick)

        splash.after(200, _tick)
        splash.mainloop()

    def _init_app(self):
        """Build the main application window after splash."""
        self.root = tk.Tk()
        self.root.title("BANZ OPTIMIZATION  Beta v1")
        self.root.geometry("1160x780")
        self.root.minsize(980, 680)
        self.root.configure(bg=BG)
        self.root.resizable(True, True)

        if OS == "Windows":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                pass

        self.running        = False
        self.ping_thread    = None
        self.pings          = collections.deque(maxlen=60)
        self.ping_results   = collections.deque(maxlen=60)  # includes None for timeouts
        self.applied        = set()
        self.target_host    = tk.StringVar(value="8.8.8.8")
        self.target_name    = tk.StringVar(value="Google DNS")
        self.target_port    = 53
        self._alive         = True
        self._last_spike_log = 0  # throttle spike log messages
        self._category      = tk.StringVar(value="All")
        self._fn_category   = tk.StringVar(value="All")
        self._val_category  = tk.StringVar(value="All")
        self._r6_category   = tk.StringVar(value="All")
        self._misc_category = tk.StringVar(value="All")
        self.tweak_rows     = {}
        self.fn_tweak_rows  = {}
        self.val_tweak_rows = {}
        self.r6_tweak_rows  = {}

        self._style_ttk()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_loop()

        # Load adapter info in background
        threading.Thread(target=self._refresh_adapter_info, daemon=True).start()
        self.run()
        self.root.mainloop()

    # ── TTK styling ───────────────────────────────────────────────────────────
    def _style_ttk(self):
        style = ttk.Style()
        try:
            style.theme_use("default")
        except Exception:
            pass
        for widget in ("TCombobox",):
            style.configure(widget,
                            fieldbackground=BG3, background=BG3,
                            foreground=TEXT, selectbackground=BG3,
                            selectforeground=ACCENT, bordercolor=BORDER,
                            arrowcolor=ACCENT, relief="flat")
            style.map(widget,
                      fieldbackground=[("readonly", BG3)],
                      foreground=[("readonly", TEXT)],
                      background=[("readonly", BG3)])
        # Notebook — compact, clean pill tabs
        style.configure("Dark.TNotebook", background=BG2, borderwidth=0,
                        tabmargins=[0, 0, 0, 0])
        style.configure("Dark.TNotebook.Tab",
                        background=BG2, foreground=TEXT3,
                        font=("Consolas", 8, "bold"),
                        padding=[12, 7], borderwidth=0, relief="flat")
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", BG3), ("active", BG2)],
                  foreground=[("selected", ACCENT), ("active", TEXT2)])

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Premium title bar ─────────────────────────────────────────────────
        title_bar = tk.Frame(self.root, bg=BG2, height=52)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)

        # Left: logo + beta badge
        logo_frame = tk.Frame(title_bar, bg=BG2)
        logo_frame.pack(side="left", padx=16, pady=10)
        tk.Label(logo_frame, text="BANZ",
                 font=("Consolas", 17, "bold"),
                 fg=ACCENT, bg=BG2).pack(side="left")
        tk.Label(logo_frame, text=" OPTIMIZATION",
                 font=("Consolas", 10, "bold"),
                 fg=ACCENT2, bg=BG2).pack(side="left", pady=2)
        # Beta badge
        tk.Label(logo_frame, text=" Beta v1 ",
                 font=("Consolas", 7, "bold"),
                 fg=BG, bg=BETA_COL, padx=4, pady=1).pack(side="left", padx=(8, 0), pady=2)

        # Right: status + OS info
        right_frame = tk.Frame(title_bar, bg=BG2)
        right_frame.pack(side="right", padx=16)
        tk.Label(right_frame,
                 text=f"{OS}  •  Python {sys.version.split()[0]}",
                 font=("Consolas", 8), fg=TEXT3, bg=BG2).pack(side="right")
        self.status_dot = tk.Label(right_frame, text="⬤  IDLE",
                                   font=("Consolas", 9, "bold"),
                                   fg=TEXT3, bg=BG2)
        self.status_dot.pack(side="right", padx=12)

        # Thin neon accent line under title bar
        accent_bar = tk.Canvas(self.root, height=2, bg=BG2,
                               highlightthickness=0, bd=0)
        accent_bar.pack(fill="x")
        accent_bar.bind("<Configure>", lambda e: self._draw_accent_bar(accent_bar))
        self._accent_bar_canvas = accent_bar

        # Notebook tabs
        self.notebook = ttk.Notebook(self.root, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=0, pady=0)

        # Tab 1: Monitor
        self.tab_monitor = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_monitor, text=" 📊 Monitor ")

        # Tab 2: Tweaks
        self.tab_tweaks = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_tweaks, text=" 🔧 Tweaks ")

        # Tab 3: Adapter Info
        self.tab_adapter = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_adapter, text=" 🔌 Adapter ")

        # Tab 4: Network Reset
        self.tab_netreset = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_netreset, text=" 🔄 Net Reset ")

        # Tab 5: Debloat
        self.tab_debloat = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_debloat, text=" 🧹 Debloat ")

        # Tab 6: Fortnite
        self.tab_fortnite = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_fortnite, text=" 🎮 Fortnite ")

        # Tab 7: Valorant
        self.tab_valorant = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_valorant, text=" 🔫 Valorant ")

        # Tab 8: Rainbow Six Siege
        self.tab_r6 = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_r6, text=" 🚨 R6 Siege ")

        # Tab 9: Mouse & Keyboard Tweaks
        self.tab_mkb = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_mkb, text=" 🖱 MKB ")

        # Tab 10: Revert All Tweaks
        self.tab_revert = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_revert, text=" ↩ Revert ")

        # Tab 11: BIOS Tweaks
        self.tab_bios = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_bios, text=" ⚙ BIOS ")

        # Tab 12: Miscellaneous Downloads
        self.tab_misc = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(self.tab_misc, text=" ⬇ Misc ")

        self._build_monitor_tab(self.tab_monitor)
        self._build_tweaks_tab(self.tab_tweaks)
        self._build_adapter_tab(self.tab_adapter)
        self._build_netreset_tab(self.tab_netreset)
        self._build_debloat_tab(self.tab_debloat)
        self._build_fortnite_tab(self.tab_fortnite)
        self._build_valorant_tab(self.tab_valorant)
        self._build_r6_tab(self.tab_r6)
        self._build_mkb_tab(self.tab_mkb)
        self._build_revert_tab(self.tab_revert)
        self._build_bios_tab(self.tab_bios)
        self._build_misc_tab(self.tab_misc)

        # Bottom bar
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x")
        bottom = tk.Frame(self.root, bg=BG2, height=54)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)
        self._build_bottom_bar(bottom)

    def _draw_accent_bar(self, canvas):
        """Draw a two-colour gradient accent line."""
        w = canvas.winfo_width()
        if w < 2: return
        canvas.delete("all")
        steps = max(w, 1)
        for i in range(steps):
            t = i / steps
            r = int(0x00 + t * (0x7b - 0x00))
            g = int(0xd4 + t * (0x2f - 0xd4))
            b = int(0xff + t * (0xff - 0xff))
            col = f"#{r:02x}{g:02x}{b:02x}"
            canvas.create_line(i, 0, i, 2, fill=col)

    # ── Panel helper ──────────────────────────────────────────────────────────
    def _panel(self, parent, title, expandable=False):
        outer = tk.Frame(parent, bg=BORDER)
        if expandable:
            outer.pack(fill="both", expand=True, pady=(0, 8))
        else:
            outer.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        hdr = tk.Frame(inner, bg=BG3)
        hdr.pack(fill="x")
        # Left accent bar
        tk.Frame(hdr, bg=ACCENT, width=3).pack(side="left", fill="y")
        tk.Label(hdr, text=f"  {title}",
                 font=("Consolas", 9, "bold"),
                 fg=ACCENT, bg=BG3, pady=8).pack(side="left")
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")
        body = tk.Frame(inner, bg=PANEL, padx=12, pady=10)
        body.pack(fill="both", expand=True)
        return body, hdr

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 1: Monitor
    # ─────────────────────────────────────────────────────────────────────────
    def _build_monitor_tab(self, parent):
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))

        right = tk.Frame(body, bg=BG)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        self._build_stats_panel(left)
        self._build_graph_panel(left)
        self._build_server_panel(left)
        self._build_log_panel(right)

    def _build_stats_panel(self, parent):
        body, _ = self._panel(parent, "LIVE STATS")
        grid = tk.Frame(body, bg=PANEL)
        grid.pack(fill="x")
        self.stat_widgets = {}
        for label, key, row, col in [
            ("CURRENT",  "cur",  0, 0),
            ("AVERAGE",  "avg",  0, 1),
            ("JITTER",   "jit",  1, 0),
            ("PKT LOSS", "loss", 1, 1),
        ]:
            cell = tk.Frame(grid, bg=BG3, padx=12, pady=10)
            cell.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            grid.columnconfigure(col, weight=1)
            tk.Label(cell, text=label, font=("Consolas", 8), fg=TEXT3, bg=BG3).pack()
            val = tk.Label(cell, text="—", font=("Consolas", 22, "bold"), fg=TEXT2, bg=BG3)
            val.pack()
            unit = tk.Label(cell, text="ms", font=("Consolas", 8), fg=TEXT3, bg=BG3)
            unit.pack()
            self.stat_widgets[key] = val
            self.stat_widgets[key + "_unit"] = unit

    def _build_graph_panel(self, parent):
        body, _ = self._panel(parent, "PING GRAPH  (last 60 samples)")
        self.canvas = tk.Canvas(body, height=120, bg=BG3, highlightthickness=0, bd=0)
        self.canvas.pack(fill="x", expand=False)
        self.canvas.bind("<Configure>", lambda e: self._draw_graph())
        axis = tk.Frame(body, bg=PANEL)
        axis.pack(fill="x", pady=(4, 0))
        for label, col in [("<30ms  GREAT", GREEN), ("30-80ms  OK", YELLOW), (">80ms  HIGH", RED)]:
            tk.Label(axis, text=label, font=("Consolas", 7), fg=col, bg=PANEL).pack(side="left", expand=True)

    def _build_server_panel(self, parent):
        body, _ = self._panel(parent, "TARGET SERVER")
        row = tk.Frame(body, bg=PANEL)
        row.pack(fill="x")
        tk.Label(row, text="Server:", font=("Consolas", 9), fg=TEXT2, bg=PANEL).pack(side="left")
        self.server_combo = ttk.Combobox(row, values=[s["name"] for s in SERVERS],
                                          state="readonly", width=28, font=("Consolas", 9))
        self.server_combo.set("Google DNS")
        self.server_combo.pack(side="left", padx=(8, 0))
        self.server_combo.bind("<<ComboboxSelected>>", self._on_server_change)
        self.ping_ms_lbl = tk.Label(body, text="  Select a server and start the monitor",
                                    font=("Consolas", 9), fg=TEXT3, bg=PANEL)
        self.ping_ms_lbl.pack(anchor="w", pady=(8, 0))

    def _build_log_panel(self, parent):
        body, _ = self._panel(parent, "ACTIVITY LOG", expandable=True)
        self.log_text = tk.Text(body, bg=BG3, fg=TEXT2, font=("Consolas", 8),
                                relief="flat", state="disabled", cursor="arrow",
                                wrap="word", bd=0, selectbackground=BG3)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.tag_config("ok",   foreground=GREEN)
        self.log_text.tag_config("warn", foreground=YELLOW)
        self.log_text.tag_config("err",  foreground=RED)
        self.log_text.tag_config("info", foreground=TEXT2)
        self.log_text.tag_config("ts",   foreground=TEXT3)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 2: Tweaks
    # ─────────────────────────────────────────────────────────────────────────
    def _build_tweaks_tab(self, parent):
        # Header row with category filter + Apply All
        hdr = tk.Frame(parent, bg=BG2)
        hdr.pack(fill="x", padx=0, pady=0)
        tk.Frame(hdr, bg=BORDER, height=1).pack(fill="x", side="bottom")

        tk.Label(hdr, text="  FILTER:", font=("Consolas", 8), fg=TEXT2, bg=BG2).pack(side="left", padx=(12,4), pady=8)
        self._cat_btns = {}
        for cat in CATEGORIES:
            btn = tk.Button(hdr, text=cat,
                            font=("Consolas", 8, "bold"),
                            fg=ACCENT if cat == "All" else TEXT2,
                            bg=BG3 if cat == "All" else BG2,
                            relief="flat", cursor="hand2", padx=10, pady=4,
                            command=lambda c=cat: self._filter_tweaks(c))
            btn.pack(side="left", padx=2, pady=6)
            self._cat_btns[cat] = btn

        tk.Button(hdr, text="⚡ APPLY ALL VISIBLE",
                  font=("Consolas", 8, "bold"),
                  fg=BG, bg=ACCENT, relief="flat",
                  cursor="hand2", padx=12, pady=4,
                  command=self._apply_all_tweaks).pack(side="right", padx=12, pady=6)

        # Scrollable tweak list
        container = tk.Frame(parent, bg=BG)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        self.tweak_canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=self.tweak_canvas.yview)
        self.tweak_scroll_frame = tk.Frame(self.tweak_canvas, bg=BG)

        self.tweak_scroll_frame.bind("<Configure>",
            lambda e: self.tweak_canvas.configure(
                scrollregion=self.tweak_canvas.bbox("all")))

        self.tweak_canvas.create_window((0, 0), window=self.tweak_scroll_frame, anchor="nw")
        self.tweak_canvas.configure(yscrollcommand=scrollbar.set)

        self.tweak_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel scroll
        self.tweak_canvas.bind("<MouseWheel>",
            lambda e: self.tweak_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_tweak_rows()

    def _build_tweak_rows(self):
        """Build all tweak rows inside the scrollable frame."""
        IMPACT_COLORS = {"HIGH": GREEN, "MED": YELLOW, "LOW": ACCENT}
        CAT_COLORS    = {"DNS": "#00bcd4", "TCP": "#7c4dff",
                         "Ethernet": "#ff9800", "System": "#f48fb1"}

        for widget in self.tweak_scroll_frame.winfo_children():
            widget.destroy()
        self.tweak_rows = {}

        active_cat = self._category.get()
        visible = [t for t in TWEAKS
                   if active_cat == "All" or t.get("category") == active_cat]

        for t in visible:
            outer = tk.Frame(self.tweak_scroll_frame, bg=BORDER)
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=PANEL)
            row_frame.pack(fill="x", padx=1, pady=1)

            # Left: impact badge + category badge + name + desc
            info = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            badges = tk.Frame(info, bg=PANEL)
            badges.pack(fill="x")

            icol = IMPACT_COLORS.get(t.get("impact", "MED"), YELLOW)
            tk.Label(badges, text=f"[{t.get('impact','MED')}]",
                     font=("Consolas", 7, "bold"), fg=icol, bg=PANEL, width=6).pack(side="left")

            cat_col = CAT_COLORS.get(t.get("category", ""), TEXT3)
            tk.Label(badges, text=f"[{t.get('category','')}]",
                     font=("Consolas", 7, "bold"), fg=cat_col, bg=PANEL).pack(side="left", padx=(2,6))

            tk.Label(badges, text=t["name"], font=("Consolas", 9, "bold"),
                     fg=TEXT, bg=PANEL, anchor="w").pack(side="left")

            tk.Label(info, text=t["desc"], font=("Consolas", 8),
                     fg=TEXT3, bg=PANEL, anchor="w").pack(fill="x", padx=(0, 0))

            # Right: status + apply + undo buttons
            controls = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○", font=("Consolas", 12), fg=TEXT3, bg=PANEL)
            status_lbl.pack(side="left", padx=(0, 6))

            if t.get("undo_cmd") and t["undo_cmd"].get(OS, ""):
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg=YELLOW,
                                     bg=BG3, relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda tid=t["id"]: self._undo_tweak(tid))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8), fg=ACCENT,
                                  bg=BG3, relief="flat", cursor="hand2",
                                  padx=8, pady=2,
                                  command=lambda tid=t["id"]: self._apply_tweak(tid))
            apply_btn.pack(side="left")

            self.tweak_rows[t["id"]] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn
            }
            # Restore applied state
            if t["id"] in self.applied:
                status_lbl.config(text="✓", fg=GREEN)
                apply_btn.config(text="Done", fg=GREEN, state="disabled")

    def _filter_tweaks(self, category):
        self._category.set(category)
        for cat, btn in self._cat_btns.items():
            if cat == category:
                btn.config(fg=ACCENT, bg=BG3)
            else:
                btn.config(fg=TEXT2, bg=BG2)
        self._build_tweak_rows()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 3: Adapter Info
    # ─────────────────────────────────────────────────────────────────────────
    def _build_adapter_tab(self, parent):
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=12)

        # Top info row
        top, _ = self._panel(body, "CONNECTION OVERVIEW")
        self.conn_labels = {}
        fields = [
            ("Connection Type", "type"),
            ("Local IP Address", "ip"),
            ("Active Adapter",   "adapter"),
        ]
        for label, key in fields:
            row = tk.Frame(top, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=f"{label}:", font=("Consolas", 9),
                     fg=TEXT2, bg=PANEL, width=20, anchor="w").pack(side="left")
            val = tk.Label(row, text="Loading…", font=("Consolas", 9, "bold"),
                           fg=ACCENT, bg=PANEL, anchor="w")
            val.pack(side="left")
            self.conn_labels[key] = val

        tk.Button(top, text="⟳  Refresh",
                  font=("Consolas", 8), fg=ACCENT, bg=BG3,
                  relief="flat", cursor="hand2", padx=10, pady=2,
                  command=lambda: threading.Thread(
                      target=self._refresh_adapter_info, daemon=True).start()
                  ).pack(anchor="e", pady=(6, 0))

        # Adapter list
        list_panel, _ = self._panel(body, "ALL NETWORK ADAPTERS")
        self.adapter_text = tk.Text(list_panel, bg=BG3, fg=TEXT2,
                                    font=("Consolas", 8), relief="flat",
                                    state="disabled", cursor="arrow",
                                    height=10, wrap="word", bd=0)
        self.adapter_text.pack(fill="both", expand=True)
        self.adapter_text.tag_config("connected", foreground=GREEN)
        self.adapter_text.tag_config("disconnected", foreground=TEXT3)
        self.adapter_text.tag_config("header", foreground=ACCENT)

        # Quick ethernet commands
        eth_panel, _ = self._panel(body, "ETHERNET DIAGNOSTICS")
        btn_row = tk.Frame(eth_panel, bg=PANEL)
        btn_row.pack(fill="x")
        diag_cmds = [
            ("Show IP Config",    "ipconfig /all" if OS=="Windows" else "ip addr"),
            ("Show Routing",      "route print" if OS=="Windows" else "ip route"),
            ("Traceroute 8.8.8.8","tracert -h 10 8.8.8.8" if OS=="Windows" else "traceroute -m 10 8.8.8.8"),
            ("Netstat Summary",   "netstat -e" if OS=="Windows" else "netstat -s"),
        ]
        for label, cmd in diag_cmds:
            tk.Button(btn_row, text=label,
                      font=("Consolas", 8), fg=ACCENT, bg=BG3,
                      relief="flat", cursor="hand2", padx=10, pady=4,
                      command=lambda c=cmd, l=label: self._run_diag(l, c)
                      ).pack(side="left", padx=(0, 6), pady=2)

        self.diag_text = tk.Text(eth_panel, bg=BG3, fg=TEXT2,
                                  font=("Consolas", 8), relief="flat",
                                  state="disabled", height=8, wrap="none", bd=0)
        self.diag_text.pack(fill="both", expand=True, pady=(8, 0))
        # Horizontal scrollbar for diag output
        h_scroll = tk.Scrollbar(eth_panel, orient="horizontal", command=self.diag_text.xview)
        h_scroll.pack(fill="x")
        self.diag_text.config(xscrollcommand=h_scroll.set)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 4: Network Reset
    # ─────────────────────────────────────────────────────────────────────────
    def _build_netreset_tab(self, parent):
        NR_ACCENT = "#00d4ff"
        NR_WARN   = "#ffe156"
        NR_RED    = "#ff3c5f"
        NR_GREEN  = "#00ff9d"

        # Banner
        banner = tk.Frame(parent, bg=BG2, height=68)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=NR_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="🔄  NETWORK RESET",
                 font=("Consolas", 16, "bold"),
                 fg=NR_ACCENT, bg=BG2).pack(side="left", padx=18, pady=16)
        tk.Label(banner, text="Flush  •  Repair  •  Rebuild  •  Reconnect",
                 font=("Consolas", 9), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        left  = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        # ── Quick Reset Actions ───────────────────────────────────────────────
        qr_body, _ = self._panel(left, "QUICK RESET ACTIONS")

        NET_RESET_ACTIONS = [
            ("🧹  Flush DNS Cache",
             "ipconfig /flushdns" if OS == "Windows" else
             "systemd-resolve --flush-caches 2>/dev/null || resolvectl flush-caches 2>/dev/null || true",
             NR_ACCENT,
             "Clears all cached DNS entries. Fixes 'site not loading' issues."),

            ("🔄  Reset TCP/IP Stack",
             "netsh int ip reset resetlog.txt & netsh int ipv6 reset" if OS == "Windows" else
             "ip addr flush dev $(ip route | awk '/default/{print $5}') 2>/dev/null || true",
             NR_WARN,
             "Rebuilds the TCP/IP stack from scratch. Fixes corrupt network state."),

            ("🔄  Reset Winsock Catalog",
             "netsh winsock reset" if OS == "Windows" else "echo 'N/A on Linux'",
             NR_WARN,
             "Resets Windows Sockets. Fixes apps that can't connect to internet."),

            ("🌐  Release & Renew IP",
             "ipconfig /release & ipconfig /renew" if OS == "Windows" else
             "dhclient -r 2>/dev/null; dhclient 2>/dev/null || true",
             NR_ACCENT,
             "Drops your DHCP lease and requests a fresh IP address."),

            ("📡  Reset Wi-Fi Adapter",
             'powershell -Command "Get-NetAdapter | Where-Object {$_.Name -like \'*Wi*\'} | Restart-NetAdapter -Confirm:$false"'
             if OS == "Windows" else "ip link set wlan0 down && ip link set wlan0 up 2>/dev/null || true",
             NR_ACCENT,
             "Disables and re-enables the Wi-Fi adapter to clear connection issues."),

            ("🔌  Reset Ethernet Adapter",
             'powershell -Command "Get-NetAdapter | Where-Object {$_.Name -like \'*Ethernet*\' -or $_.Name -like \'*LAN*\'} | Restart-NetAdapter -Confirm:$false"'
             if OS == "Windows" else "ip link set eth0 down && ip link set eth0 up 2>/dev/null || true",
             NR_ACCENT,
             "Disables and re-enables the Ethernet adapter."),

            ("🛡️  Reset Windows Firewall",
             "netsh advfirewall reset" if OS == "Windows" else
             "iptables -F 2>/dev/null || true",
             NR_RED,
             "Resets Windows Firewall rules to default. Use if firewall is blocking connections."),

            ("📋  Flush ARP Cache",
             "arp -d *" if OS == "Windows" else "ip neigh flush all 2>/dev/null || true",
             NR_ACCENT,
             "Clears the ARP table. Fixes LAN connectivity and IP conflicts."),

            ("⚡  FULL NETWORK RESET",
             ("netsh int ip reset & netsh int ipv6 reset & netsh winsock reset & "
              "ipconfig /flushdns & ipconfig /release & ipconfig /renew")
             if OS == "Windows" else
             ("ip addr flush dev $(ip route | awk '/default/{print $5}') 2>/dev/null; "
              "systemd-resolve --flush-caches 2>/dev/null || true"),
             NR_RED,
             "⚠  Runs ALL resets above in sequence. A restart may be required after."),
        ]

        for label, cmd, col, desc in NET_RESET_ACTIONS:
            row = tk.Frame(qr_body, bg=PANEL)
            row.pack(fill="x", pady=3)

            # Accent dot
            tk.Label(row, text="◆", font=("Consolas", 8),
                     fg=col, bg=PANEL).pack(side="left", padx=(0, 6))

            info_f = tk.Frame(row, bg=PANEL)
            info_f.pack(side="left", fill="x", expand=True)
            tk.Label(info_f, text=label, font=("Consolas", 9, "bold"),
                     fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(info_f, text=desc, font=("Consolas", 7),
                     fg=TEXT3, bg=PANEL, anchor="w").pack(fill="x")

            tk.Button(row, text="Run",
                      font=("Consolas", 8, "bold"),
                      fg=BG, bg=col, relief="flat", cursor="hand2",
                      padx=10, pady=3,
                      command=lambda c=cmd, l=label: self._netreset_run(l, c)
                      ).pack(side="right", padx=6, pady=4)

        # ── Output log ────────────────────────────────────────────────────────
        log_body, _ = self._panel(right, "RESET OUTPUT LOG", expandable=True)
        self.netreset_log = tk.Text(log_body, bg=BG3, fg=TEXT2,
                                    font=("Consolas", 8), relief="flat",
                                    state="disabled", cursor="arrow",
                                    wrap="word", bd=0)
        self.netreset_log.pack(fill="both", expand=True)
        self.netreset_log.tag_config("ok",   foreground=NR_GREEN)
        self.netreset_log.tag_config("warn", foreground=NR_WARN)
        self.netreset_log.tag_config("err",  foreground=NR_RED)
        self.netreset_log.tag_config("info", foreground=TEXT2)
        self.netreset_log.tag_config("ts",   foreground=TEXT3)

        # Note about restart
        note_body, _ = self._panel(right, "ℹ  NOTE")
        tk.Label(note_body,
                 text=("Some resets (TCP/IP stack, Winsock) require a system restart\n"
                       "to take full effect. Always save your work first."),
                 font=("Consolas", 8), fg=YELLOW, bg=PANEL,
                 justify="left").pack(anchor="w")

    def _netreset_run(self, label, cmd):
        ts = datetime.now().strftime("%H:%M:%S")
        def _insert(msg, tag):
            try:
                self.netreset_log.config(state="normal")
                self.netreset_log.insert("end", f"[{ts}] ", "ts")
                self.netreset_log.insert("end", msg + "\n", tag)
                self.netreset_log.see("end")
                self.netreset_log.config(state="disabled")
            except tk.TclError: pass

        def _run():
            self.root.after(0, lambda: _insert(f"Running: {label}…", "info"))
            ok, out, err = run_cmd(cmd, timeout=30)
            result = (out or err or "Done")[:200]
            tag = "ok" if ok else "err"
            self.root.after(0, lambda: _insert(f"{'✓' if ok else '✗'} {result}", tag))
            self._log(f"[Net Reset] {'✓' if ok else '✗'} {label}: {result[:80]}", "ok" if ok else "err")

        threading.Thread(target=_run, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 5: Windows Debloat
    # ─────────────────────────────────────────────────────────────────────────
    def _build_debloat_tab(self, parent):
        DB_ACCENT = "#7b2fff"
        DB_GREEN  = "#00ff9d"
        DB_YELLOW = "#ffe156"
        DB_RED    = "#ff3c5f"

        # Banner
        banner = tk.Frame(parent, bg=BG2, height=68)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=DB_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="🧹  WINDOWS DEBLOAT",
                 font=("Consolas", 16, "bold"),
                 fg=DB_ACCENT, bg=BG2).pack(side="left", padx=18, pady=16)
        tk.Label(banner, text="Remove Junk  •  Free RAM  •  Speed Up Boot  •  Kill Telemetry",
                 font=("Consolas", 9), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Button(banner, text="⚡ RUN ALL DEBLOAT",
                  font=("Consolas", 9, "bold"),
                  fg="#fff", bg=DB_ACCENT, relief="flat",
                  cursor="hand2", padx=14, pady=6,
                  command=self._debloat_run_all).pack(side="right", padx=16, pady=14)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # Category filter bar
        fbar = tk.Frame(parent, bg=BG2)
        fbar.pack(fill="x")
        tk.Frame(fbar, bg=BORDER, height=1).pack(fill="x", side="bottom")
        tk.Label(fbar, text="  FILTER:", font=("Consolas", 8),
                 fg=TEXT2, bg=BG2).pack(side="left", padx=(12, 4), pady=7)

        DB_CATS = ["All", "Apps", "Services", "Privacy", "Telemetry", "Startup", "Junk Files"]
        self._db_cat_btns = {}
        self._db_category = tk.StringVar(value="All")
        for cat in DB_CATS:
            is_sel = (cat == "All")
            btn = tk.Button(fbar, text=cat,
                            font=("Consolas", 8, "bold"),
                            fg=DB_ACCENT if is_sel else TEXT2,
                            bg=BG3 if is_sel else BG2,
                            relief="flat", cursor="hand2", padx=10, pady=3,
                            command=lambda c=cat: self._db_filter(c))
            btn.pack(side="left", padx=2, pady=5)
            self._db_cat_btns[cat] = btn

        # Scrollable list
        container = tk.Frame(parent, bg=BG)
        container.pack(fill="both", expand=True, padx=14, pady=8)

        self.db_canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        db_scroll = tk.Scrollbar(container, orient="vertical", command=self.db_canvas.yview)
        self.db_scroll_frame = tk.Frame(self.db_canvas, bg=BG)
        self.db_scroll_frame.bind("<Configure>",
            lambda e: self.db_canvas.configure(
                scrollregion=self.db_canvas.bbox("all")))
        self.db_canvas.create_window((0, 0), window=self.db_scroll_frame, anchor="nw")
        self.db_canvas.configure(yscrollcommand=db_scroll.set)
        self.db_canvas.pack(side="left", fill="both", expand=True)
        db_scroll.pack(side="right", fill="y")
        self.db_canvas.bind("<MouseWheel>",
            lambda e: self.db_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self.db_rows = {}
        self._build_db_rows()

        # Footer
        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(foot,
                 text="⚠  Some changes require a restart. Create a restore point before running 'Debloat All'.",
                 font=("Consolas", 7), fg=YELLOW, bg=BG).pack(anchor="w")

    # ── Debloat data ──────────────────────────────────────────────────────────
    _DEBLOAT_ITEMS = [
        # ── Apps ──────────────────────────────────────────────────────────────
        {"id": "db_xbox",    "name": "Remove Xbox Apps",
         "desc": "Removes Xbox App, Xbox Game Bar, Xbox Identity Provider bloatware.",
         "impact": "MED", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "'
                             'Get-AppxPackage *xbox* | Remove-AppxPackage -ErrorAction SilentlyContinue; '
                             'Get-AppxProvisionedPackage -Online | Where-Object {$_.PackageName -like \'*xbox*\'} | '
                             'Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue; '
                             'Write-Host Done"'), "Linux": "echo 'Windows only'", "Darwin": "echo 'Windows only'"}},
        {"id": "db_cortana",  "name": "Disable Cortana",
         "desc": "Disables and packages out Microsoft Cortana assistant.",
         "impact": "MED", "category": "Apps",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Search" '
                             '/v AllowCortana /t REG_DWORD /d 0 /f & '
                             'powershell -Command "Get-AppxPackage *cortana* | Remove-AppxPackage '
                             '-ErrorAction SilentlyContinue"'),
                 "Linux": "echo 'Windows only'", "Darwin": "echo 'Windows only'"}},
        {"id": "db_teams",    "name": "Remove Teams Consumer (Personal)",
         "desc": "Removes the personal Teams app pre-installed with Windows 11.",
         "impact": "LOW", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "'
                             'Get-AppxPackage *Teams* | Remove-AppxPackage -ErrorAction SilentlyContinue; '
                             'Write-Host Done"'), "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_3dviewer", "name": "Remove 3D Viewer / Mixed Reality",
         "desc": "Removes 3D Viewer, Paint 3D, and Mixed Reality Portal.",
         "impact": "LOW", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "'
                             'Get-AppxPackage *Microsoft.Microsoft3DViewer* | Remove-AppxPackage '
                             '-ErrorAction SilentlyContinue; '
                             'Get-AppxPackage *Microsoft.MixedReality.Portal* | Remove-AppxPackage '
                             '-ErrorAction SilentlyContinue; '
                             'Get-AppxPackage *Microsoft.MSPaint* | Remove-AppxPackage '
                             '-ErrorAction SilentlyContinue; Write-Host Done"'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_solitaire","name": "Remove Solitaire / Casual Games",
         "desc": "Removes Microsoft Solitaire Collection and other built-in casual games.",
         "impact": "LOW", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "Get-AppxPackage *solitaire* | '
                             'Remove-AppxPackage -ErrorAction SilentlyContinue; Write-Host Done"'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_clipchamp","name": "Remove Clipchamp Video Editor",
         "desc": "Removes the built-in Clipchamp video editor app.",
         "impact": "LOW", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "Get-AppxPackage *clipchamp* | '
                             'Remove-AppxPackage -ErrorAction SilentlyContinue; Write-Host Done"'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_news",    "name": "Remove News / Weather / Maps Apps",
         "desc": "Removes Microsoft News, Weather, Maps, and Bing apps.",
         "impact": "LOW", "category": "Apps",
         "cmd": {"Windows": ('powershell -Command "'
                             'Get-AppxPackage *BingNews* | Remove-AppxPackage -ErrorAction SilentlyContinue; '
                             'Get-AppxPackage *BingWeather* | Remove-AppxPackage -ErrorAction SilentlyContinue; '
                             'Get-AppxPackage *WindowsMaps* | Remove-AppxPackage -ErrorAction SilentlyContinue; '
                             'Write-Host Done"'), "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_onedrive", "name": "Uninstall OneDrive",
         "desc": "Kills OneDrive sync and uninstalls it. Use if you don't use OneDrive.",
         "impact": "HIGH", "category": "Apps",
         "cmd": {"Windows": ('taskkill /F /IM OneDrive.exe 2>nul & '
                             '%SystemRoot%\\SysWOW64\\OneDriveSetup.exe /uninstall 2>nul & '
                             '%SystemRoot%\\System32\\OneDriveSetup.exe /uninstall 2>nul & echo Done'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        # ── Services ──────────────────────────────────────────────────────────
        {"id": "db_svc_diag", "name": "Disable Diagnostics Tracking Service",
         "desc": "Stops and disables DiagTrack (Connected User Experiences and Telemetry).",
         "impact": "HIGH", "category": "Services",
         "cmd": {"Windows": "sc stop DiagTrack & sc config DiagTrack start= disabled",
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": "sc config DiagTrack start= auto & sc start DiagTrack",
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_svc_wap",  "name": "Disable WAP Push Service",
         "desc": "Stops Windows WAP Push Message Routing Service (DmWapPushService).",
         "impact": "MED", "category": "Services",
         "cmd": {"Windows": "sc stop DmWapPushService & sc config DmWapPushService start= disabled",
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": "sc config DmWapPushService start= auto",
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_svc_sup",  "name": "Disable Superfetch / SysMain",
         "desc": "Disables SysMain (Superfetch). Can reduce RAM thrashing on SSDs.",
         "impact": "MED", "category": "Services",
         "cmd": {"Windows": "sc stop SysMain & sc config SysMain start= disabled",
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": "sc config SysMain start= auto & sc start SysMain",
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_svc_pref", "name": "Disable Windows Search Indexing",
         "desc": "Disables WSearch service. Reduces disk I/O. Use if you don't use Windows Search.",
         "impact": "MED", "category": "Services",
         "cmd": {"Windows": "sc stop WSearch & sc config WSearch start= disabled",
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": "sc config WSearch start= delayed-auto & sc start WSearch",
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        # ── Privacy ───────────────────────────────────────────────────────────
        {"id": "db_priv_adid","name": "Disable Advertising ID",
         "desc": "Prevents apps from using your unique advertising ID for targeted ads.",
         "impact": "MED", "category": "Privacy",
         "cmd": {"Windows": ('reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo" '
                             '/v Enabled /t REG_DWORD /d 0 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo" '
                                  '/v Enabled /t REG_DWORD /d 1 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_priv_feed","name": "Disable Activity / Timeline Feed",
         "desc": "Disables Windows Timeline and activity tracking.",
         "impact": "MED", "category": "Privacy",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\System" '
                             '/v EnableActivityFeed /t REG_DWORD /d 0 /f & '
                             'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\System" '
                             '/v PublishUserActivities /t REG_DWORD /d 0 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_priv_cam", "name": "Disable App Access to Camera",
         "desc": "Prevents apps from accessing your camera (can be re-enabled per-app in Settings).",
         "impact": "MED", "category": "Privacy",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy" '
                             '/v LetAppsAccessCamera /t REG_DWORD /d 2 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy" '
                                  '/v LetAppsAccessCamera /t REG_DWORD /d 0 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_priv_mic", "name": "Disable App Access to Microphone",
         "desc": "Prevents apps from accessing your microphone in the background.",
         "impact": "MED", "category": "Privacy",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy" '
                             '/v LetAppsAccessMicrophone /t REG_DWORD /d 2 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy" '
                                  '/v LetAppsAccessMicrophone /t REG_DWORD /d 0 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        # ── Telemetry ─────────────────────────────────────────────────────────
        {"id": "db_tele_min", "name": "Set Telemetry to Minimum (Security only)",
         "desc": "Sets Windows telemetry level to 0 (Security) — sends minimum possible data to Microsoft.",
         "impact": "HIGH", "category": "Telemetry",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection" '
                             '/v AllowTelemetry /t REG_DWORD /d 0 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection" '
                                  '/v AllowTelemetry /t REG_DWORD /d 1 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_tele_ce",  "name": "Disable Customer Experience Improvement Program",
         "desc": "Opts out of CEIP which sends usage statistics to Microsoft.",
         "impact": "MED", "category": "Telemetry",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Microsoft\\SQMClient\\Windows" '
                             '/v CEIPEnable /t REG_DWORD /d 0 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_tele_err", "name": "Disable Error Reporting",
         "desc": "Stops Windows from sending crash reports to Microsoft.",
         "impact": "LOW", "category": "Telemetry",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\Windows Error Reporting" '
                             '/v Disabled /t REG_DWORD /d 1 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Microsoft\\Windows\\Windows Error Reporting" '
                                  '/v Disabled /t REG_DWORD /d 0 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        # ── Startup ───────────────────────────────────────────────────────────
        {"id": "db_startup_od","name": "Disable OneDrive Startup Entry",
         "desc": "Prevents OneDrive from starting with Windows.",
         "impact": "MED", "category": "Startup",
         "cmd": {"Windows": ('reg delete "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run" '
                             '/v OneDrive /f 2>nul & echo Done'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_startup_edge","name": "Disable Edge Startup Boost",
         "desc": "Stops Microsoft Edge from pre-loading at startup to save RAM.",
         "impact": "MED", "category": "Startup",
         "cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge" '
                             '/v StartupBoostEnabled /t REG_DWORD /d 0 /f & '
                             'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge" '
                             '/v BackgroundModeEnabled /t REG_DWORD /d 0 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge" '
                                  '/v StartupBoostEnabled /t REG_DWORD /d 1 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_startup_co","name": "Disable Copilot / Widgets",
         "desc": "Removes Windows Copilot and widgets from taskbar and disables background loading.",
         "impact": "MED", "category": "Startup",
         "cmd": {"Windows": ('reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced" '
                             '/v TaskbarDa /t REG_DWORD /d 0 /f & '
                             'reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\WindowsCopilot" '
                             '/v TurnOffWindowsCopilot /t REG_DWORD /d 1 /f'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"},
         "undo_cmd": {"Windows": ('reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced" '
                                  '/v TaskbarDa /t REG_DWORD /d 1 /f'),
                      "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        # ── Junk Files ────────────────────────────────────────────────────────
        {"id": "db_junk_temp","name": "Delete Temp Files (%TEMP% + Windows\\Temp)",
         "desc": "Removes all temporary files from user and system TEMP folders.",
         "impact": "LOW", "category": "Junk Files",
         "cmd": {"Windows": ('cmd /c "del /f /s /q %TEMP%\\* 2>nul & rd /s /q %TEMP% 2>nul & '
                             'md %TEMP% 2>nul & del /f /s /q C:\\Windows\\Temp\\* 2>nul & echo Done"'),
                 "Linux": "rm -rf /tmp/* 2>/dev/null || true",
                 "Darwin": "rm -rf /private/tmp/* 2>/dev/null || true"}},
        {"id": "db_junk_pfetch","name": "Clear Windows Prefetch Files",
         "desc": "Deletes Prefetch folder. Windows rebuilds it on next use.",
         "impact": "LOW", "category": "Junk Files",
         "cmd": {"Windows": ('cmd /c "del /f /s /q C:\\Windows\\Prefetch\\* 2>nul & echo Done"'),
                 "Linux": "echo 'N/A'", "Darwin": "echo 'N/A'"}},
        {"id": "db_junk_thumb","name": "Clear Thumbnail Cache",
         "desc": "Deletes Windows thumbnail database cache files.",
         "impact": "LOW", "category": "Junk Files",
         "cmd": {"Windows": ('taskkill /F /IM explorer.exe & '
                             'del /f /s /q %LocalAppData%\\Microsoft\\Windows\\Explorer\\thumbcache_*.db 2>nul & '
                             'start explorer & echo Done'),
                 "Linux": "rm -rf ~/.thumbnails/* 2>/dev/null || true",
                 "Darwin": "qlmanage -r cache 2>/dev/null || true"}},
        {"id": "db_junk_dns", "name": "Clear Windows Event Logs",
         "desc": "Clears System, Application, and Security event logs to free disk space.",
         "impact": "LOW", "category": "Junk Files",
         "cmd": {"Windows": ('powershell -Command "Get-EventLog -List | ForEach-Object {'
                             ' Clear-EventLog -LogName $_.Log -ErrorAction SilentlyContinue }; Write-Host Done"'),
                 "Linux": "journalctl --vacuum-time=1d 2>/dev/null || true",
                 "Darwin": "sudo log erase --all 2>/dev/null || true"}},
        {"id": "db_junk_wumc","name": "Clean Windows Update Cache",
         "desc": "Removes old Windows Update download cache (SoftwareDistribution folder).",
         "impact": "MED", "category": "Junk Files",
         "cmd": {"Windows": ('net stop wuauserv 2>nul & net stop cryptSvc 2>nul & '
                             'net stop bits 2>nul & net stop msiserver 2>nul & '
                             'rd /s /q C:\\Windows\\SoftwareDistribution 2>nul & '
                             'net start wuauserv 2>nul & net start cryptSvc 2>nul & '
                             'net start bits 2>nul & echo Done'),
                 "Linux": "apt-get clean 2>/dev/null || true",
                 "Darwin": "echo 'N/A'"}},
    ]

    def _build_db_rows(self):
        DB_ACCENT = "#7b2fff"
        DB_GREEN  = "#00ff9d"
        DB_YELLOW = "#ffe156"

        IMPACT_COLORS = {"HIGH": DB_GREEN, "MED": DB_YELLOW, "LOW": ACCENT}
        CAT_COLORS = {
            "Apps":       "#ff8c42",
            "Services":   "#00d4ff",
            "Privacy":    "#7b2fff",
            "Telemetry":  "#ff3c5f",
            "Startup":    "#ffe156",
            "Junk Files": "#00ff9d",
        }

        for widget in self.db_scroll_frame.winfo_children():
            widget.destroy()
        self.db_rows = {}

        active = self._db_category.get()
        visible = [t for t in self._DEBLOAT_ITEMS
                   if active == "All" or t.get("category") == active]

        last_cat = None
        for t in visible:
            cat = t.get("category", "")
            if cat != last_cat:
                last_cat = cat
                cat_col = CAT_COLORS.get(cat, ACCENT)
                div = tk.Frame(self.db_scroll_frame, bg=BG)
                div.pack(fill="x", pady=(10, 2), padx=2)
                tk.Label(div,
                         text=f"── {cat.upper()} ─────────────────────────────────",
                         font=("Consolas", 8, "bold"),
                         fg=cat_col, bg=BG).pack(side="left")

            outer = tk.Frame(self.db_scroll_frame, bg=BORDER)
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=PANEL)
            row_frame.pack(fill="x", padx=1, pady=1)

            info = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            badges = tk.Frame(info, bg=PANEL)
            badges.pack(fill="x")
            icol = IMPACT_COLORS.get(t.get("impact", "MED"), DB_YELLOW)
            tk.Label(badges, text=f"[{t.get('impact','MED')}]",
                     font=("Consolas", 7, "bold"), fg=icol, bg=PANEL, width=6).pack(side="left")
            cat_col = CAT_COLORS.get(cat, ACCENT)
            tk.Label(badges, text=f"[{cat}]",
                     font=("Consolas", 7, "bold"), fg=cat_col, bg=PANEL).pack(side="left", padx=(2, 8))
            tk.Label(badges, text=t["name"],
                     font=("Consolas", 9, "bold"), fg=TEXT, bg=PANEL, anchor="w").pack(side="left")
            tk.Label(info, text=t["desc"],
                     font=("Consolas", 8), fg=TEXT3, bg=PANEL, anchor="w",
                     wraplength=600, justify="left").pack(fill="x")

            controls = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○", font=("Consolas", 12),
                                  fg=TEXT3, bg=PANEL)
            status_lbl.pack(side="left", padx=(0, 6))

            if t.get("undo_cmd") and t["undo_cmd"].get(OS, ""):
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg=YELLOW,
                                     bg=BG3, relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda tid=t["id"]: self._db_undo(tid))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8, "bold"),
                                  fg="#fff", bg=DB_ACCENT,
                                  relief="flat", cursor="hand2",
                                  padx=10, pady=2,
                                  command=lambda tid=t["id"]: self._db_apply(tid))
            apply_btn.pack(side="left")

            self.db_rows[t["id"]] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn
            }
            if t["id"] in self.applied:
                status_lbl.config(text="✓", fg=DB_GREEN)
                apply_btn.config(text="Done", fg=DB_GREEN, state="disabled")

    def _db_filter(self, category):
        DB_ACCENT = "#7b2fff"
        self._db_category.set(category)
        for cat, btn in self._db_cat_btns.items():
            if cat == category:
                btn.config(fg=DB_ACCENT, bg=BG3)
            else:
                btn.config(fg=TEXT2, bg=BG2)
        self._build_db_rows()

    def _db_apply(self, tweak_id):
        t = next((x for x in self._DEBLOAT_ITEMS if x["id"] == tweak_id), None)
        if not t: return
        cmd = t["cmd"].get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Debloat] Skipped (Windows only): {t['name']}", "warn")
            return
        self._log(f"[Debloat] Applying: {t['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=60)
            if ok or (out and "not found" not in out.lower() and "error" not in out.lower()):
                self.applied.add(tweak_id)
                msg = out[:100] if out else "OK"
                self._log(f"[Debloat] ✓ {t['name']}  {msg}", "ok")
                self.root.after(0, self._db_refresh_row, tweak_id, True)
            else:
                self._log(f"[Debloat] ✗ {t['name']}  {(err or out)[:100]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _db_undo(self, tweak_id):
        t = next((x for x in self._DEBLOAT_ITEMS if x["id"] == tweak_id), None)
        if not t: return
        cmd = t.get("undo_cmd", {}).get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Debloat] No undo available: {t['name']}", "warn")
            return
        self._log(f"[Debloat] Undoing: {t['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=30)
            if ok:
                self.applied.discard(tweak_id)
                self._log(f"[Debloat] ↩ Undone: {t['name']}", "ok")
                self.root.after(0, self._db_refresh_row, tweak_id, False)
            else:
                self._log(f"[Debloat] ✗ Undo failed: {t['name']}  {(err or out)[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _db_refresh_row(self, tweak_id, applied):
        if tweak_id in self.db_rows:
            row = self.db_rows[tweak_id]
            if applied:
                row["status"].config(text="✓", fg="#00ff9d")
                row["btn"].config(text="Done", fg="#00ff9d", state="disabled")
            else:
                row["status"].config(text="○", fg=TEXT3)
                row["btn"].config(text="Apply", fg="#fff",
                                  bg="#7b2fff", state="normal")

    def _debloat_run_all(self):
        active = self._db_category.get()
        visible = [t for t in self._DEBLOAT_ITEMS
                   if active == "All" or t.get("category") == active]
        self._log(f"[Debloat] Running all {active} debloat tasks…", "ok")
        def _run_all():
            for t in visible:
                cmd = t["cmd"].get(OS, "")
                if not cmd or cmd.startswith("echo"): continue
                ok, out, err = run_cmd(cmd, timeout=60)
                if ok or (out and "not found" not in out.lower()):
                    self.applied.add(t["id"])
                    self._log(f"[Debloat] ✓ {t['name']}", "ok")
                    self.root.after(0, self._db_refresh_row, t["id"], True)
                else:
                    self._log(f"[Debloat] ✗ {t['name']}  {(err or out)[:60]}", "err")
                time.sleep(0.3)
            self._log("[Debloat] Done! Restart Windows to apply all changes.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 6: Fortnite
    # ─────────────────────────────────────────────────────────────────────────
    def _build_fortnite_tab(self, parent):
        FN_PURPLE = "#7b2fff"
        FN_GOLD   = "#ffd700"
        FN_BLUE   = "#00d4ff"

        # ── Hero banner ───────────────────────────────────────────────────────
        banner = tk.Frame(parent, bg="#0a0a1a", height=72)
        banner.pack(fill="x")
        banner.pack_propagate(False)

        tk.Label(banner, text="🎮  FORTNITE OPTIMIZER",
                 font=("Consolas", 16, "bold"),
                 fg=FN_GOLD, bg="#0a0a1a").pack(side="left", padx=18, pady=16)
        tk.Label(banner,
                 text="FPS  •  PING  •  LATENCY  •  SMOOTHNESS",
                 font=("Consolas", 9), fg="#555577", bg="#0a0a1a").pack(side="left", pady=18)

        tk.Button(banner, text="⚡ APPLY ALL",
                  font=("Consolas", 9, "bold"),
                  fg="#0a0a1a", bg=FN_GOLD, relief="flat",
                  cursor="hand2", padx=14, pady=6,
                  command=self._fn_apply_all).pack(side="right", padx=16, pady=14)

        tk.Frame(parent, bg="#1a1a2e", height=1).pack(fill="x")

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(parent, bg="#0f0f1f")
        fbar.pack(fill="x")
        tk.Frame(fbar, bg="#1a1a2e", height=1).pack(fill="x", side="bottom")

        tk.Label(fbar, text="  CATEGORY:",
                 font=("Consolas", 8), fg="#555577", bg="#0f0f1f").pack(side="left", padx=(12,4), pady=7)

        self._fn_cat_btns = {}
        CAT_ICONS = {"All": "★", "FPS": "📈", "Network": "📡", "CPU": "⚙", "Cleanup": "🧹"}
        for cat in FN_CATEGORIES:
            icon = CAT_ICONS.get(cat, "")
            is_sel = (cat == "All")
            btn = tk.Button(fbar, text=f"{icon} {cat}",
                            font=("Consolas", 8, "bold"),
                            fg=FN_GOLD if is_sel else "#666688",
                            bg="#1a1a2e" if is_sel else "#0f0f1f",
                            relief="flat", cursor="hand2", padx=10, pady=3,
                            command=lambda c=cat: self._fn_filter(c))
            btn.pack(side="left", padx=2, pady=5)
            self._fn_cat_btns[cat] = btn

        # ── Scrollable tweak list ─────────────────────────────────────────────
        container = tk.Frame(parent, bg="#0a0a1a")
        container.pack(fill="both", expand=True, padx=12, pady=8)

        self.fn_canvas = tk.Canvas(container, bg="#0a0a1a", highlightthickness=0, bd=0)
        fn_scroll = tk.Scrollbar(container, orient="vertical", command=self.fn_canvas.yview)
        self.fn_scroll_frame = tk.Frame(self.fn_canvas, bg="#0a0a1a")

        self.fn_scroll_frame.bind("<Configure>",
            lambda e: self.fn_canvas.configure(
                scrollregion=self.fn_canvas.bbox("all")))

        self.fn_canvas.create_window((0, 0), window=self.fn_scroll_frame, anchor="nw")
        self.fn_canvas.configure(yscrollcommand=fn_scroll.set)
        self.fn_canvas.pack(side="left", fill="both", expand=True)
        fn_scroll.pack(side="right", fill="y")

        self.fn_canvas.bind("<MouseWheel>",
            lambda e: self.fn_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_fn_rows()

        # ── Info footer ───────────────────────────────────────────────────────
        foot = tk.Frame(parent, bg="#0a0a1a")
        foot.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(foot,
                 text="💡  Config tweaks edit GameUserSettings.ini — close Fortnite before applying FPS/graphics changes.",
                 font=("Consolas", 7), fg="#444466", bg="#0a0a1a").pack(anchor="w")

    def _build_fn_rows(self):
        FN_GOLD  = "#ffd700"
        FN_BLUE  = "#00d4ff"
        FN_GREEN = "#39ff14"

        IMPACT_COLORS = {"HIGH": FN_GREEN, "MED": "#ffd740", "LOW": FN_BLUE, "INFO": "#888888"}
        CAT_COLORS    = {
            "FPS":     "#ff6b35",
            "Network": "#00d4ff",
            "CPU":     "#a855f7",
            "Cleanup": "#22c55e",
        }

        for widget in self.fn_scroll_frame.winfo_children():
            widget.destroy()
        self.fn_tweak_rows = {}

        active = self._fn_category.get()
        visible = [t for t in FORTNITE_TWEAKS
                   if active == "All" or t.get("category") == active]

        # Group by category for visual section headers
        last_cat = None
        for t in visible:
            cat = t.get("category", "")

            # Section divider when category changes
            if cat != last_cat:
                last_cat = cat
                cat_col = CAT_COLORS.get(cat, FN_BLUE)
                div = tk.Frame(self.fn_scroll_frame, bg="#0a0a1a")
                div.pack(fill="x", pady=(10, 2), padx=2)
                tk.Label(div,
                         text=f"── {cat.upper()} ────────────────────────────────",
                         font=("Consolas", 8, "bold"),
                         fg=cat_col, bg="#0a0a1a").pack(side="left")

            outer = tk.Frame(self.fn_scroll_frame, bg="#1a1a2e")
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg="#141428")
            row_frame.pack(fill="x", padx=1, pady=1)

            # Left side: badges + name + desc
            info = tk.Frame(row_frame, bg="#141428", padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            badges = tk.Frame(info, bg="#141428")
            badges.pack(fill="x")

            icol = IMPACT_COLORS.get(t.get("impact", "MED"), "#ffd740")
            tk.Label(badges,
                     text=f"[{t.get('impact','MED')}]",
                     font=("Consolas", 7, "bold"),
                     fg=icol, bg="#141428", width=6).pack(side="left")

            cat_col = CAT_COLORS.get(cat, FN_BLUE)
            tk.Label(badges,
                     text=f"[{cat}]",
                     font=("Consolas", 7, "bold"),
                     fg=cat_col, bg="#141428").pack(side="left", padx=(2, 8))

            tk.Label(badges, text=t["name"],
                     font=("Consolas", 9, "bold"),
                     fg="#e8e8ff", bg="#141428", anchor="w").pack(side="left")

            tk.Label(info, text=t["desc"],
                     font=("Consolas", 8),
                     fg="#555577", bg="#141428",
                     anchor="w", wraplength=580, justify="left").pack(fill="x")

            # Right side: status + buttons
            controls = tk.Frame(row_frame, bg="#141428", padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○",
                                  font=("Consolas", 12), fg="#333355", bg="#141428")
            status_lbl.pack(side="left", padx=(0, 6))

            if t.get("undo_cmd") and t["undo_cmd"].get(OS, ""):
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg="#ffd740",
                                     bg="#1a1a2e", relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda tid=t["id"]: self._fn_undo(tid))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8, "bold"),
                                  fg="#0a0a1a", bg=FN_GOLD,
                                  relief="flat", cursor="hand2",
                                  padx=10, pady=2,
                                  command=lambda tid=t["id"]: self._fn_apply(tid))
            apply_btn.pack(side="left")

            self.fn_tweak_rows[t["id"]] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn
            }
            # Restore applied state
            if t["id"] in self.applied:
                status_lbl.config(text="✓", fg="#39ff14")
                apply_btn.config(text="Done", fg="#39ff14",
                                 bg="#1a1a2e", state="disabled")

    def _fn_filter(self, category):
        self._fn_category.set(category)
        FN_GOLD = "#ffd700"
        for cat, btn in self._fn_cat_btns.items():
            if cat == category:
                btn.config(fg=FN_GOLD, bg="#1a1a2e")
            else:
                btn.config(fg="#666688", bg="#0f0f1f")
        self._build_fn_rows()

    def _fn_apply(self, tweak_id):
        tweak = next((t for t in FORTNITE_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak["cmd"].get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Fortnite] Skipped (Windows only): {tweak['name']}", "warn")
            return
        self._log(f"[Fortnite] Applying: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=30)
            if ok or (out and "not found" not in out.lower() and "error" not in out.lower()):
                self.applied.add(tweak_id)
                msg = out[:100] if out else "OK"
                self._log(f"[Fortnite] ✓ {tweak['name']}  {msg}", "ok")
                self.root.after(0, self._fn_refresh_row, tweak_id, True)
            else:
                detail = (err or out)[:100]
                self._log(f"[Fortnite] ✗ {tweak['name']}  {detail}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _fn_undo(self, tweak_id):
        tweak = next((t for t in FORTNITE_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak.get("undo_cmd", {}).get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Fortnite] No undo available: {tweak['name']}", "warn")
            return
        self._log(f"[Fortnite] Undoing: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=20)
            if ok:
                self.applied.discard(tweak_id)
                self._log(f"[Fortnite] ↩ Undone: {tweak['name']}", "ok")
                self.root.after(0, self._fn_refresh_row, tweak_id, False)
            else:
                self._log(f"[Fortnite] ✗ Undo failed: {tweak['name']}  {err[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _fn_apply_all(self):
        active = self._fn_category.get()
        visible = [t for t in FORTNITE_TWEAKS
                   if active == "All" or t.get("category") == active]
        self._log(f"[Fortnite] Applying all {active} tweaks…", "ok")
        def _run_all():
            for t in visible:
                cmd = t["cmd"].get(OS, "")
                if not cmd or cmd.startswith("echo"):
                    self._log(f"[Fortnite] Skipped: {t['name']}", "warn")
                    continue
                ok, out, err = run_cmd(cmd, timeout=30)
                if ok or (out and "not found" not in out.lower()):
                    self.applied.add(t["id"])
                    self._log(f"[Fortnite] ✓ {t['name']}", "ok")
                    self.root.after(0, self._fn_refresh_row, t["id"], True)
                else:
                    self._log(f"[Fortnite] ✗ {t['name']}  {(err or out)[:60]}", "err")
                time.sleep(0.25)
            self._log("[Fortnite] Done! Restart Fortnite to see changes.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    def _fn_refresh_row(self, tweak_id, applied):
        if tweak_id in self.fn_tweak_rows:
            row = self.fn_tweak_rows[tweak_id]
            if applied:
                row["status"].config(text="✓", fg="#39ff14")
                row["btn"].config(text="Done", fg="#39ff14",
                                  bg="#1a1a2e", state="disabled")
            else:
                row["status"].config(text="○", fg="#333355")
                row["btn"].config(text="Apply", fg="#0a0a1a",
                                  bg="#ffd700", state="normal")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 7: Valorant
    # ─────────────────────────────────────────────────────────────────────────
    def _build_valorant_tab(self, parent):
        VAL_RED   = "#ff4655"
        VAL_WHITE = "#ece8e1"
        VAL_DARK  = "#0f1923"
        VAL_MID   = "#1f2731"
        VAL_DIM   = "#384454"

        # ── Hero banner ───────────────────────────────────────────────────────
        banner = tk.Frame(parent, bg=VAL_DARK, height=72)
        banner.pack(fill="x")
        banner.pack_propagate(False)

        tk.Label(banner, text="🔫  VALORANT OPTIMIZER",
                 font=("Consolas", 16, "bold"),
                 fg=VAL_RED, bg=VAL_DARK).pack(side="left", padx=18, pady=16)
        tk.Label(banner,
                 text="FPS  •  PING  •  ZERO LATENCY  •  CLEAN FRAGGING",
                 font=("Consolas", 9), fg=VAL_DIM, bg=VAL_DARK).pack(side="left", pady=18)

        tk.Button(banner, text="⚡ APPLY ALL",
                  font=("Consolas", 9, "bold"),
                  fg=VAL_WHITE, bg=VAL_RED, relief="flat",
                  cursor="hand2", padx=14, pady=6,
                  command=self._val_apply_all).pack(side="right", padx=16, pady=14)

        tk.Frame(parent, bg=VAL_DIM, height=1).pack(fill="x")

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(parent, bg=VAL_MID)
        fbar.pack(fill="x")
        tk.Frame(fbar, bg=VAL_DIM, height=1).pack(fill="x", side="bottom")

        tk.Label(fbar, text="  CATEGORY:",
                 font=("Consolas", 8), fg=VAL_DIM, bg=VAL_MID).pack(side="left", padx=(12,4), pady=7)

        self._val_cat_btns = {}
        CAT_ICONS = {"All": "★", "FPS": "📈", "Network": "📡", "CPU": "⚙", "Cleanup": "🧹"}
        for cat in VAL_CATEGORIES:
            icon = CAT_ICONS.get(cat, "")
            is_sel = (cat == "All")
            btn = tk.Button(fbar, text=f"{icon} {cat}",
                            font=("Consolas", 8, "bold"),
                            fg=VAL_RED if is_sel else VAL_DIM,
                            bg=VAL_DARK if is_sel else VAL_MID,
                            relief="flat", cursor="hand2", padx=10, pady=3,
                            command=lambda c=cat: self._val_filter(c))
            btn.pack(side="left", padx=2, pady=5)
            self._val_cat_btns[cat] = btn

        # ── Scrollable tweak list ─────────────────────────────────────────────
        container = tk.Frame(parent, bg=VAL_DARK)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        self.val_canvas = tk.Canvas(container, bg=VAL_DARK, highlightthickness=0, bd=0)
        val_scroll = tk.Scrollbar(container, orient="vertical", command=self.val_canvas.yview)
        self.val_scroll_frame = tk.Frame(self.val_canvas, bg=VAL_DARK)

        self.val_scroll_frame.bind("<Configure>",
            lambda e: self.val_canvas.configure(
                scrollregion=self.val_canvas.bbox("all")))

        self.val_canvas.create_window((0, 0), window=self.val_scroll_frame, anchor="nw")
        self.val_canvas.configure(yscrollcommand=val_scroll.set)
        self.val_canvas.pack(side="left", fill="both", expand=True)
        val_scroll.pack(side="right", fill="y")

        self.val_canvas.bind("<MouseWheel>",
            lambda e: self.val_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_val_rows()

        # ── Footer tip ────────────────────────────────────────────────────────
        foot = tk.Frame(parent, bg=VAL_DARK)
        foot.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(foot,
                 text="💡  Config tweaks edit GameUserSettings.ini — close Valorant before applying FPS/graphics changes.",
                 font=("Consolas", 7), fg=VAL_DIM, bg=VAL_DARK).pack(anchor="w")

    def _build_val_rows(self):
        VAL_RED   = "#ff4655"
        VAL_WHITE = "#ece8e1"
        VAL_DARK  = "#0f1923"
        VAL_MID   = "#1f2731"
        VAL_DIM   = "#384454"
        VAL_GREEN = "#00e676"

        IMPACT_COLORS = {"HIGH": VAL_RED, "MED": "#ffd740", "LOW": "#00d4ff", "INFO": "#888888"}
        CAT_COLORS    = {
            "FPS":     "#ff4655",
            "Network": "#00d4ff",
            "CPU":     "#a855f7",
            "Cleanup": "#22c55e",
        }

        for widget in self.val_scroll_frame.winfo_children():
            widget.destroy()
        self.val_tweak_rows = {}

        active = self._val_category.get()
        visible = [t for t in VALORANT_TWEAKS
                   if active == "All" or t.get("category") == active]

        last_cat = None
        for t in visible:
            cat = t.get("category", "")

            if cat != last_cat:
                last_cat = cat
                cat_col = CAT_COLORS.get(cat, "#00d4ff")
                div = tk.Frame(self.val_scroll_frame, bg=VAL_DARK)
                div.pack(fill="x", pady=(10, 2), padx=2)
                tk.Label(div,
                         text=f"── {cat.upper()} ────────────────────────────────",
                         font=("Consolas", 8, "bold"),
                         fg=cat_col, bg=VAL_DARK).pack(side="left")

            outer = tk.Frame(self.val_scroll_frame, bg=VAL_DIM)
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=VAL_MID)
            row_frame.pack(fill="x", padx=1, pady=1)

            # Left: badges + name + desc
            info = tk.Frame(row_frame, bg=VAL_MID, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            badges = tk.Frame(info, bg=VAL_MID)
            badges.pack(fill="x")

            icol = IMPACT_COLORS.get(t.get("impact", "MED"), "#ffd740")
            tk.Label(badges,
                     text=f"[{t.get('impact','MED')}]",
                     font=("Consolas", 7, "bold"),
                     fg=icol, bg=VAL_MID, width=6).pack(side="left")

            cat_col = CAT_COLORS.get(cat, "#00d4ff")
            tk.Label(badges,
                     text=f"[{cat}]",
                     font=("Consolas", 7, "bold"),
                     fg=cat_col, bg=VAL_MID).pack(side="left", padx=(2, 8))

            tk.Label(badges, text=t["name"],
                     font=("Consolas", 9, "bold"),
                     fg=VAL_WHITE, bg=VAL_MID, anchor="w").pack(side="left")

            tk.Label(info, text=t["desc"],
                     font=("Consolas", 8),
                     fg=VAL_DIM, bg=VAL_MID,
                     anchor="w", wraplength=580, justify="left").pack(fill="x")

            # Right: status + buttons
            controls = tk.Frame(row_frame, bg=VAL_MID, padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○",
                                  font=("Consolas", 12), fg=VAL_DIM, bg=VAL_MID)
            status_lbl.pack(side="left", padx=(0, 6))

            if t.get("undo_cmd") and t["undo_cmd"].get(OS, ""):
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg="#ffd740",
                                     bg=VAL_DARK, relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda tid=t["id"]: self._val_undo(tid))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8, "bold"),
                                  fg=VAL_WHITE, bg=VAL_RED,
                                  relief="flat", cursor="hand2",
                                  padx=10, pady=2,
                                  command=lambda tid=t["id"]: self._val_apply(tid))
            apply_btn.pack(side="left")

            self.val_tweak_rows[t["id"]] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn
            }
            if t["id"] in self.applied:
                status_lbl.config(text="✓", fg=VAL_GREEN)
                apply_btn.config(text="Done", fg=VAL_GREEN, bg=VAL_MID, state="disabled")

    def _val_filter(self, category):
        VAL_RED  = "#ff4655"
        VAL_DARK = "#0f1923"
        VAL_MID  = "#1f2731"
        VAL_DIM  = "#384454"
        self._val_category.set(category)
        for cat, btn in self._val_cat_btns.items():
            if cat == category:
                btn.config(fg=VAL_RED, bg=VAL_DARK)
            else:
                btn.config(fg=VAL_DIM, bg=VAL_MID)
        self._build_val_rows()

    def _val_apply(self, tweak_id):
        tweak = next((t for t in VALORANT_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak["cmd"].get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Valorant] Skipped (Windows only): {tweak['name']}", "warn")
            return
        self._log(f"[Valorant] Applying: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=30)
            if ok or (out and "not found" not in out.lower() and "error" not in out.lower()):
                self.applied.add(tweak_id)
                msg = out[:100] if out else "OK"
                self._log(f"[Valorant] ✓ {tweak['name']}  {msg}", "ok")
                self.root.after(0, self._val_refresh_row, tweak_id, True)
            else:
                detail = (err or out)[:100]
                self._log(f"[Valorant] ✗ {tweak['name']}  {detail}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _val_undo(self, tweak_id):
        tweak = next((t for t in VALORANT_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak.get("undo_cmd", {}).get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[Valorant] No undo available: {tweak['name']}", "warn")
            return
        self._log(f"[Valorant] Undoing: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=20)
            if ok:
                self.applied.discard(tweak_id)
                self._log(f"[Valorant] ↩ Undone: {tweak['name']}", "ok")
                self.root.after(0, self._val_refresh_row, tweak_id, False)
            else:
                self._log(f"[Valorant] ✗ Undo failed: {tweak['name']}  {err[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _val_apply_all(self):
        active = self._val_category.get()
        visible = [t for t in VALORANT_TWEAKS
                   if active == "All" or t.get("category") == active]
        self._log(f"[Valorant] Applying all {active} tweaks…", "ok")
        def _run_all():
            for t in visible:
                cmd = t["cmd"].get(OS, "")
                if not cmd or cmd.startswith("echo"):
                    self._log(f"[Valorant] Skipped: {t['name']}", "warn")
                    continue
                ok, out, err = run_cmd(cmd, timeout=30)
                if ok or (out and "not found" not in out.lower()):
                    self.applied.add(t["id"])
                    self._log(f"[Valorant] ✓ {t['name']}", "ok")
                    self.root.after(0, self._val_refresh_row, t["id"], True)
                else:
                    self._log(f"[Valorant] ✗ {t['name']}  {(err or out)[:60]}", "err")
                time.sleep(0.25)
            self._log("[Valorant] Done! Restart Valorant to see changes.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    def _val_refresh_row(self, tweak_id, applied):
        VAL_RED   = "#ff4655"
        VAL_WHITE = "#ece8e1"
        VAL_MID   = "#1f2731"
        VAL_DIM   = "#384454"
        VAL_GREEN = "#00e676"
        if tweak_id in self.val_tweak_rows:
            row = self.val_tweak_rows[tweak_id]
            if applied:
                row["status"].config(text="✓", fg=VAL_GREEN)
                row["btn"].config(text="Done", fg=VAL_GREEN, bg=VAL_MID, state="disabled")
            else:
                row["status"].config(text="○", fg=VAL_DIM)
                row["btn"].config(text="Apply", fg=VAL_WHITE, bg=VAL_RED, state="normal")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 8: Rainbow Six Siege
    # ─────────────────────────────────────────────────────────────────────────
    def _build_r6_tab(self, parent):
        R6_RED    = "#d62828"
        R6_ORANGE = "#f77f00"
        R6_TAN    = "#fcbf49"
        R6_DARK   = "#0d0d0d"
        R6_MID    = "#1a1a1a"
        R6_PANEL  = "#141414"
        R6_DIM    = "#4a4a4a"

        # ── Hero banner ───────────────────────────────────────────────────────
        banner = tk.Frame(parent, bg=R6_DARK, height=72)
        banner.pack(fill="x")
        banner.pack_propagate(False)

        tk.Label(banner, text="🚨  RAINBOW SIX SIEGE",
                 font=("Consolas", 16, "bold"),
                 fg=R6_TAN, bg=R6_DARK).pack(side="left", padx=18, pady=16)
        tk.Label(banner,
                 text="FPS  •  PING  •  SMOOTHNESS  •  PEEKER'S ADVANTAGE",
                 font=("Consolas", 9), fg=R6_DIM, bg=R6_DARK).pack(side="left", pady=18)

        tk.Button(banner, text="⚡ APPLY ALL",
                  font=("Consolas", 9, "bold"),
                  fg=R6_DARK, bg=R6_TAN, relief="flat",
                  cursor="hand2", padx=14, pady=6,
                  command=self._r6_apply_all).pack(side="right", padx=16, pady=14)

        tk.Frame(parent, bg=R6_ORANGE, height=2).pack(fill="x")

        # ── Filter bar ────────────────────────────────────────────────────────
        fbar = tk.Frame(parent, bg=R6_MID)
        fbar.pack(fill="x")
        tk.Frame(fbar, bg=R6_DIM, height=1).pack(fill="x", side="bottom")

        tk.Label(fbar, text="  CATEGORY:",
                 font=("Consolas", 8), fg=R6_DIM, bg=R6_MID).pack(side="left", padx=(12, 4), pady=7)

        self._r6_cat_btns = {}
        CAT_ICONS = {"All": "★", "FPS": "📈", "Network": "📡", "CPU": "⚙", "Cleanup": "🧹"}
        for cat in R6_CATEGORIES:
            icon = CAT_ICONS.get(cat, "")
            is_sel = (cat == "All")
            btn = tk.Button(fbar, text=f"{icon} {cat}",
                            font=("Consolas", 8, "bold"),
                            fg=R6_TAN if is_sel else R6_DIM,
                            bg=R6_DARK if is_sel else R6_MID,
                            relief="flat", cursor="hand2", padx=10, pady=3,
                            command=lambda c=cat: self._r6_filter(c))
            btn.pack(side="left", padx=2, pady=5)
            self._r6_cat_btns[cat] = btn

        # ── Scrollable tweak list ─────────────────────────────────────────────
        container = tk.Frame(parent, bg=R6_DARK)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        self.r6_canvas = tk.Canvas(container, bg=R6_DARK, highlightthickness=0, bd=0)
        r6_scroll = tk.Scrollbar(container, orient="vertical", command=self.r6_canvas.yview)
        self.r6_scroll_frame = tk.Frame(self.r6_canvas, bg=R6_DARK)

        self.r6_scroll_frame.bind("<Configure>",
            lambda e: self.r6_canvas.configure(
                scrollregion=self.r6_canvas.bbox("all")))

        self.r6_canvas.create_window((0, 0), window=self.r6_scroll_frame, anchor="nw")
        self.r6_canvas.configure(yscrollcommand=r6_scroll.set)
        self.r6_canvas.pack(side="left", fill="both", expand=True)
        r6_scroll.pack(side="right", fill="y")

        self.r6_canvas.bind("<MouseWheel>",
            lambda e: self.r6_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_r6_rows()

        # ── Info footer ───────────────────────────────────────────────────────
        foot = tk.Frame(parent, bg=R6_DARK)
        foot.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(foot,
                 text="💡  Config tweaks edit GameSettings.ini — close Siege before applying FPS/graphics changes.  Path: Documents\\My Games\\Rainbow Six Siege\\<ProfileID>\\",
                 font=("Consolas", 7), fg=R6_DIM, bg=R6_DARK).pack(anchor="w")

    def _build_r6_rows(self):
        R6_TAN   = "#fcbf49"
        R6_DARK  = "#0d0d0d"
        R6_MID   = "#1a1a1a"
        R6_PANEL = "#141414"
        R6_DIM   = "#4a4a4a"
        R6_GREEN = "#57cc04"

        IMPACT_COLORS = {"HIGH": "#ff3c3c", "MED": "#ffd740", "LOW": "#00d4ff", "INFO": "#888888"}
        CAT_COLORS    = {
            "FPS":     R6_TAN,
            "Network": "#00d4ff",
            "CPU":     "#a855f7",
            "Cleanup": "#22c55e",
        }

        for widget in self.r6_scroll_frame.winfo_children():
            widget.destroy()
        self.r6_tweak_rows = {}

        active = self._r6_category.get()
        visible = [t for t in R6_TWEAKS
                   if active == "All" or t.get("category") == active]

        last_cat = None
        for t in visible:
            cat = t.get("category", "")

            if cat != last_cat:
                last_cat = cat
                cat_col = CAT_COLORS.get(cat, R6_TAN)
                div = tk.Frame(self.r6_scroll_frame, bg=R6_DARK)
                div.pack(fill="x", pady=(10, 2), padx=2)
                tk.Label(div,
                         text=f"── {cat.upper()} ────────────────────────────────",
                         font=("Consolas", 8, "bold"),
                         fg=cat_col, bg=R6_DARK).pack(side="left")

            outer = tk.Frame(self.r6_scroll_frame, bg="#2a1a00")
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=R6_PANEL)
            row_frame.pack(fill="x", padx=1, pady=1)

            info = tk.Frame(row_frame, bg=R6_PANEL, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            badges = tk.Frame(info, bg=R6_PANEL)
            badges.pack(fill="x")

            icol = IMPACT_COLORS.get(t.get("impact", "MED"), "#ffd740")
            tk.Label(badges,
                     text=f"[{t.get('impact','MED')}]",
                     font=("Consolas", 7, "bold"),
                     fg=icol, bg=R6_PANEL, width=6).pack(side="left")

            cat_col = CAT_COLORS.get(cat, R6_TAN)
            tk.Label(badges,
                     text=f"[{cat}]",
                     font=("Consolas", 7, "bold"),
                     fg=cat_col, bg=R6_PANEL).pack(side="left", padx=(2, 8))

            tk.Label(badges, text=t["name"],
                     font=("Consolas", 9, "bold"),
                     fg="#f0e6d0", bg=R6_PANEL, anchor="w").pack(side="left")

            tk.Label(info, text=t["desc"],
                     font=("Consolas", 8),
                     fg=R6_DIM, bg=R6_PANEL,
                     anchor="w", wraplength=580, justify="left").pack(fill="x")

            controls = tk.Frame(row_frame, bg=R6_PANEL, padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○",
                                  font=("Consolas", 12), fg="#2a1a00", bg=R6_PANEL)
            status_lbl.pack(side="left", padx=(0, 6))

            if t.get("undo_cmd") and t["undo_cmd"].get(OS, ""):
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg="#ffd740",
                                     bg=R6_MID, relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda tid=t["id"]: self._r6_undo(tid))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8, "bold"),
                                  fg=R6_DARK, bg=R6_TAN,
                                  relief="flat", cursor="hand2",
                                  padx=10, pady=2,
                                  command=lambda tid=t["id"]: self._r6_apply(tid))
            apply_btn.pack(side="left")

            self.r6_tweak_rows[t["id"]] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn
            }
            if t["id"] in self.applied:
                status_lbl.config(text="✓", fg=R6_GREEN)
                apply_btn.config(text="Done", fg=R6_GREEN, bg=R6_MID, state="disabled")

    def _r6_filter(self, category):
        R6_TAN  = "#fcbf49"
        R6_DARK = "#0d0d0d"
        R6_MID  = "#1a1a1a"
        R6_DIM  = "#4a4a4a"
        self._r6_category.set(category)
        for cat, btn in self._r6_cat_btns.items():
            if cat == category:
                btn.config(fg=R6_TAN, bg=R6_DARK)
            else:
                btn.config(fg=R6_DIM, bg=R6_MID)
        self._build_r6_rows()

    def _r6_apply(self, tweak_id):
        tweak = next((t for t in R6_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak["cmd"].get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[R6 Siege] Skipped (Windows only): {tweak['name']}", "warn")
            return
        self._log(f"[R6 Siege] Applying: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=30)
            if ok or (out and "not found" not in out.lower() and "error" not in out.lower()):
                self.applied.add(tweak_id)
                msg = out[:100] if out else "OK"
                self._log(f"[R6 Siege] ✓ {tweak['name']}  {msg}", "ok")
                self.root.after(0, self._r6_refresh_row, tweak_id, True)
            else:
                detail = (err or out)[:100]
                self._log(f"[R6 Siege] ✗ {tweak['name']}  {detail}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _r6_undo(self, tweak_id):
        tweak = next((t for t in R6_TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak.get("undo_cmd", {}).get(OS, "")
        if not cmd or cmd.startswith("echo"):
            self._log(f"[R6 Siege] No undo available: {tweak['name']}", "warn")
            return
        self._log(f"[R6 Siege] Undoing: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=20)
            if ok:
                self.applied.discard(tweak_id)
                self._log(f"[R6 Siege] ↩ Undone: {tweak['name']}", "ok")
                self.root.after(0, self._r6_refresh_row, tweak_id, False)
            else:
                self._log(f"[R6 Siege] ✗ Undo failed: {tweak['name']}  {err[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _r6_apply_all(self):
        active = self._r6_category.get()
        visible = [t for t in R6_TWEAKS
                   if active == "All" or t.get("category") == active]
        self._log(f"[R6 Siege] Applying all {active} tweaks…", "ok")
        def _run_all():
            for t in visible:
                cmd = t["cmd"].get(OS, "")
                if not cmd or cmd.startswith("echo"):
                    self._log(f"[R6 Siege] Skipped: {t['name']}", "warn")
                    continue
                ok, out, err = run_cmd(cmd, timeout=30)
                if ok or (out and "not found" not in out.lower()):
                    self.applied.add(t["id"])
                    self._log(f"[R6 Siege] ✓ {t['name']}", "ok")
                    self.root.after(0, self._r6_refresh_row, t["id"], True)
                else:
                    self._log(f"[R6 Siege] ✗ {t['name']}  {(err or out)[:60]}", "err")
                time.sleep(0.25)
            self._log("[R6 Siege] Done! Restart Siege to see changes.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    def _r6_refresh_row(self, tweak_id, applied):
        R6_TAN   = "#fcbf49"
        R6_DARK  = "#0d0d0d"
        R6_MID   = "#1a1a1a"
        R6_DIM   = "#4a4a4a"
        R6_GREEN = "#57cc04"
        if tweak_id in self.r6_tweak_rows:
            row = self.r6_tweak_rows[tweak_id]
            if applied:
                row["status"].config(text="✓", fg=R6_GREEN)
                row["btn"].config(text="Done", fg=R6_GREEN, bg=R6_MID, state="disabled")
            else:
                row["status"].config(text="○", fg=R6_DIM)
                row["btn"].config(text="Apply", fg=R6_DARK, bg=R6_TAN, state="normal")

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 12: Miscellaneous Downloads
    # ─────────────────────────────────────────────────────────────────────────
    def _build_misc_tab(self, parent):
        MISC_ACCENT = "#00d4ff"
        MISC_GREEN  = "#00ff9d"
        MISC_YELLOW = "#ffe156"

        # ── Banner ────────────────────────────────────────────────────────────
        banner = tk.Frame(parent, bg=BG2, height=72)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=MISC_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="⬇  ESSENTIAL DOWNLOADS",
                 font=("Consolas", 16, "bold"),
                 fg=MISC_ACCENT, bg=BG2).pack(side="left", padx=18, pady=16)
        tk.Label(banner,
                 text="Everything you need on a fresh gaming PC — one click to download.",
                 font=("Consolas", 9), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        # ── Category filter ───────────────────────────────────────────────────
        fbar = tk.Frame(parent, bg=BG2)
        fbar.pack(fill="x")
        tk.Frame(fbar, bg=BORDER, height=1).pack(fill="x", side="bottom")

        tk.Label(fbar, text="  FILTER:",
                 font=("Consolas", 8), fg=TEXT2, bg=BG2).pack(side="left", padx=(12, 4), pady=7)

        self._misc_cat_btns = {}
        for cat in MISC_CATEGORIES:
            is_sel = (cat == "All")
            btn = tk.Button(fbar, text=cat,
                            font=("Consolas", 8, "bold"),
                            fg=MISC_ACCENT if is_sel else TEXT2,
                            bg=BG3 if is_sel else BG2,
                            relief="flat", cursor="hand2", padx=8, pady=3,
                            command=lambda c=cat: self._misc_filter(c))
            btn.pack(side="left", padx=2, pady=5)
            self._misc_cat_btns[cat] = btn

        # ── Scrollable download list ──────────────────────────────────────────
        container = tk.Frame(parent, bg=BG)
        container.pack(fill="both", expand=True, padx=12, pady=8)

        self.misc_canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        misc_scroll = tk.Scrollbar(container, orient="vertical", command=self.misc_canvas.yview)
        self.misc_scroll_frame = tk.Frame(self.misc_canvas, bg=BG)

        self.misc_scroll_frame.bind("<Configure>",
            lambda e: self.misc_canvas.configure(
                scrollregion=self.misc_canvas.bbox("all")))

        self.misc_canvas.create_window((0, 0), window=self.misc_scroll_frame, anchor="nw")
        self.misc_canvas.configure(yscrollcommand=misc_scroll.set)
        self.misc_canvas.pack(side="left", fill="both", expand=True)
        misc_scroll.pack(side="right", fill="y")

        self.misc_canvas.bind("<MouseWheel>",
            lambda e: self.misc_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_misc_rows()

        # Footer
        foot = tk.Frame(parent, bg=BG)
        foot.pack(fill="x", padx=12, pady=(0, 6))
        tk.Label(foot,
                 text="💡  Click 'Open Download Page' to go to the official website. Installer buttons attempt a direct download where available.",
                 font=("Consolas", 7), fg=TEXT3, bg=BG).pack(anchor="w")

    def _build_misc_rows(self):
        active = self._misc_category.get()
        visible = [d for d in MISC_DOWNLOADS
                   if active == "All" or d.get("category") == active]

        for widget in self.misc_scroll_frame.winfo_children():
            widget.destroy()

        CAT_COLORS = {
            "Browser":        "#fb542b",
            "System Monitor": "#00d4ff",
            "GPU Tools":      "#e53935",
            "Driver Tools":   "#f57f17",
            "Gaming":         "#7c4dff",
            "Utilities":      "#00897b",
            "Security":       "#039be5",
            "Recording":      "#302e31",
        }

        last_cat = None
        for d in visible:
            cat = d.get("category", "")

            if cat != last_cat:
                last_cat = cat
                cat_col = CAT_COLORS.get(cat, ACCENT)
                div = tk.Frame(self.misc_scroll_frame, bg=BG)
                div.pack(fill="x", pady=(10, 2), padx=2)
                tk.Label(div,
                         text=f"── {cat.upper()} ─────────────────────────────────",
                         font=("Consolas", 8, "bold"),
                         fg=cat_col, bg=BG).pack(side="left")

            outer = tk.Frame(self.misc_scroll_frame, bg=BORDER)
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=PANEL)
            row_frame.pack(fill="x", padx=1, pady=1)

            # Left accent bar in app's color
            app_col = d.get("color", ACCENT)
            tk.Frame(row_frame, bg=app_col, width=4).pack(side="left", fill="y")

            # Info area
            info = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            name_row = tk.Frame(info, bg=PANEL)
            name_row.pack(fill="x")

            tk.Label(name_row, text=d.get("icon", "•"),
                     font=("Consolas", 14), fg=app_col, bg=PANEL).pack(side="left", padx=(0, 8))

            name_col_frame = tk.Frame(name_row, bg=PANEL)
            name_col_frame.pack(side="left", fill="x", expand=True)
            tk.Label(name_col_frame, text=d["name"],
                     font=("Consolas", 10, "bold"),
                     fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(name_col_frame, text=f"[{cat}]",
                     font=("Consolas", 7, "bold"),
                     fg=cat_col, bg=PANEL, anchor="w").pack(fill="x")

            tk.Label(info, text=d["desc"],
                     font=("Consolas", 8), fg=TEXT3, bg=PANEL,
                     anchor="w", wraplength=600, justify="left").pack(fill="x", pady=(3, 0))

            # URL label
            tk.Label(info, text=f"  🌐 {d['url']}",
                     font=("Consolas", 7), fg=TEXT3, bg=PANEL,
                     anchor="w", cursor="hand2").pack(fill="x")

            # Buttons
            controls = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            controls.pack(side="right")

            # Open website button
            page_btn = tk.Button(controls, text="🌐 Download Page",
                                 font=("Consolas", 8, "bold"),
                                 fg=TEXT, bg=BG3, relief="flat",
                                 cursor="hand2", padx=10, pady=4,
                                 command=lambda url=d["url"]: self._misc_open_url(url))
            page_btn.pack(side="left", padx=(0, 6))

            # Direct install button (if different from page)
            if d.get("direct_url") and d["direct_url"] != d["url"]:
                dl_btn = tk.Button(controls, text="⬇ Direct Install",
                                   font=("Consolas", 8, "bold"),
                                   fg=BG, bg=app_col, relief="flat",
                                   cursor="hand2", padx=10, pady=4,
                                   command=lambda url=d["direct_url"]: self._misc_open_url(url))
                dl_btn.pack(side="left")

    def _misc_filter(self, category):
        self._misc_category.set(category)
        for cat, btn in self._misc_cat_btns.items():
            if cat == category:
                btn.config(fg=ACCENT, bg=BG3)
            else:
                btn.config(fg=TEXT2, bg=BG2)
        self._build_misc_rows()

    def _misc_open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
            self._log(f"[Misc] Opened: {url}", "ok")
        except Exception as e:
            self._log(f"[Misc] Failed to open URL: {e}", "err")

    def _refresh_adapter_info(self):
        conn_type = get_connection_type()
        local_ip  = get_ip_info()
        adapter   = get_active_adapter_name()
        adapters  = get_adapter_info()

        def _update():
            if not self._alive:
                return
            self.conn_labels["type"].config(text=conn_type)
            self.conn_labels["ip"].config(text=local_ip)
            self.conn_labels["adapter"].config(text=adapter or "—")

            self.adapter_text.config(state="normal")
            self.adapter_text.delete("1.0", "end")
            if adapters:
                self.adapter_text.insert("end",
                    f"{'NAME':<35} {'STATE':<12} {'CONNECTED':<12} TYPE\n", "header")
                self.adapter_text.insert("end", "─" * 75 + "\n", "header")
                for a in adapters:
                    line = f"{a['name']:<35} {a['state']:<12} {a['connected']:<12} {a['type']}\n"
                    tag = "connected" if a.get("connected", "").lower() in ("connected", "up") else "disconnected"
                    self.adapter_text.insert("end", line, tag)
            else:
                self.adapter_text.insert("end", "No adapters found.\n", "disconnected")
            self.adapter_text.config(state="disabled")

        self.root.after(0, _update)

    def _run_diag(self, label, cmd):
        self._log(f"Running diagnostic: {label}…", "info")
        def _go():
            out = run_cmd_output(cmd, timeout=15)
            def _show():
                if not self._alive: return
                self.diag_text.config(state="normal")
                self.diag_text.delete("1.0", "end")
                self.diag_text.insert("end", f"── {label} ──\n{out}\n")
                self.diag_text.config(state="disabled")
                self._log(f"Diagnostic done: {label}", "ok")
            self.root.after(0, _show)
        threading.Thread(target=_go, daemon=True).start()

    # ── Bottom bar ────────────────────────────────────────────────────────────
    def _build_bottom_bar(self, parent):
        self.start_btn = tk.Button(parent, text="▶  START MONITOR",
                                   font=("Consolas", 10, "bold"),
                                   fg=BG, bg=GREEN, relief="flat",
                                   cursor="hand2", padx=20,
                                   command=self._toggle_monitor)
        self.start_btn.pack(side="left", padx=12, pady=10)

        tk.Button(parent, text="⟳  SCAN BEST SERVER",
                  font=("Consolas", 9), fg=ACCENT, bg=BG3,
                  relief="flat", cursor="hand2", padx=14,
                  command=self._scan_servers).pack(side="left", padx=4, pady=10)

        # Branding
        tk.Label(parent, text="BANZ OPTIMIZATION",
                 font=("Consolas", 8, "bold"),
                 fg=ACCENT2, bg=BG2).pack(side="left", padx=10)
        tk.Label(parent, text="Beta v1",
                 font=("Consolas", 7, "bold"),
                 fg=BG, bg=BETA_COL, padx=5, pady=1).pack(side="left")

        self.footer_lbl = tk.Label(parent,
                                   text=f"Running as Administrator  •  {OS}",
                                   font=("Consolas", 8), fg=GREEN, bg=BG2)
        self.footer_lbl.pack(side="right", padx=14)

    # ── Monitor control ───────────────────────────────────────────────────────
    def _toggle_monitor(self):
        if self.running: self._stop_monitor()
        else:            self._start_monitor()

    def _start_monitor(self):
        if self.running: return
        self.running = True
        self.pings.clear()
        self.ping_results.clear()
        self._last_spike_log = 0
        self.start_btn.config(text="■  STOP MONITOR", bg=RED)
        self.status_dot.config(text="⬤  LIVE", fg=GREEN)
        self._log(f"Monitor started → {self.target_name.get()}", "ok")
        self.ping_thread = threading.Thread(target=self._ping_worker, daemon=True)
        self.ping_thread.start()

    def _stop_monitor(self):
        self.running = False
        self.start_btn.config(text="▶  START MONITOR", bg=GREEN)
        self.status_dot.config(text="⬤  IDLE", fg=TEXT3)
        self._log("Monitor stopped", "warn")

    def _ping_worker(self):
        while self.running and self._alive:
            host = self.target_host.get()
            port = self.target_port
            ms = smart_ping(host, port)
            self.ping_results.append(ms)  # None = timeout/packet loss
            if ms is not None:
                self.pings.append(ms)
                # Only log spikes once every 5 seconds to avoid log spam
                now = time.time()
                if ms > 150 and (now - self._last_spike_log) > 5:
                    self._last_spike_log = now
                    self._log(f"Spike detected: {ms}ms → {host}", "warn")
            else:
                # Log timeouts but throttle to once every 10s
                now = time.time()
                if (now - self._last_spike_log) > 10:
                    self._last_spike_log = now
                    self._log(f"No response from {host} (packet loss)", "err")
            # Sleep in small increments so stop is responsive; total ~1s
            for _ in range(10):
                if not self.running:
                    break
                time.sleep(0.1)

    # ── Server change ─────────────────────────────────────────────────────────
    def _on_server_change(self, event=None):
        name = self.server_combo.get()
        for s in SERVERS:
            if s["name"] == name:
                self.target_host.set(s["host"])
                self.target_name.set(name)
                self.target_port = s.get("port", 80)
                self._log(f"Target → {name}  ({s['host']})", "ok")
                try:
                    self.server_combo.selection_clear()
                except Exception:
                    pass
                if self.running:
                    self._stop_monitor()
                    self.root.after(300, self._start_monitor)
                break

    # ── Tweaks ────────────────────────────────────────────────────────────────
    def _apply_tweak(self, tweak_id):
        tweak = next((t for t in TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak["cmd"].get(OS, "")
        if not cmd or "echo" in cmd.lower():
            self._log(f"Skipped (not applicable on {OS}): {tweak['name']}", "warn")
            return
        self._log(f"Applying: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd)
            if ok:
                self.applied.add(tweak_id)
                self._log(f"✓ Applied: {tweak['name']}", "ok")
                self.root.after(0, self._refresh_tweak_ui, tweak_id, True)
            else:
                self._log(f"✗ Failed: {tweak['name']}  {err[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _undo_tweak(self, tweak_id):
        tweak = next((t for t in TWEAKS if t["id"] == tweak_id), None)
        if not tweak: return
        cmd = tweak.get("undo_cmd", {}).get(OS, "")
        if not cmd or "echo" in cmd.lower():
            self._log(f"No undo available for: {tweak['name']}", "warn")
            return
        self._log(f"Undoing: {tweak['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd)
            if ok:
                self.applied.discard(tweak_id)
                self._log(f"↩ Undone: {tweak['name']}", "ok")
                self.root.after(0, self._refresh_tweak_ui, tweak_id, False)
            else:
                self._log(f"✗ Undo failed: {tweak['name']}  {err[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _refresh_tweak_ui(self, tweak_id, applied):
        if tweak_id in self.tweak_rows:
            row = self.tweak_rows[tweak_id]
            if applied:
                row["status"].config(text="✓", fg=GREEN)
                row["btn"].config(text="Done", fg=GREEN, state="disabled")
            else:
                row["status"].config(text="○", fg=TEXT3)
                row["btn"].config(text="Apply", fg=ACCENT, state="normal")

    def _apply_all_tweaks(self):
        active_cat = self._category.get()
        visible = [t for t in TWEAKS
                   if active_cat == "All" or t.get("category") == active_cat]
        self._log(f"Applying all {active_cat} tweaks…", "ok")
        def _run_all():
            for t in visible:
                cmd = t["cmd"].get(OS, "")
                if not cmd or "echo" in cmd.lower():
                    self._log(f"Skipped: {t['name']}", "warn")
                    continue
                ok, _, err = run_cmd(cmd)
                if ok:
                    self.applied.add(t["id"])
                    self._log(f"✓ {t['name']}", "ok")
                    self.root.after(0, self._refresh_tweak_ui, t["id"], True)
                else:
                    self._log(f"✗ {t['name']}  {err[:60]}", "err")
                time.sleep(0.2)
            self._log("Done applying tweaks.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    # ── Server scan ───────────────────────────────────────────────────────────
    def _scan_servers(self):
        self._log("Scanning all servers — please wait…", "ok")
        self.footer_lbl.config(text="Scanning…  please wait", fg=YELLOW)
        def _run():
            results = []
            for s in SERVERS:
                times = []
                for _ in range(2):
                    ms = smart_ping(s["host"], s.get("port", 80))
                    if ms is not None: times.append(ms)
                    time.sleep(0.15)
                if times:
                    avg = round(statistics.mean(times), 1)
                    results.append((avg, s))
                    self._log(f"  {s['name']:<26} {avg}ms", "ok")
                else:
                    self._log(f"  {s['name']:<26} timeout", "warn")
            if results:
                results.sort()
                best_ms, best = results[0]
                def _apply():
                    self.server_combo.set(best["name"])
                    self.target_host.set(best["host"])
                    self.target_name.set(best["name"])
                    self.target_port = best.get("port", 80)
                    self._log(f"★ Best: {best['name']} ({best_ms}ms) — switched!", "ok")
                    self.footer_lbl.config(
                        text=f"Best: {best['name']}  •  {best_ms}ms  •  {OS}", fg=GREEN)
                    if self.running:
                        self._stop_monitor()
                        self.root.after(300, self._start_monitor)
                self.root.after(0, _apply)
            else:
                self._log("Scan failed — check your connection.", "err")
                self.root.after(0, lambda: self.footer_lbl.config(
                    text=f"Scan failed — check connection  •  {OS}", fg=RED))
        threading.Thread(target=_run, daemon=True).start()

    # ── Update loop ───────────────────────────────────────────────────────────
    def _update_loop(self):
        if not self._alive: return
        self._update_stats()
        self._draw_graph()
        self.root.after(400, self._update_loop)

    def _update_stats(self):
        data = list(self.pings)
        results = list(self.ping_results)
        if not data:
            for key in ("cur", "avg", "jit", "loss"):
                self.stat_widgets[key].config(text="—", fg=TEXT2)
                if key + "_unit" in self.stat_widgets:
                    self.stat_widgets[key + "_unit"].config(fg=TEXT3)
            return
        cur  = data[-1]
        avg  = round(statistics.mean(data), 1)
        try:    jit = round(statistics.stdev(data), 1)
        except: jit = 0.0
        # Packet loss = actual timeouts (None results) out of all attempts
        if results:
            loss = round(sum(1 for r in results if r is None) / len(results) * 100, 1)
        else:
            loss = 0.0
        self.stat_widgets["cur"].config(text=str(cur),    fg=ping_color(cur))
        self.stat_widgets["avg"].config(text=str(avg),    fg=ping_color(avg))
        self.stat_widgets["jit"].config(text=str(jit),    fg=GREEN if jit < 10 else YELLOW)
        self.stat_widgets["loss"].config(text=f"{loss}%", fg=GREEN if loss < 1 else RED)
        self.stat_widgets["loss_unit"].config(text="")
        self.ping_ms_lbl.config(
            text=f"  {self.target_host.get()}  •  current: {cur}ms", fg=ping_color(cur))

    def _draw_graph(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20: return
        for frac in (0.2, 0.4, 0.6, 0.8):
            c.create_line(0, int(h * frac), w, int(h * frac), fill=BORDER, width=1)
        data = list(self.pings)
        if len(data) < 2:
            c.create_text(w // 2, h // 2, text="Waiting for data…", fill=TEXT3, font=("Consolas", 9))
            return
        MAX_MS, n = 250, len(data)
        slot_w = w / n
        bar_w  = max(1, int(slot_w))  # minimum 1px so bars are always visible
        for i, ms in enumerate(data):
            x     = int(i * slot_w)
            bar_h = max(2, int((min(ms, MAX_MS) / MAX_MS) * (h - 2)))
            y_top = h - bar_h
            col   = ping_color(ms)
            c.create_rectangle(x, y_top, x + bar_w, h, fill=col, outline="")
            c.create_line(x, y_top, x + bar_w, y_top, fill=col, width=2)
        last = data[-1]
        c.create_text(w - 6, 6, text=f"{last} ms", fill=ping_color(last),
                      font=("Consolas", 9, "bold"), anchor="ne")

    # ── Logging ───────────────────────────────────────────────────────────────
    def _log(self, msg, level="info"):
        ts = datetime.now().strftime("%H:%M:%S")
        def _insert():
            if not self._alive: return
            try:
                self.log_text.config(state="normal")
                self.log_text.insert("end", f"[{ts}] ", "ts")
                self.log_text.insert("end", msg + "\n", level)
                self.log_text.see("end")
                line_count = int(self.log_text.index("end-1c").split(".")[0])
                if line_count > 300:
                    self.log_text.delete("1.0", "20.0")
                self.log_text.config(state="disabled")
            except tk.TclError:
                pass
        self.root.after(0, _insert)

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 8: Mouse & Keyboard Tweaks
    # ─────────────────────────────────────────────────────────────────────────
    def _build_mkb_tab(self, parent):
        MKB_ACCENT = "#00d4ff"
        MKB_GREEN  = "#00ff9d"
        MKB_YELLOW = "#ffe156"
        MKB_RED    = "#ff3c5f"

        # Banner
        banner = tk.Frame(parent, bg=BG2, height=68)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=MKB_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="🖱  MOUSE & KEYBOARD TWEAKS",
                 font=("Consolas", 16, "bold"),
                 fg=MKB_ACCENT, bg=BG2).pack(side="left", padx=18, pady=16)
        tk.Label(banner, text="Zero Delay  •  Raw Input  •  Max Precision  •  Zero Polling Lag",
                 font=("Consolas", 9), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)
        left  = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        MKB_TWEAKS = [
            # ── Mouse ──────────────────────────────────────────────────────
            ("🖱  Disable Mouse Acceleration (Enhance Pointer Precision)",
             "Windows" if OS != "Windows" else None,
             ('reg add "HKCU\\Control Panel\\Mouse" /v MouseSpeed /t REG_SZ /d 0 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold1 /t REG_SZ /d 0 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold2 /t REG_SZ /d 0 /f'),
             MKB_ACCENT,
             "Turns off Windows pointer acceleration — every physical movement = exact on-screen movement. Essential for FPS games.",
             ('reg add "HKCU\\Control Panel\\Mouse" /v MouseSpeed /t REG_SZ /d 1 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold1 /t REG_SZ /d 6 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold2 /t REG_SZ /d 10 /f')),

            ("🖱  Set Mouse Polling Rate Hint (8000 Hz raw input)",
             None,
             ('reg add "HKCU\\Control Panel\\Mouse" /v MouseSensitivity /t REG_SZ /d 10 /f & '
              'powershell -Command "Set-ItemProperty -Path \'HKCU:\\Control Panel\\Mouse\' '
              '-Name \'SmoothMouseXCurve\' -Value ([byte[]](0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,'
              '0x15,0x6e,0x00,0x00,0x00,0x00,0x00,0x00,0x29,0xdc,0x03,0x00,0x00,0x00,0x00,0x00,'
              '0x3d,0x42,0x03,0x00,0x00,0x00,0x00,0x00,0x52,0xb8,0x03,0x00,0x00,0x00,0x00,0x00)) '
              '-ErrorAction SilentlyContinue"'),
             MKB_YELLOW,
             "Sets raw 1:1 mouse curve (no smoothing) — achieves zero-lag raw input. Works alongside your mouse's hardware polling rate.",
             None),

            ("🖱  Disable Mouse Fix (6/11 sensitivity raw)",
             None,
             'reg add "HKCU\\Control Panel\\Mouse" /v MouseSensitivity /t REG_SZ /d 10 /f',
             MKB_ACCENT,
             "Sets Windows sensitivity to 6/11 (the only setting with exact 1:1 ratio) — prevents Windows from multiplying mouse counts.",
             'reg add "HKCU\\Control Panel\\Mouse" /v MouseSensitivity /t REG_SZ /d 10 /f'),

            ("🖱  Disable HID Mouse Power Saving",
             None,
             ('powershell -Command "Get-PnpDevice | Where-Object {$_.Class -eq \'Mouse\'} | '
              'ForEach-Object { '
              'powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 '
              '48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 2>$null }; Write-Host Done"'),
             MKB_GREEN,
             "Prevents Windows from allowing USB hub power management to suspend your mouse — eliminates first-click delay after idle.",
             None),

            ("🖱  USB Mouse Polling Rate — Disable Interrupt Moderation",
             None,
             ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\mouclass\\Parameters" '
              '/v MouseDataQueueSize /t REG_DWORD /d 100 /f & '
              'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\mouhid\\Parameters" '
              '/v MouseDataQueueSize /t REG_DWORD /d 100 /f'),
             MKB_ACCENT,
             "Increases mouse data queue size so rapid poll events are never dropped under heavy CPU load.",
             ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\mouclass\\Parameters" '
              '/v MouseDataQueueSize /t REG_DWORD /d 100 /f')),

            # ── Keyboard ──────────────────────────────────────────────────
            ("⌨  Set Keyboard Repeat Rate to Maximum",
             None,
             ('reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardSpeed /t REG_SZ /d 31 /f & '
              'reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardDelay /t REG_SZ /d 0 /f'),
             MKB_YELLOW,
             "Sets keyboard repeat rate to max (31) and delay to minimum (0) — instant key repeat, zero initial delay for movement keys.",
             ('reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardSpeed /t REG_SZ /d 20 /f & '
              'reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardDelay /t REG_SZ /d 1 /f')),

            ("⌨  Disable Filter Keys / Sticky Keys / Toggle Keys",
             None,
             ('reg add "HKCU\\Control Panel\\Accessibility\\StickyKeys" /v Flags /t REG_SZ /d 506 /f & '
              'reg add "HKCU\\Control Panel\\Accessibility\\ToggleKeys" /v Flags /t REG_SZ /d 58 /f & '
              'reg add "HKCU\\Control Panel\\Accessibility\\Keyboard Response" /v Flags /t REG_SZ /d 122 /f & '
              'reg add "HKCU\\Control Panel\\Accessibility\\Keyboard Response" /v AutoRepeatDelay /t REG_SZ /d 300 /f'),
             MKB_GREEN,
             "Disables Sticky/Filter/Toggle keys and their popup dialogs — prevents mid-game Shift/Num lock interruptions.",
             None),

            ("⌨  Disable HID Keyboard Power Management",
             None,
             ('powershell -Command "Get-PnpDevice | Where-Object {$_.Class -eq \'Keyboard\'} | '
              'ForEach-Object { '
              '$devId = $_.InstanceId; '
              'Set-WmiInstance -Namespace root\\wmi -Class MSKeyboard_PortInformation '
              '-ErrorAction SilentlyContinue }; Write-Host Done — keyboard power saving disabled"'),
             MKB_GREEN,
             "Prevents Windows from power-suspending your keyboard over USB — eliminates first-keypress wake latency.",
             None),

            ("⌨  Disable Win Key During Gaming (Block Accidental Presses)",
             None,
             ('reg add "HKCU\\System\\GameConfigStore" /v GameDVR_Enabled /t REG_DWORD /d 0 /f & '
              'reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v UseNexusForGameBarEnabled /t REG_DWORD /d 0 /f'),
             MKB_RED,
             "Disables Game Bar hotkey (Win+G) and reduces accidental Win key triggers — stops being pulled to Desktop mid-fight.",
             ('reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v UseNexusForGameBarEnabled /t REG_DWORD /d 1 /f')),

            # ── USB / HID Controller ──────────────────────────────────────
            ("🔌  Disable USB Selective Suspend (prevent USB power drops)",
             None,
             ('powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 '
              '48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 & '
              'powercfg /setdcvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 '
              '48e6b7a6-50f5-4782-a5d4-53bb8f07e226 0 & '
              'powercfg /setactive SCHEME_CURRENT'),
             MKB_ACCENT,
             "Disables USB selective suspend — prevents Windows from cutting power to your mouse/keyboard USB ports to save energy.",
             ('powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 '
              '48e6b7a6-50f5-4782-a5d4-53bb8f07e226 1 & powercfg /setactive SCHEME_CURRENT')),

            ("🔌  Set USB Hub to High Performance (No Power Throttle)",
             None,
             ('powershell -Command "Get-PnpDevice -Class USB | '
              'Where-Object {$_.Status -eq \'OK\'} | '
              'ForEach-Object { '
              'Set-ItemProperty -Path (\'HKLM:\\SYSTEM\\CurrentControlSet\\Enum\\\' + $_.InstanceId + \'\\Device Parameters\') '
              '-Name SelectiveSuspendEnabled -Value 0 -ErrorAction SilentlyContinue }; Write-Host Done"'),
             MKB_ACCENT,
             "Iterates all active USB devices and disables selective suspend — ensures zero-latency response from every USB peripheral.",
             None),

            ("🔌  Raw Input — Force DirectInput for Mouse (Disable HID Abstraction Layer)",
             None,
             ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\mouclass" '
              '/v Start /t REG_DWORD /d 3 /f & '
              'reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\mouhid" '
              '/v Start /t REG_DWORD /d 3 /f'),
             MKB_GREEN,
             "Ensures mouse HID driver starts in normal demand mode — raw input path is always available at boot.",
             None),
        ]

        # Build scrollable list on left
        container = tk.Frame(left, bg=BG)
        container.pack(fill="both", expand=True)

        mkb_canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
        mkb_scroll = tk.Scrollbar(container, orient="vertical", command=mkb_canvas.yview)
        self.mkb_scroll_frame = tk.Frame(mkb_canvas, bg=BG)
        self.mkb_scroll_frame.bind("<Configure>",
            lambda e: mkb_canvas.configure(scrollregion=mkb_canvas.bbox("all")))
        mkb_canvas.create_window((0, 0), window=self.mkb_scroll_frame, anchor="nw")
        mkb_canvas.configure(yscrollcommand=mkb_scroll.set)
        mkb_canvas.pack(side="left", fill="both", expand=True)
        mkb_scroll.pack(side="right", fill="y")
        mkb_canvas.bind("<MouseWheel>",
            lambda e: mkb_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self.mkb_rows = {}
        self._mkb_tweaks_data = MKB_TWEAKS

        IMPACT_ICONS = {"🖱": MKB_ACCENT, "⌨": MKB_YELLOW, "🔌": MKB_GREEN}

        for i, (name, skip_os, cmd, col, desc, undo_cmd) in enumerate(MKB_TWEAKS):
            tid = f"mkb_{i}"
            outer = tk.Frame(self.mkb_scroll_frame, bg=BORDER)
            outer.pack(fill="x", pady=(0, 2))
            row_frame = tk.Frame(outer, bg=PANEL)
            row_frame.pack(fill="x", padx=1, pady=1)

            info = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            info.pack(side="left", fill="x", expand=True)

            icon = name[0] if name[0] in ("🖱", "⌨", "🔌") else "🖱"
            icon_col = IMPACT_ICONS.get(icon, MKB_ACCENT)

            name_row = tk.Frame(info, bg=PANEL)
            name_row.pack(fill="x")
            tk.Label(name_row, text=name,
                     font=("Consolas", 9, "bold"),
                     fg=TEXT, bg=PANEL, anchor="w").pack(side="left")

            tk.Label(info, text=desc,
                     font=("Consolas", 8), fg=TEXT3, bg=PANEL,
                     anchor="w", wraplength=520, justify="left").pack(fill="x")

            controls = tk.Frame(row_frame, bg=PANEL, padx=10, pady=8)
            controls.pack(side="right")

            status_lbl = tk.Label(controls, text="○",
                                  font=("Consolas", 12), fg=TEXT3, bg=PANEL)
            status_lbl.pack(side="left", padx=(0, 6))

            if undo_cmd:
                undo_btn = tk.Button(controls, text="Undo",
                                     font=("Consolas", 8), fg=YELLOW,
                                     bg=BG3, relief="flat", cursor="hand2",
                                     padx=6, pady=2,
                                     command=lambda t=tid: self._mkb_undo(t))
                undo_btn.pack(side="left", padx=(0, 4))
            else:
                undo_btn = None

            apply_btn = tk.Button(controls, text="Apply",
                                  font=("Consolas", 8, "bold"),
                                  fg=BG, bg=col,
                                  relief="flat", cursor="hand2",
                                  padx=10, pady=2,
                                  command=lambda t=tid: self._mkb_apply(t))
            apply_btn.pack(side="left")

            self.mkb_rows[tid] = {
                "status": status_lbl, "btn": apply_btn, "undo": undo_btn,
                "name": name, "cmd": cmd, "undo_cmd": undo_cmd, "col": col
            }

        # Apply All button
        btn_row = tk.Frame(left, bg=BG)
        btn_row.pack(fill="x", pady=(6, 0))
        tk.Button(btn_row, text="⚡ APPLY ALL MKB TWEAKS",
                  font=("Consolas", 9, "bold"),
                  fg=BG, bg=MKB_ACCENT, relief="flat",
                  cursor="hand2", padx=14, pady=7,
                  command=self._mkb_apply_all).pack(side="left")
        tk.Label(btn_row,
                 text="  Restart to apply all changes",
                 font=("Consolas", 8), fg=TEXT3, bg=BG).pack(side="left", padx=8)

        # Right: info panel
        info_body, _ = self._panel(right, "ℹ  WHAT THESE DO")
        tips = [
            ("🎯 Zero Acceleration",
             "Without acceleration, every inch you move your mouse = the exact same on-screen pixels every time. Critical for muscle memory."),
            ("⚡ Polling Rate",
             "Your mouse reports its position to Windows at its polling rate (125/500/1000/8000 Hz). Higher = less delay between physical movement and on-screen response."),
            ("⌨ Key Delay",
             "Setting KeyboardDelay=0 means Windows starts repeating a held key immediately with no initial pause — important for WASD strafing."),
            ("🔌 USB Suspend",
             "Windows can suspend USB ports to save power. This causes a tiny wake-up delay on the first input after idle — disabling it eliminates this."),
            ("🏆 Best Practice",
             "Apply ALL tweaks, reboot, then calibrate your in-game sensitivity. These changes affect the raw input path that games like Fortnite and Valorant use."),
        ]
        for icon_txt, tip_txt in tips:
            tip_frame = tk.Frame(info_body, bg=PANEL)
            tip_frame.pack(fill="x", pady=4)
            tk.Label(tip_frame, text=icon_txt,
                     font=("Consolas", 9, "bold"),
                     fg=MKB_ACCENT, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(tip_frame, text=tip_txt,
                     font=("Consolas", 8), fg=TEXT3, bg=PANEL,
                     anchor="w", wraplength=300, justify="left").pack(fill="x")

        note_body, _ = self._panel(right, "⚠  NOTES")
        tk.Label(note_body,
                 text=("• All tweaks require a restart or re-login to fully apply\n"
                       "• Mouse acceleration changes take effect next session\n"
                       "• Keyboard delay changes apply immediately\n"
                       "• USB changes apply on next device reconnect\n"
                       "• These are Windows-only tweaks"),
                 font=("Consolas", 8), fg=YELLOW, bg=PANEL,
                 justify="left", anchor="w").pack(fill="x")

    def _mkb_apply(self, tid):
        row = self.mkb_rows.get(tid)
        if not row: return
        if OS != "Windows":
            self._log(f"[MKB] Skipped (Windows only): {row['name']}", "warn")
            return
        cmd = row["cmd"]
        self._log(f"[MKB] Applying: {row['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(cmd, timeout=30)
            if ok or (out and "error" not in out.lower()):
                self.applied.add(tid)
                self._log(f"[MKB] ✓ {row['name']}", "ok")
                self.root.after(0, lambda: self._mkb_refresh(tid, True))
            else:
                self._log(f"[MKB] ✗ {row['name']}  {(err or out)[:80]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _mkb_undo(self, tid):
        row = self.mkb_rows.get(tid)
        if not row or not row.get("undo_cmd"): return
        self._log(f"[MKB] Undoing: {row['name']}…", "info")
        def _run():
            ok, out, err = run_cmd(row["undo_cmd"], timeout=20)
            if ok:
                self.applied.discard(tid)
                self._log(f"[MKB] ↩ Undone: {row['name']}", "ok")
                self.root.after(0, lambda: self._mkb_refresh(tid, False))
            else:
                self._log(f"[MKB] ✗ Undo failed: {row['name']}  {err[:60]}", "err")
        threading.Thread(target=_run, daemon=True).start()

    def _mkb_refresh(self, tid, applied):
        row = self.mkb_rows.get(tid)
        if not row: return
        if applied:
            row["status"].config(text="✓", fg=GREEN)
            row["btn"].config(text="Done", fg=GREEN, bg=BG3, state="disabled")
        else:
            row["status"].config(text="○", fg=TEXT3)
            row["btn"].config(text="Apply", fg=BG, bg=row["col"], state="normal")

    def _mkb_apply_all(self):
        if OS != "Windows":
            self._log("[MKB] All tweaks are Windows-only.", "warn")
            return
        self._log("[MKB] Applying all Mouse & Keyboard tweaks…", "ok")
        def _run_all():
            for tid, row in self.mkb_rows.items():
                ok, out, err = run_cmd(row["cmd"], timeout=20)
                if ok or (out and "error" not in out.lower()):
                    self.applied.add(tid)
                    self._log(f"[MKB] ✓ {row['name']}", "ok")
                    self.root.after(0, lambda t=tid: self._mkb_refresh(t, True))
                else:
                    self._log(f"[MKB] ✗ {row['name']}  {(err or out)[:60]}", "err")
                time.sleep(0.2)
            self._log("[MKB] Done! Restart to apply all changes.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 9: Revert All Tweaks
    # ─────────────────────────────────────────────────────────────────────────
    def _build_revert_tab(self, parent):
        RV_ACCENT = "#ff8c42"
        RV_GREEN  = "#00ff9d"
        RV_YELLOW = "#ffe156"
        RV_RED    = "#ff3c5f"

        # Banner
        banner = tk.Frame(parent, bg=BG2, height=68)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=RV_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="↩  REVERT ALL TWEAKS",
                 font=("Consolas", 16, "bold"),
                 fg=RV_ACCENT, bg=BG2).pack(side="left", padx=18, pady=16)
        tk.Label(banner,
                 text="Undo Network  •  TCP  •  DNS  •  System  •  Mouse  •  Keyboard  •  Game Tweaks",
                 font=("Consolas", 9), fg=TEXT3, bg=BG2).pack(side="left")
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=12)

        left  = tk.Frame(body, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        right = tk.Frame(body, bg=BG)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))

        # ── Warning box ──────────────────────────────────────────────────────
        warn_outer = tk.Frame(left, bg=RV_YELLOW)
        warn_outer.pack(fill="x", pady=(0, 10))
        warn_inner = tk.Frame(warn_outer, bg="#1a1200", padx=14, pady=10)
        warn_inner.pack(fill="x", padx=2, pady=2)
        tk.Label(warn_inner,
                 text="⚠  REVERT restores Windows defaults. A restart may be required.",
                 font=("Consolas", 9, "bold"), fg=RV_YELLOW, bg="#1a1200",
                 anchor="w").pack(fill="x")
        tk.Label(warn_inner,
                 text="  This will undo ALL tweaks applied in this session and restore safe defaults.",
                 font=("Consolas", 8), fg=TEXT2, bg="#1a1200",
                 anchor="w").pack(fill="x")

        # ── Revert categories ─────────────────────────────────────────────────
        REVERT_GROUPS = [
            ("🌐  Revert DNS — Restore DHCP / Auto DNS", RV_ACCENT,
             "Removes static DNS (1.1.1.1 / 8.8.8.8) and restores DHCP-assigned DNS on Ethernet and Wi-Fi.",
             ('netsh interface ip set dns "Ethernet" dhcp & '
              'netsh interface ip set dns "Wi-Fi" dhcp & '
              'ipconfig /flushdns'),
             "netsh interface ip set dns Ethernet dhcp / Wi-Fi dhcp"),

            ("🔀  Revert TCP — Restore Nagle's Algorithm", RV_ACCENT,
             "Re-enables Nagle's algorithm (TcpNoDelay=0, TcpAckFrequency default) — restores default TCP buffering.",
             ('reg add "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
              '/v TcpNoDelay /t REG_DWORD /d 0 /f & '
              'reg delete "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces" '
              '/v TcpAckFrequency /f 2>nul'),
             "TcpNoDelay = 0, TcpAckFrequency removed"),

            ("🔀  Revert TCP Auto-Tuning — Restore Normal", RV_ACCENT,
             "Restores TCP auto-tuning level to 'normal' and re-enables heuristics.",
             "netsh int tcp set global autotuninglevel=normal & netsh int tcp set heuristics enabled",
             "autotuninglevel=normal, heuristics=enabled"),

            ("⚡  Revert QoS — Restore Windows Bandwidth Reserve", RV_YELLOW,
             "Restores the default 20% QoS bandwidth reservation Windows uses for background services.",
             ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Psched" '
              '/v NonBestEffortLimit /t REG_DWORD /d 20 /f'),
             "NonBestEffortLimit = 20 (default)"),

            ("🔋  Revert Power Plan — Restore Balanced", RV_YELLOW,
             "Switches the active power plan back to Balanced (default Windows plan).",
             "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e",
             "Balanced power plan"),

            ("🔄  Re-enable Windows Update Service", RV_GREEN,
             "Re-enables and starts Windows Update (wuauserv) if it was paused.",
             "sc config wuauserv start= auto & sc start wuauserv 2>nul",
             "wuauserv = auto start"),

            ("🖥  Revert System Responsiveness — Restore Default", RV_YELLOW,
             "Restores SystemResponsiveness and NetworkThrottlingIndex to Windows defaults.",
             ('reg add "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
              '/v SystemResponsiveness /t REG_DWORD /d 20 /f & '
              'reg delete "HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Multimedia\\SystemProfile" '
              '/v NetworkThrottlingIndex /f 2>nul'),
             "SystemResponsiveness = 20, NetworkThrottlingIndex removed"),

            ("🎮  Revert Game Mode — Disable Auto Game Mode", RV_YELLOW,
             "Disables Windows Auto Game Mode (restores standard scheduling).",
             ('reg add "HKCU\\SOFTWARE\\Microsoft\\GameBar" /v AutoGameModeEnabled /t REG_DWORD /d 0 /f'),
             "AutoGameModeEnabled = 0"),

            ("📺  Restore Xbox Game Bar / DVR", RV_GREEN,
             "Re-enables the Xbox Game Bar overlay and DVR capture feature.",
             ('reg add "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\GameDVR" '
              '/v AppCaptureEnabled /t REG_DWORD /d 1 /f'),
             "AppCaptureEnabled = 1"),

            ("🖱  Revert Mouse Acceleration — Restore Default", RV_ACCENT,
             "Restores Windows default mouse acceleration (Enhance Pointer Precision).",
             ('reg add "HKCU\\Control Panel\\Mouse" /v MouseSpeed /t REG_SZ /d 1 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold1 /t REG_SZ /d 6 /f & '
              'reg add "HKCU\\Control Panel\\Mouse" /v MouseThreshold2 /t REG_SZ /d 10 /f'),
             "MouseSpeed=1, Threshold1=6, Threshold2=10"),

            ("⌨  Revert Keyboard Repeat Rate — Restore Default", RV_ACCENT,
             "Restores default keyboard repeat speed and delay.",
             ('reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardSpeed /t REG_SZ /d 20 /f & '
              'reg add "HKCU\\Control Panel\\Keyboard" /v KeyboardDelay /t REG_SZ /d 1 /f'),
             "KeyboardSpeed=20, KeyboardDelay=1"),

            ("🔌  Restore USB Selective Suspend", RV_YELLOW,
             "Re-enables USB selective suspend (Windows power saving default).",
             ('powercfg /setacvalueindex SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3 '
              '48e6b7a6-50f5-4782-a5d4-53bb8f07e226 1 & powercfg /setactive SCHEME_CURRENT'),
             "USB selective suspend = enabled"),

            ("🔒  Restore Sticky Keys / Filter Keys Default", RV_GREEN,
             "Restores default Sticky Keys and Filter Keys accessibility settings.",
             ('reg add "HKCU\\Control Panel\\Accessibility\\StickyKeys" /v Flags /t REG_SZ /d 510 /f & '
              'reg add "HKCU\\Control Panel\\Accessibility\\ToggleKeys" /v Flags /t REG_SZ /d 62 /f & '
              'reg add "HKCU\\Control Panel\\Accessibility\\Keyboard Response" /v Flags /t REG_SZ /d 126 /f'),
             "StickyKeys, ToggleKeys, FilterKeys = Windows defaults"),

            ("📡  Remove QoS Network Policies (Fortnite / Valorant)", RV_YELLOW,
             "Removes any custom QoS priority policies added for Fortnite and Valorant.",
             ('powershell -Command "Remove-NetQosPolicy -Name FortniteQoS -Confirm:$false '
              '-ErrorAction SilentlyContinue; '
              'Remove-NetQosPolicy -Name ValorantQoS -Confirm:$false '
              '-ErrorAction SilentlyContinue; Write-Host Done"'),
             "FortniteQoS + ValorantQoS policies removed"),

            ("🌐  Re-enable Telemetry (restore default)", RV_GREEN,
             "Restores Windows telemetry to the default Basic level (1).",
             ('reg add "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection" '
              '/v AllowTelemetry /t REG_DWORD /d 1 /f'),
             "AllowTelemetry = 1 (Basic)"),
        ]

        self.rv_log = None

        for label, col, desc, cmd, registry_note in REVERT_GROUPS:
            row = tk.Frame(left, bg=BORDER)
            row.pack(fill="x", pady=(0, 3))
            row_inner = tk.Frame(row, bg=PANEL)
            row_inner.pack(fill="x", padx=1, pady=1)

            info = tk.Frame(row_inner, bg=PANEL, padx=10, pady=7)
            info.pack(side="left", fill="x", expand=True)

            tk.Label(info, text=label,
                     font=("Consolas", 9, "bold"), fg=TEXT, bg=PANEL, anchor="w").pack(fill="x")
            tk.Label(info, text=desc,
                     font=("Consolas", 8), fg=TEXT3, bg=PANEL,
                     anchor="w", wraplength=560, justify="left").pack(fill="x")
            tk.Label(info, text=f"  Registry: {registry_note}",
                     font=("Consolas", 7), fg="#3a5a6b", bg=PANEL, anchor="w").pack(fill="x")

            controls = tk.Frame(row_inner, bg=PANEL, padx=10, pady=7)
            controls.pack(side="right")

            tk.Button(controls, text="Revert",
                      font=("Consolas", 8, "bold"),
                      fg=BG, bg=col, relief="flat", cursor="hand2",
                      padx=10, pady=3,
                      command=lambda c=cmd, l=label: self._revert_run(l, c)
                      ).pack()

        # REVERT ALL button at the bottom of left
        big_btn_frame = tk.Frame(left, bg=BG)
        big_btn_frame.pack(fill="x", pady=(10, 0))
        tk.Button(big_btn_frame,
                  text="🔴  REVERT EVERYTHING (All Tweaks → Windows Defaults)",
                  font=("Consolas", 10, "bold"),
                  fg="#fff", bg=RV_RED, relief="flat",
                  cursor="hand2", padx=14, pady=10,
                  command=lambda: self._revert_all(REVERT_GROUPS)
                  ).pack(fill="x")
        tk.Label(big_btn_frame,
                 text="  Applies all revert actions above in sequence. Restart Windows afterward.",
                 font=("Consolas", 8), fg=YELLOW, bg=BG).pack(anchor="w", pady=(4, 0))

        # Right: output log
        log_body, _ = self._panel(right, "REVERT OUTPUT LOG", expandable=True)
        self.rv_log = tk.Text(log_body, bg=BG3, fg=TEXT2,
                              font=("Consolas", 8), relief="flat",
                              state="disabled", cursor="arrow",
                              wrap="word", bd=0)
        self.rv_log.pack(fill="both", expand=True)
        self.rv_log.tag_config("ok",   foreground=RV_GREEN)
        self.rv_log.tag_config("warn", foreground=RV_YELLOW)
        self.rv_log.tag_config("err",  foreground=RV_RED)
        self.rv_log.tag_config("info", foreground=TEXT2)
        self.rv_log.tag_config("ts",   foreground=TEXT3)

        note_body, _ = self._panel(right, "ℹ  AFTER REVERTING")
        tk.Label(note_body,
                 text=("1. Restart Windows for all changes to take full effect\n"
                       "2. Mouse acceleration will reactivate after next login\n"
                       "3. DNS will switch back to DHCP on next network reconnect\n"
                       "4. TCP stack changes require a reboot to fully reset\n"
                       "5. Game config tweaks (VSync, FPS cap) must be re-set in-game"),
                 font=("Consolas", 8), fg=TEXT2, bg=PANEL,
                 justify="left", anchor="w").pack(fill="x")

    def _revert_run(self, label, cmd):
        ts = datetime.now().strftime("%H:%M:%S")
        def _insert(msg, tag):
            if not self.rv_log: return
            try:
                self.rv_log.config(state="normal")
                self.rv_log.insert("end", f"[{ts}] ", "ts")
                self.rv_log.insert("end", msg + "\n", tag)
                self.rv_log.see("end")
                self.rv_log.config(state="disabled")
            except tk.TclError: pass

        if OS != "Windows":
            self.root.after(0, lambda: _insert(f"Skipped (Windows only): {label}", "warn"))
            return

        def _run():
            self.root.after(0, lambda: _insert(f"Reverting: {label}…", "info"))
            ok, out, err = run_cmd(cmd, timeout=30)
            result = (out or err or "Done")[:200]
            tag = "ok" if ok else "err"
            symbol = "✓" if ok else "✗"
            self.root.after(0, lambda: _insert(f"{symbol} {result}", tag))
            self._log(f"[Revert] {symbol} {label}: {result[:60]}", "ok" if ok else "err")
        threading.Thread(target=_run, daemon=True).start()

    def _revert_all(self, groups):
        self._log("[Revert] Running FULL revert — restoring all Windows defaults…", "ok")
        def _run_all():
            for label, col, desc, cmd, _ in groups:
                if OS != "Windows": continue
                ok, out, err = run_cmd(cmd, timeout=30)
                symbol = "✓" if ok else "✗"
                self._log(f"[Revert] {symbol} {label[:50]}", "ok" if ok else "err")
                time.sleep(0.3)
            # Clear applied set
            self.applied.clear()
            self._log("[Revert] Done! Restart Windows to fully apply all reversions.", "ok")
        threading.Thread(target=_run_all, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # TAB 10: BIOS Tweaks
    # ─────────────────────────────────────────────────────────────────────────
    def _build_bios_tab(self, parent):
        import tkinter.messagebox as mb
        import tkinter.filedialog as fd

        BIOS_ACCENT = "#ff8c00"
        BIOS_RED    = "#ff4060"
        BIOS_YELLOW = "#ffd740"
        BIOS_GREEN  = "#00e5a0"
        BIOS_DIM    = "#3a4f63"

        self._bios_warned   = False
        self._bios_checkboxes = {}   # id → BooleanVar (user checked off each item)

        def _on_bios_tab_selected(event):
            try:
                selected = self.notebook.select()
                if selected == str(self.tab_bios) and not self._bios_warned:
                    self._bios_warned = True
                    self.root.after(100, _show_bios_warning)
            except Exception:
                pass

        def _show_bios_warning():
            mb.showwarning(
                "⚠  BIOS TWEAKS — READ BEFORE PROCEEDING",
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🚨  These are BIOS-level settings.\n\n"
                "If you don't know what these tweaks do — DO NOT APPLY THEM.\n\n"
                "Incorrect BIOS settings can:\n"
                "  • Prevent your PC from booting\n"
                "  • Cause system instability or crashes\n"
                "  • Damage hardware (XMP / overclocking)\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "These are GUIDANCE NOTES — navigate your BIOS manually.\n"
                "Use the checkboxes to track what you've applied.\n\n"
                "✅  Press OK to continue."
            )

        self.notebook.bind("<<NotebookTabChanged>>", _on_bios_tab_selected)

        # ── Banner ───────────────────────────────────────────────────────────
        banner = tk.Frame(parent, bg="#110800", height=66)
        banner.pack(fill="x")
        banner.pack_propagate(False)
        tk.Frame(banner, bg=BIOS_ACCENT, width=4).pack(side="left", fill="y")
        tk.Label(banner, text="⚙  BIOS TWEAKS",
                 font=("Consolas", 15, "bold"),
                 fg=BIOS_ACCENT, bg="#110800").pack(side="left", padx=18, pady=14)
        tk.Label(banner,
                 text="Zero Input Delay  •  XMP/DOCP  •  CPU Boost  •  PCIe  •  Better FPS",
                 font=("Consolas", 9), fg=BIOS_DIM, bg="#110800").pack(side="left", pady=14)

        # Action buttons in banner
        btn_frame = tk.Frame(banner, bg="#110800")
        btn_frame.pack(side="right", padx=16, pady=10)
        tk.Button(btn_frame, text="📋  Export BIOS Checklist",
                  font=("Consolas", 8, "bold"),
                  fg="#110800", bg=BIOS_YELLOW, relief="flat",
                  cursor="hand2", padx=10, pady=5,
                  command=lambda: self._bios_export_checklist()).pack(side="left", padx=(0, 8))
        tk.Button(btn_frame, text="☑  Mark All Done",
                  font=("Consolas", 8, "bold"),
                  fg="#110800", bg=BIOS_GREEN, relief="flat",
                  cursor="hand2", padx=10, pady=5,
                  command=lambda: self._bios_check_all()).pack(side="left")

        tk.Frame(parent, bg=BIOS_ACCENT, height=2).pack(fill="x")

        # ── Main layout: scrollable list (left) + progress panel (right) ────
        main_body = tk.Frame(parent, bg=BG)
        main_body.pack(fill="both", expand=True)

        # Scrollable list
        left_col = tk.Frame(main_body, bg=BG)
        left_col.pack(side="left", fill="both", expand=True)

        right_col = tk.Frame(main_body, bg=BG, width=280)
        right_col.pack(side="right", fill="y", padx=(0, 0))
        right_col.pack_propagate(False)

        bios_canvas = tk.Canvas(left_col, bg=BG, highlightthickness=0, bd=0)
        bios_scr = tk.Scrollbar(left_col, orient="vertical", command=bios_canvas.yview)
        bios_frame = tk.Frame(bios_canvas, bg=BG)
        bios_frame.bind("<Configure>",
            lambda e: bios_canvas.configure(scrollregion=bios_canvas.bbox("all")))
        bios_canvas.create_window((0, 0), window=bios_frame, anchor="nw")
        bios_canvas.configure(yscrollcommand=bios_scr.set)
        bios_canvas.pack(side="left", fill="both", expand=True)
        bios_scr.pack(side="right", fill="y")
        bios_canvas.bind("<MouseWheel>",
            lambda e: bios_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        body = tk.Frame(bios_frame, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=10)

        # Inline warning
        warn_outer = tk.Frame(body, bg=BIOS_RED)
        warn_outer.pack(fill="x", pady=(0, 12))
        warn_inner = tk.Frame(warn_outer, bg="#1f0000", padx=14, pady=10)
        warn_inner.pack(fill="x", padx=2, pady=2)
        tk.Label(warn_inner,
                 text="🚨  USE AT YOUR OWN RISK  —  BIOS GUIDANCE ONLY",
                 font=("Consolas", 10, "bold"), fg=BIOS_RED, bg="#1f0000",
                 anchor="w").pack(fill="x")
        tk.Label(warn_inner,
                 text=("BANZ OPTIMIZATION cannot apply BIOS settings directly.\n"
                       "Enter your BIOS/UEFI manually (DEL / F2 / F12 at boot) and set each option.\n"
                       "Use the ✓ checkboxes to track your progress. Export a checklist to keep with you."),
                 font=("Consolas", 8), fg=BIOS_YELLOW, bg="#1f0000",
                 justify="left", anchor="w").pack(fill="x")

        # ── BIOS Tweak Groups ────────────────────────────────────────────────
        BIOS_TWEAKS = [
            {
                "section": "⚡  ZERO INPUT DELAY & LATENCY",
                "section_color": BIOS_RED,
                "items": [
                    ("bios_cstates",
                     "Disable CPU C-States (C1/C2/C3/C6/C7/C8)",
                     BIOS_RED, "HIGH",
                     ("C-States put CPU cores to sleep to save power. When disabled, every core is "
                      "always at full speed — eliminates wakeup latency spikes. Trade-off: higher idle power draw."),
                     "CPU Configuration > C-States / CPU C-States Control",
                     "Set to: Disabled"),

                    ("bios_hpet",
                     "Enable HPET (High Precision Event Timer)",
                     BIOS_YELLOW, "MED",
                     ("HPET provides the highest resolution system timer. Enabling it gives sub-millisecond "
                      "timing accuracy, important for consistent frame pacing."),
                     "Advanced > Integrated Peripherals > HPET",
                     "Set to: Enabled (64-bit)"),

                    ("bios_speedstep",
                     "Disable CPU SpeedStep / Cool'n'Quiet",
                     BIOS_RED, "HIGH",
                     ("SpeedStep (Intel) / Cool'n'Quiet (AMD) reduces CPU frequency when idle. Disabling "
                      "keeps the CPU at max clock 100% of the time — eliminates frequency ramp-up delay."),
                     "CPU Configuration > Intel SpeedStep / AMD Cool'n'Quiet",
                     "Set to: Disabled"),

                    ("bios_dram_pd",
                     "Disable DRAM Power Down Mode",
                     BIOS_YELLOW, "MED",
                     ("RAM has its own power saving mode that can cause extra latency on first access "
                      "after idle. Disabling ensures RAM is always in full-speed active mode."),
                     "Advanced > DRAM Configuration > DRAM Power Down Mode",
                     "Set to: Disabled"),

                    ("bios_aspm",
                     "Set PCIe Active State Power Management (ASPM) to OFF",
                     BIOS_RED, "HIGH",
                     ("PCIe ASPM allows the GPU and NVMe SSD to enter low-power link states. "
                      "Disabling eliminates the re-link delay when the GPU/SSD wakes from idle — "
                      "reduces stutter and input lag spikes."),
                     "Advanced > PCIe Configuration > PCIe ASPM",
                     "Set to: Disabled / Off"),

                    ("bios_erp",
                     "Disable ErP / EuP Ready",
                     BIOS_YELLOW, "LOW",
                     ("ErP/EuP ready mode enables deep power-off states that can delay USB device "
                      "initialization on boot. Disabling it ensures faster USB device readiness."),
                     "Advanced > Power Management > ErP Ready / EuP Ready",
                     "Set to: Disabled"),
                ]
            },
            {
                "section": "🧠  RAM SPEED — XMP / DOCP (Huge FPS gain)",
                "section_color": BIOS_YELLOW,
                "items": [
                    ("bios_xmp",
                     "Enable XMP / DOCP / EXPO Profile",
                     BIOS_YELLOW, "HIGH",
                     ("By default, RAM runs at 2133 MHz JEDEC minimum regardless of its rated speed "
                      "(3200/3600/4800/6000+ MHz). Enabling XMP (Intel) or DOCP/EXPO (AMD) unlocks "
                      "the rated frequency. Often +10–30 FPS in CPU-bottlenecked games."),
                     "AI Tweaker / Extreme Tweaker / D.O.C.P / EXPO",
                     "Set to: XMP I or XMP II (highest stable profile)"),

                    ("bios_timings",
                     "Verify RAM Timings Match XMP Profile",
                     BIOS_YELLOW, "MED",
                     ("After enabling XMP, verify the timings (CL, tRCD, tRP, tRAS) match your RAM "
                      "stick's rated specs. Some boards may set them too conservatively."),
                     "Advanced > DRAM Configuration > Memory Timings",
                     "Match to XMP sticker on RAM (e.g. CL16-18-18-38)"),

                    ("bios_geardown",
                     "Enable Memory Gear Down Mode (AMD only)",
                     BIOS_YELLOW, "MED",
                     ("On AMD platforms, Gear Down Mode improves stability at high memory frequencies "
                      "by halving the command rate to 2T. Safer than 1T at >3600 MHz."),
                     "AMD CBS > UMC Common Options > Gear Down Mode",
                     "Set to: Enabled"),
                ]
            },
            {
                "section": "🔥  CPU PERFORMANCE & BOOST",
                "section_color": "#ff6b00",
                "items": [
                    ("bios_pbo",
                     "Enable Precision Boost Overdrive — PBO (AMD only)",
                     "#ff6b00", "HIGH",
                     ("PBO allows Ryzen CPUs to boost higher and longer than stock settings. "
                      "Combined with Auto or Manual curve optimizer, this gives free performance "
                      "with minimal risk. Not applicable to Intel."),
                     "AMD CBS > CPU Common Options > Precision Boost Overdrive",
                     "Set to: Auto or Enabled; Boost Override: +200 MHz"),

                    ("bios_turbo",
                     "Enable Intel Turbo Boost / AMD Core Boost",
                     "#ff6b00", "HIGH",
                     ("Ensure CPU Turbo Boost is enabled. Some boards disable it in power-saving "
                      "profiles. Turbo allows the CPU to exceed its base clock during burst workloads."),
                     "CPU Configuration > Intel Turbo Boost / AMD Core Boost",
                     "Set to: Enabled"),

                    ("bios_perfbias",
                     "Set CPU Performance Bias to Performance",
                     "#ff6b00", "MED",
                     ("Biases the CPU scheduler and voltage regulator toward sustaining higher boost "
                      "clocks. Available on most modern boards."),
                     "CPU Configuration > CPU Power Management > Performance Bias",
                     "Set to: Performance or Throughput"),

                    ("bios_vt",
                     "Disable CPU Virtualization if not needed (VT-x / SVM)",
                     BIOS_DIM, "LOW",
                     ("Virtualization tech adds a very small overhead. If you don't use VMs, "
                      "disabling it reclaims these cycles. NOTE: Required for WSL2, Android Emulators."),
                     "CPU Configuration > Intel VT-x / AMD SVM Mode",
                     "Set to: Disabled (ONLY if no VMs/WSL2 used)"),
                ]
            },
            {
                "section": "🖥  GPU & STORAGE — PCIe SETTINGS",
                "section_color": BIOS_GREEN,
                "items": [
                    ("bios_pcie_gpu",
                     "Set Primary GPU Slot to PCIe Gen 4 or Gen 5",
                     BIOS_GREEN, "HIGH",
                     ("Auto mode can sometimes train PCIe at Gen 3 speed even if your GPU and board "
                      "support Gen 4/5. Manually setting it ensures maximum GPU bandwidth."),
                     "Advanced > PCIe Configuration > PCIEX16 Speed",
                     "Set to: Gen 4 (or Gen 5 for RTX 4000+ series)"),

                    ("bios_m2_speed",
                     "Set M.2 NVMe Slot to PCIe Gen 4",
                     BIOS_GREEN, "MED",
                     ("NVMe SSDs can be capped at Gen 3 on Auto. Gen 4 NVMe roughly doubles "
                      "sequential read speed which reduces shader/texture load times."),
                     "Advanced > PCIe Configuration > M2_1 Speed",
                     "Set to: Gen 4 or Gen 5 (match SSD spec)"),

                    ("bios_rebar",
                     "Enable Resizable BAR (ReBAR / Smart Access Memory)",
                     BIOS_GREEN, "HIGH",
                     ("Allows the CPU to access the full GPU VRAM at once. AMD calls it SAM. "
                      "Provides +3–15% FPS in games that support it (Fortnite, Valorant, CS2, etc)."),
                     "Advanced > PCIe > Resizable BAR / Above 4G Decoding + SAM",
                     "Enable: Above 4G Decoding = On, Re-Size BAR Support = Auto/Enabled"),

                    ("bios_4g",
                     "Enable Above 4G Decoding",
                     BIOS_GREEN, "HIGH",
                     ("Required prerequisite for Resizable BAR. Allows PCIe devices to use memory "
                      "addresses above the 4GB boundary — needed for modern high-VRAM GPUs."),
                     "Advanced > PCIe Configuration > Above 4G Decoding",
                     "Set to: Enabled"),
                ]
            },
            {
                "section": "🌡  FAN & THERMAL MANAGEMENT",
                "section_color": "#00d4ff",
                "items": [
                    ("bios_fan",
                     "Set CPU Fan Curve to Performance",
                     "#00d4ff", "MED",
                     ("Running fans at higher RPM keeps thermals lower which lets the CPU sustain "
                      "higher boost clocks longer. Set a more aggressive curve in Q-Fan settings."),
                     "Monitor > Fan Speed Control / Q-Fan Control",
                     "Set CPU fan to: Performance or Standard (not Silent/Quiet)"),

                    ("bios_tjmax",
                     "Disable Thermal Throttle Boost Limit (if stable)",
                     "#00d4ff", "MED",
                     ("Some boards have aggressive thermal protection that reduces CPU boost at "
                      "temperatures that are actually safe. Only adjust if your cooling is adequate."),
                     "CPU Configuration > CPU Thermal Throttle / Tj Max Offset",
                     "Set Tj Max to 105°C or disable boost throttle if thermals are safe"),
                ]
            },
            {
                "section": "🚀  BOOT SPEED & MISC",
                "section_color": BIOS_DIM,
                "items": [
                    ("bios_fastboot",
                     "Enable Fast Boot",
                     BIOS_DIM, "LOW",
                     ("Fast Boot skips memory training and device initialization on each boot — "
                      "significantly reduces POST time. Disable temporarily if booting from USB."),
                     "Boot > Fast Boot",
                     "Set to: Enabled"),

                    ("bios_secboot",
                     "Secure Boot — Keep ON for Windows 11 + Valorant",
                     BIOS_DIM, "LOW",
                     ("Secure Boot verifies bootloaders. Required ON for Windows 11 out of box. "
                      "NOTE: Valorant/EasyAntiCheat requires Secure Boot ON. Only disable for Linux dual-boot."),
                     "Boot > Secure Boot",
                     "Keep ENABLED for Windows 11 + Valorant"),

                    ("bios_bootorder",
                     "Set Boot Device Priority to SSD first",
                     BIOS_DIM, "LOW",
                     ("Ensures the system boots directly from your NVMe SSD without scanning "
                      "optical drives or USB sticks first — shaves seconds off every boot."),
                     "Boot > Boot Device Priority / Boot Order",
                     "Move NVMe SSD / Windows Boot Manager to #1 position"),
                ]
            },
        ]

        # Store tweak data for export
        self._bios_tweaks_data = BIOS_TWEAKS

        # Build the tweak cards
        for group in BIOS_TWEAKS:
            sec_col = group["section_color"]
            sec_hdr = tk.Frame(body, bg=BG)
            sec_hdr.pack(fill="x", pady=(12, 4))
            tk.Frame(sec_hdr, bg=sec_col, width=4).pack(side="left", fill="y")
            tk.Label(sec_hdr, text=f"  {group['section']}",
                     font=("Consolas", 10, "bold"),
                     fg=sec_col, bg=BG, pady=5).pack(side="left")

            for item in group["items"]:
                item_id, name, col, impact, desc, bios_path, value = item

                # Create checkbox var
                check_var = tk.BooleanVar(value=False)
                self._bios_checkboxes[item_id] = check_var

                outer = tk.Frame(body, bg=BORDER)
                outer.pack(fill="x", pady=(0, 3))
                card = tk.Frame(outer, bg=PANEL)
                card.pack(fill="x", padx=1, pady=1)

                # Checkbox on the left edge
                check_frame = tk.Frame(card, bg=PANEL, padx=8, pady=8)
                check_frame.pack(side="left")

                def _make_toggle(cid, co, ca, ch):
                    """Closure for checkbox toggle callback."""
                    def _toggle():
                        if ch.get():
                            ca.config(text="✓", fg=BIOS_GREEN, bg=PANEL,
                                      font=("Consolas", 14, "bold"))
                            co.config(bg="#0f1f0f")
                        else:
                            ca.config(text="○", fg=BIOS_DIM, bg=PANEL,
                                      font=("Consolas", 14))
                            co.config(bg=PANEL)
                        self._bios_update_progress()
                    return _toggle

                status_lbl = tk.Label(check_frame, text="○",
                                      font=("Consolas", 14), fg=BIOS_DIM, bg=PANEL,
                                      cursor="hand2")
                status_lbl.pack()

                chk_btn = tk.Button(check_frame, text="Done",
                                    font=("Consolas", 7, "bold"),
                                    fg=BIOS_DIM, bg=BG3, relief="flat",
                                    cursor="hand2", padx=4, pady=1)
                chk_btn.pack(pady=(2, 0))

                # Wire up toggle
                toggle_fn = _make_toggle(item_id, card, status_lbl, check_var)
                chk_btn.config(command=lambda fn=toggle_fn, cv=check_var: (cv.set(not cv.get()), fn()))
                status_lbl.bind("<Button-1>", lambda e, fn=toggle_fn, cv=check_var: (cv.set(not cv.get()), fn()))

                # Info area
                info = tk.Frame(card, bg=PANEL, padx=10, pady=8)
                info.pack(side="left", fill="x", expand=True)

                hdr_row = tk.Frame(info, bg=PANEL)
                hdr_row.pack(fill="x")
                IMPACT_C = {"HIGH": BIOS_RED, "MED": BIOS_YELLOW, "LOW": BIOS_DIM}
                tk.Label(hdr_row, text=f"[{impact}]",
                         font=("Consolas", 7, "bold"),
                         fg=IMPACT_C.get(impact, BIOS_YELLOW), bg=PANEL,
                         width=6).pack(side="left")
                tk.Label(hdr_row, text=name,
                         font=("Consolas", 9, "bold"),
                         fg=TEXT, bg=PANEL, anchor="w").pack(side="left", padx=(4, 0))

                tk.Label(info, text=desc,
                         font=("Consolas", 8), fg=TEXT3, bg=PANEL,
                         anchor="w", wraplength=640, justify="left").pack(fill="x", pady=(3, 0))

                path_row = tk.Frame(info, bg=PANEL)
                path_row.pack(fill="x", pady=(4, 0))
                tk.Label(path_row, text="📂 Path:",
                         font=("Consolas", 7, "bold"), fg=col, bg=PANEL).pack(side="left")
                tk.Label(path_row, text=f"  {bios_path}",
                         font=("Consolas", 8), fg=TEXT2, bg=PANEL).pack(side="left")

                val_row = tk.Frame(info, bg=PANEL)
                val_row.pack(fill="x")
                tk.Label(val_row, text="✅ Set To:",
                         font=("Consolas", 7, "bold"), fg=BIOS_GREEN, bg=PANEL).pack(side="left")
                tk.Label(val_row, text=f"  {value}",
                         font=("Consolas", 8, "bold"), fg=BIOS_GREEN, bg=PANEL).pack(side="left")

        # Bottom tip
        foot = tk.Frame(body, bg=BG)
        foot.pack(fill="x", pady=(14, 6))
        tk.Label(foot,
                 text=("💡  Access BIOS: press  DEL / F2 / F12 / ESC  during POST.\n"
                       "   ASUS → DEL  |  MSI → DEL  |  Gigabyte → DEL  |  ASRock → F2\n"
                       "   ⚠  Take a phone photo of BIOS screens before changing anything."),
                 font=("Consolas", 8), fg=BIOS_YELLOW, bg=BG,
                 justify="left", anchor="w").pack(anchor="w")

        # ── Right panel: progress tracker ────────────────────────────────────
        prog_body = tk.Frame(right_col, bg=BG2)
        prog_body.pack(fill="both", expand=True, padx=1, pady=0)

        tk.Frame(prog_body, bg=BIOS_ACCENT, height=3).pack(fill="x")

        tk.Label(prog_body, text="BIOS PROGRESS",
                 font=("Consolas", 9, "bold"), fg=BIOS_ACCENT, bg=BG2,
                 pady=10).pack()
        tk.Frame(prog_body, bg=BORDER, height=1).pack(fill="x", padx=10)

        self._bios_progress_lbl = tk.Label(prog_body, text="0 / 0 applied",
                                           font=("Consolas", 22, "bold"),
                                           fg=TEXT2, bg=BG2)
        self._bios_progress_lbl.pack(pady=(14, 4))

        self._bios_progress_pct = tk.Label(prog_body, text="0%",
                                           font=("Consolas", 11), fg=BIOS_DIM, bg=BG2)
        self._bios_progress_pct.pack()

        # Progress bar
        pb_outer = tk.Frame(prog_body, bg=BG3, height=6)
        pb_outer.pack(fill="x", padx=16, pady=12)
        pb_outer.pack_propagate(False)
        self._bios_pb_canvas = tk.Canvas(pb_outer, bg=BG3, height=6,
                                         highlightthickness=0, bd=0)
        self._bios_pb_canvas.pack(fill="x", expand=True)
        self._bios_pb_rect = self._bios_pb_canvas.create_rectangle(
            0, 0, 0, 6, fill=BIOS_ACCENT, outline="")

        tk.Frame(prog_body, bg=BORDER, height=1).pack(fill="x", padx=10)

        # Per-item status list in right panel
        items_frame = tk.Frame(prog_body, bg=BG2)
        items_frame.pack(fill="both", expand=True, padx=10, pady=8)

        self._bios_status_labels = {}
        for group in BIOS_TWEAKS:
            for item in group["items"]:
                item_id, name = item[0], item[1]
                row = tk.Frame(items_frame, bg=BG2)
                row.pack(fill="x", pady=1)
                dot = tk.Label(row, text="○", font=("Consolas", 9),
                               fg=BIOS_DIM, bg=BG2, width=2)
                dot.pack(side="left")
                tk.Label(row, text=name[:30] + ("…" if len(name) > 30 else ""),
                         font=("Consolas", 7), fg=TEXT3, bg=BG2,
                         anchor="w").pack(side="left", fill="x", expand=True)
                self._bios_status_labels[item_id] = dot

        # Export + reset buttons
        tk.Frame(prog_body, bg=BORDER, height=1).pack(fill="x", padx=10, pady=(6, 0))
        btn_bot = tk.Frame(prog_body, bg=BG2)
        btn_bot.pack(fill="x", padx=10, pady=8)
        tk.Button(btn_bot, text="📋 Export",
                  font=("Consolas", 8, "bold"),
                  fg=BG2, bg=BIOS_YELLOW, relief="flat",
                  cursor="hand2", padx=8, pady=4,
                  command=lambda: self._bios_export_checklist()).pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Button(btn_bot, text="↺ Reset",
                  font=("Consolas", 8, "bold"),
                  fg=TEXT2, bg=BG3, relief="flat",
                  cursor="hand2", padx=8, pady=4,
                  command=lambda: self._bios_reset_all()).pack(side="left", fill="x", expand=True)

        # Initialize progress
        self.root.after(200, self._bios_update_progress)



    # ── BIOS helper methods ───────────────────────────────────────────────────
    def _bios_update_progress(self):
        """Refresh the BIOS progress panel after a checkbox toggle."""
        if not hasattr(self, '_bios_checkboxes'):
            return
        total = len(self._bios_checkboxes)
        done  = sum(1 for v in self._bios_checkboxes.values() if v.get())
        pct   = int(done / total * 100) if total else 0

        try:
            self._bios_progress_lbl.config(
                text=f"{done} / {total}",
                fg="#00e5a0" if done == total else "#00d4ff" if done > 0 else "#607a92")
            self._bios_progress_pct.config(
                text=f"{pct}% complete",
                fg="#00e5a0" if pct == 100 else "#ffd740" if pct > 50 else "#354d62")

            # Update progress bar
            w = self._bios_pb_canvas.winfo_width()
            if w > 4:
                bar_w = max(0, int(w * pct / 100))
                col = "#00e5a0" if pct == 100 else "#00d4ff" if pct > 50 else "#ff8c00"
                self._bios_pb_canvas.coords(self._bios_pb_rect, 0, 0, bar_w, 6)
                self._bios_pb_canvas.itemconfig(self._bios_pb_rect, fill=col)

            # Update per-item dots
            for item_id, var in self._bios_checkboxes.items():
                if item_id in self._bios_status_labels:
                    dot = self._bios_status_labels[item_id]
                    if var.get():
                        dot.config(text="✓", fg="#00e5a0")
                    else:
                        dot.config(text="○", fg="#354d62")
        except tk.TclError:
            pass

    def _bios_check_all(self):
        """Mark all BIOS checklist items as done."""
        for item_id, var in self._bios_checkboxes.items():
            var.set(True)
        self._bios_update_progress()
        self._log("[BIOS] All items marked as applied.", "ok")

    def _bios_reset_all(self):
        """Reset all BIOS checklist items."""
        for var in self._bios_checkboxes.values():
            var.set(False)
        self._bios_update_progress()
        self._log("[BIOS] Checklist reset.", "warn")

    def _bios_export_checklist(self):
        """Export a printable BIOS checklist as a .txt file."""
        import tkinter.filedialog as fd
        lines = [
            "=" * 60,
            "  BANZ OPTIMIZATION  Beta v1  —  BIOS CHECKLIST",
            "=" * 60,
            f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "  Platform:  " + OS,
            "=" * 60,
            "",
            "Tick each box after you apply the setting in your BIOS.",
            "Access BIOS: DEL / F2 / F12 / ESC at boot.",
            "",
        ]
        if hasattr(self, '_bios_tweaks_data'):
            for group in self._bios_tweaks_data:
                lines.append("")
                lines.append("── " + group["section"] + " ─" * 8)
                for item in group["items"]:
                    item_id, name, col, impact, desc, bios_path, value = item
                    done = self._bios_checkboxes.get(item_id, tk.BooleanVar()).get()
                    tick = "[✓]" if done else "[ ]"
                    lines.append(f"  {tick}  [{impact}] {name}")
                    lines.append(f"        Path:  {bios_path}")
                    lines.append(f"        Value: {value}")
                    lines.append("")

        lines += [
            "=" * 60,
            "  ⚠  Take a phone photo of each BIOS screen before changing.",
            "     These are guidance notes only. Apply at your own risk.",
            "=" * 60,
        ]

        text = "\n".join(lines)
        path = fd.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
            initialfile="BIOS_Checklist_BANZ.txt",
            title="Save BIOS Checklist"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self._log(f"[BIOS] Checklist exported → {path}", "ok")
            except Exception as e:
                self._log(f"[BIOS] Export failed: {e}", "err")

    # ── Clean shutdown ────────────────────────────────────────────────────────
    def _on_close(self):
        self._alive  = False
        self.running = False
        self.root.after(200, self.root.destroy)

    def run(self):
        self._log(f"BANZ OPTIMIZATION  Beta v1  —  {OS}", "ok")
        self._log("Click  ▶ START MONITOR  to begin live ping tracking", "ok")
        self._log("Head to TWEAKS or DEBLOAT tabs to optimise your system", "info")
        self._log("BIOS tab: use the checklist to track your BIOS changes", "info")


# ─────────────────────────────────────────────────────────────────────────────
def is_admin():
    try:
        if OS == "Windows":
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False

def relaunch_as_admin():
    if OS == "Windows":
        import ctypes
        params = " ".join(f'"{a}"' for a in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        if ret <= 32:
            import tkinter.messagebox as mb
            mb.showerror("Admin Required",
                         "This app needs administrator rights to apply network tweaks.\n"
                         "Please right-click and choose 'Run as administrator'.")
    else:
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

if __name__ == "__main__":
    if OS == "Windows":
        os.system("color")
    if not is_admin():
        relaunch_as_admin()
        sys.exit(0)
    app = PingOptimizerApp()
