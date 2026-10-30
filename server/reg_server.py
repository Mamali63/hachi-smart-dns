#!/usr/bin/env python3
"""Hachi Smart DNS registration service (v1, 2026-10-27).
Stdlib only. Listens on 0.0.0.0:8792 (HTTP, see note below).
Source of truth: customers.json in the same directory.
Rules (from the user, 2026-10-27):
- One customer = one /32 IP, rewrite not add: a new register replaces the
  old IP in the whitelist; the old IP is never kept.
- New code: first register starts the clock (start=now, end=start+months*30d).
- Old code, still active: register keeps start/end, only updates the IP.
- Old code, expired, without a renewal: register does NOT reset the clock
  and does NOT whitelist the IP; it returns status=expired.
- Counters are keyed by code, not by IP, so an IP change never resets them.
- The code itself carries no months/price/expiry; those live server-side.
NOTE on transport: v1 is plain HTTP on a direct IP (203.0.113.10:8792)
because the server has no TLS cert for a bare IP. Before selling, move
this behind https://dns.example.com (planned DoT/DoH domain) and close
the open Unbound resolver; see the project file. The code is a secret
and must only be sent to a customer over a private channel.
"""
import json, os, time, threading
try:
    os.environ["TZ"] = "Asia/Tehran"; time.tzset()
except Exception:
    pass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
CUSTOMERS = os.path.join(BASE, "customers.json")
WHITELIST_TXT = os.path.join(BASE, "whitelist.txt")
WHITELIST_JSON = os.path.join(BASE, "whitelist.json")
DNS_SERVERS = os.path.join(BASE, "dns_servers.json")
VERSION = os.path.join(BASE, "version.json")
PORT = 8792
DAY = 86400
LOCK = threading.Lock()

def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)

def load_customers():
    d = _load(CUSTOMERS, {})
    return d if isinstance(d, dict) else {}

def save_customers(d):
    _save_atomic(CUSTOMERS, d)

def dns_servers():
    d = _load(DNS_SERVERS, {})
    return {
        "primary": d.get("primary", "203.0.113.10"),
        "secondary": d.get("secondary", "203.0.113.10"),
    }

def version_info():
    d = _load(VERSION, {})
    return {"versionCode": d.get("versionCode", 1), "versionName": d.get("versionName", "1.0.0")}

def remaining(end_ts, now):
    if end_ts is None or end_ts <= now:
        return {"months": 0, "days": 0, "hours": 0, "total_seconds": 0}
    sec = int(end_ts - now)
    months = sec // (30 * DAY)
    sec -= months * 30 * DAY
    days = sec // DAY
    sec -= days * DAY
    hours = sec // 3600
    return {"months": months, "days": days, "hours": hours, "total_seconds": int(end_ts - now)}

def status_of(code, c, now):
    start, end = c.get("start_ts"), c.get("end_ts")
    if start is None:
        status = "not_started"
    elif end is not None and now > end:
        status = "expired"
    else:
        status = "active"
    out = {
        "code": code,
        "display_name": c.get("display_name", ""),
        "months": c.get("months", 0),
        "duration_hours": c.get("duration_hours"),
        "duration_days": c.get("duration_days"),
        "status": status,
        "start_ts": start,
        "end_ts": end,
        "start": time.strftime("%Y-%m-%d %H:%M", time.localtime(start)) if start else None,
        "end": time.strftime("%Y-%m-%d %H:%M", time.localtime(end)) if end else None,
        "remaining": remaining(end, now) if end else {"months": 0, "days": 0, "hours": 0, "total_seconds": 0},
        "current_ip": c.get("current_ip"),
        "total_bytes": c.get("total_bytes", 0),
    }
    out.update(dns_servers())
    return out

def rebuild_whitelist(customers):
    now = int(time.time())
    lines, items = [], []
    for code in sorted(customers):
        c = customers[code]
        ip = c.get("current_ip")
        if c.get("start_ts") and c.get("end_ts") and now <= c["end_ts"] and ip:
            lines.append(f"{ip}  # {code}\n")
            items.append({"code": code, "ip": ip})
    _save_atomic(WHITELIST_TXT, "".join(lines)) if False else None
    with open(WHITELIST_TXT, "w", encoding="utf-8") as f:
        f.writelines(lines)
    _save_atomic(WHITELIST_JSON, {"generated_ts": now, "whitelist": items})
    return items

class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.client_address[0]} {fmt % args}", flush=True)
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/health":
            return self._send({"ok": True, "service": "hachi-dns-reg", "time": int(time.time())})
        if p.path == "/dns-info":
            d = dns_servers(); d.update(version_info()); return self._send(d)
        if p.path == "/version":
            return self._send(version_info())
        if p.path == "/status":
            code = (parse_qs(p.query).get("code", [""])[0] or "").strip().lower()
            with LOCK:
                cs = load_customers()
            c = cs.get(code)
            if not c:
                return self._send({"error": "یوزر پیدا نشد"}, 404)
            return self._send(status_of(code, c, int(time.time())))
        return self._send({"error": "not found"}, 404)
    def do_POST(self):
        p = urlparse(self.path)
        if p.path != "/register":
            return self._send({"error": "not found"}, 404)
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(ln).decode("utf-8") or "{}")
        except Exception:
            return self._send({"error": "بدنهٔ JSON نامعتبر است"}, 400)
        code = str(body.get("code", "") or "").strip().lower()
        if not code:
            return self._send({"error": "کد خالی است"}, 400)
        client_ip = self.client_address[0]
        now = int(time.time())
        with LOCK:
            cs = load_customers()
            c = cs.get(code)
            if not c:
                return self._send({"error": "یوزر پیدا نشد"}, 404)
            months = int(c.get("months", 0) or 0)
            dur_h = c.get("duration_hours")
            dur_d = c.get("duration_days")
            if c.get("start_ts") is None:
                if dur_h:
                    dur_sec = int(dur_h) * 3600
                elif dur_d:
                    dur_sec = int(dur_d) * DAY
                elif months > 0:
                    dur_sec = months * 30 * DAY
                else:
                    return self._send({"error": "برای این کد مدتی ثبت نشده است"}, 400)
                c["start_ts"] = now
                c["end_ts"] = now + dur_sec
                first = True
            elif c.get("end_ts") is not None and now > c["end_ts"]:
                rebuild_whitelist(cs)
                st = status_of(code, c, now); st["first_start"] = False
                return self._send(st, 200)
            else:
                first = False
            c["current_ip"] = client_ip
            c["last_seen_ts"] = now
            save_customers(cs)
            rebuild_whitelist(cs)
            st = status_of(code, c, now); st["first_start"] = first
            return self._send(st, 200)

if __name__ == "__main__":
    os.makedirs(BASE, exist_ok=True)
    if not os.path.exists(CUSTOMERS):
        _save_atomic(CUSTOMERS, {})
    if not os.path.exists(DNS_SERVERS):
        _save_atomic(DNS_SERVERS, {"primary": "203.0.113.10", "secondary": "203.0.113.10"})
    if not os.path.exists(VERSION):
        _save_atomic(VERSION, {"versionCode": 1, "versionName": "1.0.0"})
    print(f"hachi-dns-reg on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
