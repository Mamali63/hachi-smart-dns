#!/usr/bin/env bash
# Hachi Smart DNS — installer (released 2026-10-30)
# Run as root on a fresh Ubuntu 24.04 VPS, from the repo directory:
#   sudo bash install.sh
# What it does:
#   - installs python3, unbound, sniproxy
#   - installs the registration service (port 8792) + hourly expiry timer
#   - installs the sample Unbound / Sniproxy configs with YOUR server IP
#   - creates an empty customer table (customers.json is created empty;
#     it is never shipped with data)
# What it does NOT do (do these by hand before selling):
#   - put the registration service behind HTTPS (use your own domain + TLS)
#   - close the open resolver / apply the whitelist split-view
#   - set the monthly price or issue customer codes (use dns_admin.py)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/hachi-dns"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash install.sh" >&2
  exit 1
fi

# --- server IP -------------------------------------------------------------
DETECTED_IP="$(curl -fsS --max-time 10 https://ifconfig.me 2>/dev/null || true)"
if [ -n "${SERVER_IP:-}" ]; then
  :
elif [ -n "$DETECTED_IP" ]; then
  read -r -p "Server public IP / آی‌پی عمومی سرور [$DETECTED_IP]: " SERVER_IP
  SERVER_IP="${SERVER_IP:-$DETECTED_IP}"
else
  read -r -p "Server public IP / آی‌پی عمومی سرور: " SERVER_IP
fi
if [ -z "${SERVER_IP:-}" ]; then
  echo "No server IP given, aborting." >&2
  exit 1
fi
echo "Using server IP: $SERVER_IP / آی‌پی سرور: $SERVER_IP"

# --- panel port ------------------------------------------------------------
# Default 8080. Ask (y/N); empty answer or "no" keeps the default.
# If the chosen port is already in use, warn and ask again.
ask_port() {
  local port=8080 ans="" input="" first=1
  echo "Panel port (default 8080) / پورت پنل (پیش‌فرض ۸۰۸۰)"
  echo "If the port is busy on your server, you can change it. / اگر پورت روی سرورت درگیر است، می‌توانی عوضش کنی."
  while true; do
    if [ "$first" = 1 ]; then
      first=0
      read -r -p "Change panel port? (y/N) / پورت پنل را عوض می‌کنی؟ (y/N) " ans
      case "$ans" in
        y|Y|yes|YES) read -r -p "Enter panel port [8080] / پورت پنل را بزن [8080]: " input; port="${input:-8080}" ;;
        *) port=8080 ;;
      esac
    else
      read -r -p "Enter panel port [8080] / پورت پنل را بزن [8080]: " input
      port="${input:-8080}"
    fi
    if ! [[ "$port" =~ ^[0-9]+$ ]] || [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
      echo "Not a valid port. / پورت درست نیست."
      continue
    fi
    if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ":$port "; then
      echo "Port $port is already in use. / پورت $port درگیر است."
      continue
    fi
    PANEL_PORT="$port"
    echo "Panel port: $PANEL_PORT / پورت پنل: $PANEL_PORT"
    return 0
  done
}
ask_port

# --- packages --------------------------------------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 unbound sniproxy curl

# --- registration service + admin panel ----------------------------------
mkdir -p "$INSTALL_DIR"
cp "$REPO_DIR/server/reg_server.py" "$REPO_DIR/server/dns_admin.py" "$REPO_DIR/server/dns_expire.py" "$INSTALL_DIR/"
cp "$REPO_DIR/server/admin_panel.py" "$REPO_DIR/server/domains.json" "$REPO_DIR/server/domains.default.json" "$REPO_DIR/server/blocked.json" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/"*.py

# DNS addresses the app shows to customers
python3 "$INSTALL_DIR/dns_admin.py" set-dns "$SERVER_IP" "$SERVER_IP"

# App version the server reports to the client (update check)
printf '{"versionCode": 3, "versionName": "1.2.0"}' > "$INSTALL_DIR/version.json"

# --- Unbound + Sniproxy configs -------------------------------------------
# The samples carry the placeholder 203.0.113.10 (TEST-NET-3); swap it.
mkdir -p /etc/unbound/unbound.conf.d
sed "s/203\.0\.113\.10/$SERVER_IP/g" "$REPO_DIR/config-samples/hachi-dns.conf" > /etc/unbound/unbound.conf.d/hachi-dns.conf
# The SNI table is generated from domains.json (the panel's source of truth),
# so the installed table always matches what the panel shows.
cd "$INSTALL_DIR"
HACHI_SNI_CONF=/etc/unbound/unbound.conf.d/hachi-sni.conf HACHI_RELOAD=0 python3 -c "import admin_panel; print(admin_panel.rebuild_sni())"
# The blocklist (blocked.json) is generated the same way; empty by default.
HACHI_BLOCK_CONF=/etc/unbound/unbound.conf.d/hachi-block.conf HACHI_RELOAD=0 python3 -c "import admin_panel; print(admin_panel.rebuild_blocklist())"
cd - >/dev/null
cp "$REPO_DIR/config-samples/sniproxy.conf" /etc/sniproxy.conf

unbound-checkconf /etc/unbound/unbound.conf.d/hachi-dns.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-sni.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-block.conf

# --- systemd ---------------------------------------------------------------
cp "$REPO_DIR/systemd/hachi-dns-reg.service" "$REPO_DIR/systemd/hachi-dns-expire.service" "$REPO_DIR/systemd/hachi-dns-expire.timer" /etc/systemd/system/
sed "s/HACHI_PANEL_PORT=8080/HACHI_PANEL_PORT=$PANEL_PORT/" "$REPO_DIR/systemd/hachi-dns-panel.service" > /etc/systemd/system/hachi-dns-panel.service
# Always-on: our own services already carry Restart=always in their units.
# Give the same to unbound/sniproxy (distro units) via drop-ins, so a crash
# brings them back and a VPS reboot brings the whole stack back up.
for svc in unbound sniproxy; do
  mkdir -p "/etc/systemd/system/$svc.service.d"
  printf '[Service]\nRestart=always\nRestartSec=5\n' > "/etc/systemd/system/$svc.service.d/restart.conf"
done
systemctl daemon-reload
systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer hachi-dns-panel.service

# --- firewall: open the ports the service needs ---------------------------
# Without this, the panel is unreachable from the internet — the exact bug
# we hit on 2026-10-30: the panel only answered from the VPN because ufw
# had no rule for its port (the browser just kept spinning). Same for the
# DNS port (53) and the registration port (8792) on a fresh VPS with ufw
# enabled. Skip silently if ufw is not installed.
if command -v ufw >/dev/null 2>&1; then
  ufw allow "$PANEL_PORT/tcp" comment "hachi-dns-panel" 2>/dev/null || ufw allow "$PANEL_PORT/tcp"
  ufw allow 53/tcp comment "hachi-dns" 2>/dev/null || ufw allow 53/tcp
  ufw allow 53/udp comment "hachi-dns" 2>/dev/null || ufw allow 53/udp
  ufw allow 8792/tcp comment "hachi-dns-reg" 2>/dev/null || ufw allow 8792/tcp
fi

# --- restart DNS services --------------------------------------------------
systemctl restart unbound sniproxy
systemctl enable unbound sniproxy >/dev/null 2>&1 || true

# --- summary ---------------------------------------------------------------
echo
echo "Hachi Smart DNS installed. / نصب شد."
echo "  DNS (give to customers / به مشتری بده): $SERVER_IP (primary + secondary)"
echo "  Registration service / سرویس ثبت:    http://$SERVER_IP:8792/health"
echo "  Admin panel / پنل ادمین:             http://$SERVER_IP:$PANEL_PORT  (first login: admin / admin — change it! / ورود اول: admin / admin — عوضش کن!)"
echo "  Add a customer / ساخت یوزر:          open the panel, or: python3 $INSTALL_DIR/dns_admin.py add 1 \"name\""
echo
echo "Manage services from the console / مدیریت سرویس‌ها از کنسول:"
echo "  systemctl restart unbound sniproxy hachi-dns-reg hachi-dns-panel   # restart all / ریستارت همه"
echo "  systemctl stop unbound    # stop DNS / خاموش کردن DNS"
echo "  systemctl start unbound   # start DNS / روشن کردن DNS"
echo "  systemctl status unbound  # check status / دیدن وضعیت"
echo "Or use the buttons in the admin panel: Services / یا دکمه‌ها داخل پنل: سرویس‌ها"
echo
echo "BEFORE SELLING / پیش از فروش:"
echo "  1. Put the registration service behind HTTPS with your own domain. / سرویس ثبت را با دامنهٔ خودت پشت HTTPS ببر."
echo "  2. Close the open resolver: allow only whitelisted customer IPs. / resolver باز را ببند: فقط آی‌پی‌های لیست سفید."
echo "  3. Never share customer codes in a group chat — private channel only. / کد مشتری را هیچ‌وقت در گروه نفرست — فقط چت خصوصی."
