#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

try:
    import PySimpleGUI as sg
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PySimpleGUI"])
    import PySimpleGUI as sg

APP_NAME = "AKATSYKI VPN WIFI"
APP_VERSION = "1.3.0"
APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "config.json"
LOG_DIR = APP_ROOT / "logs"
LOG_PATH = LOG_DIR / "app.log"
ZAPRET_ROOT = APP_ROOT / "zapret"
XRAY_ROOT = APP_ROOT / "xray"
XRAY_EXE = XRAY_ROOT / "xray.exe"

DNS_OPTIONS = {
    "Xbox DNS": ["111.88.96.54", "111.88.96.55"],
    "Google DNS": ["8.8.8.8", "8.8.4.4"],
    "Custom": [],
}

def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{ts}] {message}"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)

def ensure_windows() -> None:
    if os.name != "nt":
        raise RuntimeError("Это приложение предназначено только для Windows 10/11.")

def is_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return subprocess.run(["whoami", "/groups"], capture_output=True, text=True, check=False).returncode == 0
    except Exception:
        return False

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "ssid": "AKATSYKI_WIFI",
        "password": "12345678",
        "dns_mode": "Xbox DNS",
        "custom_dns": "111.88.96.54, 111.88.96.55",
        "mode": "zapret",
        "subscription_url": "",
        "autostart": False,
    }

def save_config(data: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"Скачивание: {url}")
    response = requests.get(url, timeout=120, stream=True)
    response.raise_for_status()
    with target.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                fh.write(chunk)
    log(f"Скачано: {target}")

def find_general_bat(root: Path) -> Path | None:
    for path in root.rglob("general.bat"):
        if path.is_file():
            return path
    return None

def ensure_zapret() -> Path:
    script = find_general_bat(ZAPRET_ROOT)
    if script is not None:
        log(f"Zapret уже установлен: {script.parent}")
        return script.parent

    ZAPRET_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        api_url = "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest"
        response = requests.get(api_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        asset_url = None
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if "zip" in name.lower():
                asset_url = asset.get("browser_download_url")
                break
        if not asset_url:
            raise RuntimeError("Не найден zip-архив Zapret в релизах")

        archive = ZAPRET_ROOT / "zapret.zip"
        download_file(asset_url, archive)
        log("Распаковка Zapret...")
        shutil.unpack_archive(str(archive), str(ZAPRET_ROOT))
        archive.unlink(missing_ok=True)
        log("Zapret скачан и распакован")
    except Exception as exc:
        log(f"Ошибка скачивания Zapret: {exc}")
        raise

    script = find_general_bat(ZAPRET_ROOT)
    if script is None:
        raise RuntimeError("После распаковки не найден general.bat в папке zapret")
    return script.parent

def ensure_xray() -> Path:
    if XRAY_EXE.exists():
        log("Xray уже установлен")
        return XRAY_EXE

    XRAY_ROOT.mkdir(parents=True, exist_ok=True)
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-windows-64.zip"
        archive = XRAY_ROOT / "xray.zip"
        download_file(url, archive)
        log("Распаковка Xray...")
        shutil.unpack_archive(str(archive), str(XRAY_ROOT))
        archive.unlink(missing_ok=True)
        log("Xray скачан и распакован")
    except Exception as exc:
        log(f"Ошибка скачивания Xray: {exc}")
        raise

    if not XRAY_EXE.exists():
        raise RuntimeError("xray.exe не найден после распаковки")
    return XRAY_EXE

def detect_wifi_interface() -> str:
    try:
        output = subprocess.check_output(["netsh", "interface", "show", "interface"], text=True, stderr=subprocess.STDOUT)
        for line in output.splitlines():
            if "Interface Name" in line or "---" in line:
                continue
            parts = line.split()
            if len(parts) >= 4:
                candidate = parts[0]
                lower = candidate.lower()
                if "wifi" in lower or "wireless" in lower:
                    return candidate
        return "Wi-Fi"
    except Exception:
        return "Wi-Fi"

def set_dns(mode: str, custom_dns: str = "") -> bool:
    ensure_windows()
    iface = detect_wifi_interface()
    if mode == "Custom":
        dns_list = [p.strip() for p in custom_dns.split(",") if p.strip()]
    else:
        dns_list = DNS_OPTIONS.get(mode, ["8.8.8.8", "8.8.4.4"])
    if not dns_list:
        log(f"Список DNS пуст для режима {mode}")
        return False
    try:
        for dns_ip in dns_list[:2]:
            subprocess.run([
                "netsh", "interface", "ip", "set", "dns",
                f"name={iface}", "source=static", f"addr={dns_ip}", "validate=no"
            ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"DNS установлен: {iface} -> {dns_list[:2]}")
        return True
    except Exception as exc:
        log(f"Ошибка установки DNS: {exc}")
        return False

def start_hotspot(ssid: str, password: str) -> bool:
    ensure_windows()
    try:
        if len(password) < 8:
            raise RuntimeError("Пароль должен содержать минимум 8 символов")
        subprocess.run([
            "netsh", "wlan", "set", "hostednetwork",
            f"mode=allow", f"ssid={ssid}", f"key={password}"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["netsh", "wlan", "start", "hostednetwork"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log(f"Hotspot запущен: {ssid}")
        return True
    except Exception as exc:
        log(f"Ошибка запуска hotspot: {exc}")
        return False

def stop_hotspot() -> bool:
    try:
        subprocess.run(["netsh", "wlan", "stop", "hostednetwork"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("Hotspot остановлен")
        return True
    except Exception as exc:
        log(f"Ошибка остановки hotspot: {exc}")
        return False

def parse_vless_line(line: str) -> dict:
    value = line.strip()
    if not value or not value.startswith("vless://"):
        return {}
    rest = value[len("vless://"):]
    if "@" not in rest:
        return {}
    userinfo, tail = rest.split("@", 1)
    if "?" in tail:
        host_port, query = tail.split("?", 1)
    else:
        host_port, query = tail, ""
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
    else:
        host, port = host_port, "443"
    params = parse_qs(query)
    return {
        "uuid": userinfo,
        "host": host,
        "port": int(port),
        "path": params.get("path", ["/"])[0],
        "sni": params.get("sni", [host])[0],
        "raw": value,
    }

def fetch_subscription_text(url_or_raw: str) -> str:
    value = url_or_raw.strip()
    if not value:
        return ""
    if value.startswith("http://") or value.startswith("https://"):
        response = requests.get(value, timeout=30)
        response.raise_for_status()
        return response.text
    return value

def ping_host(host: str) -> int:
    try:
        result = subprocess.run(["ping", "-n", "1", host], capture_output=True, text=True, timeout=10)
        match = re.search(r"time\s*[<=]\s*(\d+)ms", result.stdout, flags=re.I)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 999

def build_server_list(subscription_url: str) -> list[dict]:
    text = fetch_subscription_text(subscription_url)
    servers: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_vless_line(line)
        if parsed:
            parsed["ping"] = ping_host(parsed["host"])
            servers.append(parsed)
    servers.sort(key=lambda item: item.get("ping", 999))
    return servers

def create_xray_config(server: dict) -> Path:
    config_path = APP_ROOT / "xray-config.json"
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": 10808,
            "listen": "0.0.0.0",
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        }],
        "outbounds": [{
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": server.get("host", ""),
                    "port": int(server.get("port", 443)),
                    "users": [{"id": server.get("uuid", ""), "encryption": "none"}],
                }]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {"serverName": server.get("sni", server.get("host", ""))},
                "wsSettings": {"path": server.get("path", "/")},
            },
            "tag": "proxy"
        }, {"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
        "routing": {"rules": [{"type": "field", "outboundTag": "proxy", "network": "tcp,udp"}]},
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path

def start_xray(server: dict) -> bool:
    try:
        exe = ensure_xray()
        cfg = create_xray_config(server)
        subprocess.Popen([str(exe), "-config", str(cfg)], cwd=str(APP_ROOT), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log(f"Xray запущен: {server.get('host')}:{server.get('port')}")
        return True
    except Exception as exc:
        log(f"Ошибка запуска Xray: {exc}")
        return False

def start_zapret() -> bool:
    try:
        zapret_dir = ensure_zapret()
        general = find_general_bat(zapret_dir)
        if general is None:
            raise RuntimeError("Не найден general.bat в папке zapret")
        subprocess.Popen(["cmd", "/c", str(general)], cwd=str(general.parent), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        log("Zapret запущен")
        return True
    except Exception as exc:
        log(f"Ошибка запуска Zapret: {exc}")
        return False

def enable_autostart() -> bool:
    try:
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup_dir.mkdir(parents=True, exist_ok=True)
        runner = startup_dir / "AKATSYKI_VPN_WIFI.bat"
        runner.write_text(f'@echo off\n"{sys.executable}" "{APP_ROOT / "app.py"}"\n', encoding="utf-8")
        log(f"Автозапуск включён: {runner}")
        return True
    except Exception as exc:
        log(f"Ошибка включения автозапуска: {exc}")
        return False

def disable_autostart() -> bool:
    try:
        startup_dir = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        runner = startup_dir / "AKATSYKI_VPN_WIFI.bat"
        if runner.exists():
            runner.unlink()
        log("Автозапуск отключён")
        return True
    except Exception as exc:
        log(f"Ошибка отключения автозапуска: {exc}")
        return False

def make_layout(config: dict) -> list:
    return [
        [sg.Text(APP_NAME, font=("Segoe UI", 20, "bold"))],
        [sg.Radio("Zapret", "MODE", default=(config.get("mode") != "xray"), key="-MODE_ZAPRET-"),
         sg.Radio("Xray Key", "MODE", default=(config.get("mode") == "xray"), key="-MODE_XRAY-")],
        [sg.Text("SSID"), sg.InputText(config.get("ssid", "AKATSYKI_WIFI"), key="-SSID-")],
        [sg.Text("Пароль"), sg.InputText(config.get("password", "12345678"), key="-PASS-", password_char="•")],
        [sg.Text("DNS"), sg.Combo(list(DNS_OPTIONS.keys()), default_value=config.get("dns_mode", "Xbox DNS"), key="-DNS-", readonly=True)],
        [sg.Text("Custom DNS"), sg.InputText(config.get("custom_dns", "111.88.96.54, 111.88.96.55"), key="-CUSTOM_DNS-")],
        [sg.Text("VLESS / Subscription URL"), sg.InputText(config.get("subscription_url", ""), key="-SUB_URL-")],
        [sg.Button("Load Servers"), sg.Button("Start"), sg.Button("Stop"), sg.Button("Exit")],
        [sg.Checkbox("Автозапуск", default=bool(config.get("autostart", False)), key="-AUTO-")],
        [sg.Listbox([], size=(90, 8), key="-SERVER_LIST-", select_mode=sg.LISTBOX_SELECT_MODE_SINGLE)],
        [sg.Text("Статус: готово", key="-STATUS-", text_color="green")],
    ]

def main() -> None:
    sg.theme("DarkBlue3")
    config = load_config()
    window = sg.Window(APP_NAME, make_layout(config), finalize=True)
    servers: list[dict] = []

    while True:
        event, values = window.read(timeout=300)
        if event in (sg.WIN_CLOSED, "Exit"):
            break

        if event == "Load Servers":
            url = values["-SUB_URL-"].strip()
            if not url:
                window["-STATUS-"].update("Введите VLESS или HTTPS-подписку", text_color="red")
                continue
            try:
                servers = build_server_list(url)
                list_items = [f"{s['host']}:{s['port']} | ping {s['ping']} ms" for s in servers]
                window["-SERVER_LIST-"].update(list_items)
                window["-STATUS-"].update(f"Загружено серверов: {len(servers)}", text_color="green")
                log(f"Загружено {len(servers)} серверов из подписки")
            except Exception as exc:
                window["-STATUS-"].update(f"Ошибка загрузки серверов: {exc}", text_color="red")
                log(f"Ошибка загрузки серверов: {exc}")

        if event == "Start":
            cfg = {
                "ssid": values["-SSID-"].strip(),
                "password": values["-PASS-"].strip(),
                "dns_mode": values["-DNS-"],
                "custom_dns": values["-CUSTOM_DNS-"].strip(),
                "mode": "xray" if values["-MODE_XRAY-"] else "zapret",
                "subscription_url": values["-SUB_URL-"].strip(),
                "autostart": bool(values["-AUTO-"])
            }
            save_config(cfg)
            if cfg["autostart"]:
                enable_autostart()
            else:
                disable_autostart()

            try:
                if cfg["mode"] == "zapret":
                    if not cfg["ssid"] or not cfg["password"]:
                        raise RuntimeError("SSID и пароль обязательны")
                    window["-STATUS-"].update("Запуск Zapret...", text_color="blue")
                    window.refresh()
                    start_hotspot(cfg["ssid"], cfg["password"])
                    set_dns(cfg["dns_mode"], cfg["custom_dns"])
                    start_zapret()
                    window["-STATUS-"].update("Zapret запущен", text_color="green")
                else:
                    if not servers and cfg["subscription_url"]:
                        servers = build_server_list(cfg["subscription_url"])
                    if not servers:
                        raise RuntimeError("Сначала загрузите серверы из VLESS/подписки")
                    selected = servers[0]
                    list_values = values["-SERVER_LIST-"]
                    if list_values:
                        picked = list_values[0]
                        for s in servers:
                            label = f"{s['host']}:{s['port']} | ping {s['ping']} ms"
                            if label == picked:
                                selected = s
                                break
                    window["-STATUS-"].update("Запуск Xray...", text_color="blue")
                    window.refresh()
                    start_hotspot(cfg["ssid"], cfg["password"])
                    set_dns(cfg["dns_mode"], cfg["custom_dns"])
                    start_xray(selected)
                    window["-STATUS-"].update(f"Xray активен: {selected['host']}:{selected['port']}", text_color="green")
            except Exception as exc:
                window["-STATUS-"].update(f"Ошибка запуска: {exc}", text_color="red")
                log(f"Ошибка запуска: {exc}")

        if event == "Stop":
            stop_hotspot()
            window["-STATUS-"].update("Остановлено", text_color="red")

    window.close()

if __name__ == "__main__":
    try:
        ensure_windows()
        if not is_admin():
            raise RuntimeError("Запустите приложение от имени администратора")
        log(f"=== {APP_NAME} v{APP_VERSION} started ===")
        main()
    except Exception as exc:
        log(f"Критическая ошибка: {exc}")
        sg.popup_error(f"Ошибка запуска:\n{exc}\n\nЗапустите от имени администратора.")
        raise