#!/usr/bin/env python3
"""Hachi Smart DNS — admin panel (v1, 2026-10-30).
Stdlib only. Serves a small Persian RTL web panel for the buyer/admin:
  - users: list (full info), create (months or hours), renew, delete
  - games/domains: list, add, delete — every change regenerates the
    Unbound SNI table and reloads Unbound + Sniproxy at once
  - whitelist: last IP of each user, remove an IP, attach an IP to a user
  - settings: DNS addresses, whitelist view, change admin password
Auth: single admin. First run creates admin.json with password "admin"
and must_change=true — the panel shows a big warning until it is changed.
Change the password from inside the panel; the password is stored only
as a salted pbkdf2 hash, never in plain text, never in the repo.
Sessions live in memory (a restart logs the admin out).
Env overrides (for testing / custom installs):
  HACHI_PANEL_PORT (default 8080), HACHI_BIND (default 0.0.0.0),
  HACHI_SNI_CONF (default /etc/unbound/unbound.conf.d/hachi-sni.conf),
  HACHI_RELOAD (1 = reload services on domain change, 0 = skip).
Run:  python3 admin_panel.py   (systemd unit hachi-dns-panel.service)
"""
import hashlib
import hmac
import html
import ipaddress
import json
import re
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
CUSTOMERS = os.path.join(BASE, "customers.json")
DOMAINS = os.path.join(BASE, "domains.json")
DOMAINS_DEFAULT = os.path.join(BASE, "domains.default.json")
BLOCKED = os.path.join(BASE, "blocked.json")

SERVICES = [
    ("unbound", "Unbound", "ریزالور DNS — جواب پرس‌وجوها را می‌دهد"),
    ("sniproxy", "Sniproxy", "پراکسی SNI — بازی‌ها و یوتیوب از این رد می‌شوند"),
    ("hachi-dns-reg", "سرویس ثبت", "ثبت یوزر و لیست سفید (پورت 8792)"),
    ("hachi-dns-panel", "پنل ادمین", "همین پنل — خاموش‌کردنش پنل را می‌بندد"),
]
DNS_SERVERS = os.path.join(BASE, "dns_servers.json")
ADMIN_FILE = os.path.join(BASE, "admin.json")
WHITELIST_TXT = os.path.join(BASE, "whitelist.txt")
WHITELIST_JSON = os.path.join(BASE, "whitelist.json")
PORT = int(os.environ.get("HACHI_PANEL_PORT", "8080"))
BIND = os.environ.get("HACHI_BIND", "0.0.0.0")
SNI_CONF = os.environ.get("HACHI_SNI_CONF", "/etc/unbound/unbound.conf.d/hachi-sni.conf")
BLOCK_CONF = os.environ.get("HACHI_BLOCK_CONF", "/etc/unbound/unbound.conf.d/hachi-block.conf")
DO_RELOAD = os.environ.get("HACHI_RELOAD", "1") == "1"
DAY = 86400
LOCK = threading.RLock()  # reentrant: page builders also take LOCK, handlers call them while holding it
SESSIONS = {}  # token -> expiry ts


# ---------------------------------------------------------------- helpers
def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, (dict, list)) else default
    except Exception:
        return default


def _save_atomic(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def rebuild_whitelist(cs):
    """Regenerate whitelist.txt + whitelist.json from customers (source of truth).

    Only active users with a current IP are listed. Removing an IP means
    clearing that user's current_ip; adding one means attaching it to a user.
    """
    now = int(time.time())
    lines, items = [], []
    for code in sorted(cs):
        c = cs[code]
        ip = c.get("current_ip")
        if c.get("start_ts") and c.get("end_ts") and now <= c["end_ts"] and ip:
            lines.append(f"{ip}  # {code}\n")
            items.append({"code": code, "ip": ip})
    tmp = WHITELIST_TXT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, WHITELIST_TXT)
    _save_atomic(WHITELIST_JSON, {"generated_ts": now, "whitelist": items})
    return items


def esc(s):
    return html.escape("" if s is None else str(s))


def fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def status_of(c, now):
    start, end = c.get("start_ts"), c.get("end_ts")
    if start is None:
        return "شروع نشده"
    if end is not None and now > end:
        return "منقضی"
    return "فعال"


def remaining(end, now):
    if not end or end <= now:
        return "۰"
    sec = int(end - now)
    m = sec // (30 * DAY)
    sec -= m * 30 * DAY
    d = sec // DAY
    sec -= d * DAY
    h = sec // 3600
    parts = []
    if m:
        parts.append(f"{m} ماه")
    if d:
        parts.append(f"{d} روز")
    if h or not parts:
        parts.append(f"{h} ساعت")
    return " و ".join(parts)


# ------------------------------------------------------------------- auth
def _hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 200000).hex()


def ensure_admin():
    if os.path.exists(ADMIN_FILE):
        return
    salt = secrets.token_hex(16)
    _save_atomic(ADMIN_FILE, {
        "username": "admin",
        "salt": salt,
        "hash": _hash_pw("admin", salt),
        "must_change": True,
    })


def check_pw(pw):
    d = _load(ADMIN_FILE, {})
    if not d.get("salt") or not d.get("hash"):
        return False
    return hmac.compare_digest(_hash_pw(pw, d["salt"]), d["hash"])


def set_pw(new_pw):
    d = _load(ADMIN_FILE, {})
    salt = secrets.token_hex(16)
    d.update({"salt": salt, "hash": _hash_pw(new_pw, salt), "must_change": False})
    _save_atomic(ADMIN_FILE, d)


def make_session():
    tok = secrets.token_hex(24)
    SESSIONS[tok] = int(time.time()) + 2 * 3600
    return tok


def valid_session(headers):
    cookie = headers.get("Cookie") or ""
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("hachi_admin="):
            tok = part[len("hachi_admin="):]
            exp = SESSIONS.get(tok)
            if exp and exp > time.time():
                return True
            SESSIONS.pop(tok, None)
    return False


# ---------------------------------------------------------------- domains
def load_domains():
    d = _load(DOMAINS, [])
    return d if isinstance(d, list) else []


def server_ip():
    d = _load(DNS_SERVERS, {})
    return d.get("primary", "203.0.113.10")


def rebuild_sni():
    """Regenerate the Unbound SNI table from domains.json and reload."""
    domains = load_domains()
    ip = server_ip()
    lines = []
    for item in domains:
        dom = (item.get("domain") or "").strip().rstrip(".")
        mode = item.get("mode", "redirect")
        if not dom:
            continue
        if mode == "transparent":
            lines.append(f'    local-zone: "{dom}." transparent')
        else:
            lines.append(f'    local-zone: "{dom}." redirect')
            lines.append(f'    local-data: "{dom}. 300 IN A {ip}"')
    text = "server:\n" + "\n".join(lines) + "\n"
    try:
        os.makedirs(os.path.dirname(SNI_CONF) or ".", exist_ok=True)
        with open(SNI_CONF, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        return f"خطا در نوشتن فایل Unbound: {e}"
    if not DO_RELOAD:
        return "فایل Unbound بازسازی شد (بازخوانی سرویس‌ها خاموش است)."
    msgs = []
    for cmd in (["systemctl", "reload", "unbound"], ["systemctl", "restart", "sniproxy"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except Exception as e:
            msgs.append(f"{cmd[1]} {cmd[2]}: خطا/تایم‌اوت ({str(e)[:100]})")
            continue
        if r.returncode != 0:
            msgs.append(f"{cmd[1]} {cmd[2]}: {(r.stderr or r.stdout or '').strip()[:200]}")
    if msgs:
        return "فایل بازسازی شد ولی بازخوانی سرویس‌ها خطا داد: " + " | ".join(msgs)
    return "فایل Unbound بازسازی و سرویس‌ها بازخوانی شدند."


def rebuild_blocklist():
    """Regenerate the Unbound blocklist from blocked.json and reload Unbound.

    A blocked domain gets `local-zone ... static` with no data, so Unbound
    answers NXDOMAIN and the site does not open at all (not even via the
    server). Only Unbound is reloaded; sniproxy is untouched.
    """
    blocked = _load(BLOCKED, [])
    lines = []
    for dom in blocked:
        dom = (str(dom) or "").strip().rstrip(".").lower()
        if dom and "." in dom:
            lines.append(f'    local-zone: "{dom}." static')
    text = "server:\n" + ("\n".join(lines) + "\n" if lines else "")
    try:
        os.makedirs(os.path.dirname(BLOCK_CONF) or ".", exist_ok=True)
        with open(BLOCK_CONF, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        return f"خطا در نوشتن فایل بلاک: {e}"
    if not DO_RELOAD:
        return "فایل بلاک بازسازی شد (بازخوانی خاموش است)."
    try:
        r = subprocess.run(["systemctl", "reload", "unbound"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:
        return f"خطا/تایم‌اوت در بازخوانی Unbound: {str(e)[:100]}"
    if r.returncode != 0:
        return f"بازخوانی Unbound خطا داد: {(r.stderr or r.stdout or '').strip()[:200]}"
    return "لیست سیاه بازسازی و Unbound بازخوانی شد."


# ------------------------------------------------------------------- HTML
CSS = """
body{background:#0f172a;color:#e2e8f0;font-family:tahoma,arial,sans-serif;margin:0;padding:0}
.wrap{max-width:900px;margin:0 auto;padding:16px}
h1{font-size:20px;color:#38bdf8} h2{font-size:17px;color:#a5b4fc}
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin:12px 0}
.warn{background:#451a03;border:1px solid #f59e0b;border-radius:12px;padding:12px;margin:12px 0;color:#fde68a}
.ok{background:#052e16;border:1px solid #22c55e;border-radius:12px;padding:12px;margin:12px 0;color:#bbf7d0}
.err{background:#450a0a;border:1px solid #ef4444;border-radius:12px;padding:12px;margin:12px 0;color:#fecaca}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border-bottom:1px solid #334155;padding:8px 6px;text-align:right;vertical-align:top}
th{color:#94a3b8}
input,select{width:100%;padding:10px;margin:6px 0;border-radius:8px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:15px;box-sizing:border-box}
button{background:#0284c7;color:#fff;border:0;border-radius:8px;padding:10px 18px;font-size:15px;cursor:pointer;margin:4px 0}
button.danger{background:#b91c1c} button.ghost{background:#334155}
a{color:#38bdf8} nav a{margin-left:14px}
.row{display:flex;gap:10px}.row>*{flex:1}
.small{font-size:12px;color:#94a3b8}
"""


def page(title, body, nav=True):
    links = ""
    if nav:
        links = ('<nav><a href="/admin">یوزرها</a><a href="/admin/whitelist">لیست سفید</a><a href="/admin/games">بازی‌ها</a><a href="/admin/blocklist">لیست سیاه</a>'
                 '<a href="/admin/services">سرویس‌ها</a><a href="/admin/guide">آموزش بازی‌ها</a>'
                 '<a href="/admin/guide-app">آموزش نرم‌افزار</a>'
                 '<a href="/admin/settings">تنظیمات</a><a href="/admin/logout">خروج</a></nav>')
    return ("<!DOCTYPE html><html lang=\"fa\" dir=\"rtl\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body><div class=\"wrap\">"
            f"<h1>هاچی اسمارت دی‌ان‌اس — پنل ادمین</h1>{links}{body}</div>"
            "<script>function copyCode(btn,text){function done(){var o=btn.textContent;btn.textContent='کپی شد ✓';setTimeout(function(){btn.textContent=o;},1200);}function fb(){var ta=document.createElement('textarea');ta.value=text;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done();}catch(e){}document.body.removeChild(ta);}if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(done,fb);}else{fb();}}</script></body></html>")


def login_page(msg=""):
    m = f"<div class=\"err\">{esc(msg)}</div>" if msg else ""
    body = (f"{m}<div class=\"card\"><h2>ورود ادمین</h2>"
            "<form method=\"post\" action=\"/login\">"
            "<label>نام کاربری</label><input name=\"username\" value=\"admin\">"
            "<label>رمز عبور</label><input type=\"password\" name=\"password\" autofocus>"
            "<button>ورود</button></form>"
            "<p class=\"small\">ورود اول: admin / admin — بعد از اولین ورود، رمز را از تنظیمات عوض کنید.</p></div>")
    return page("ورود", body, nav=False)


def users_page(msg=""):
    now = int(time.time())
    with LOCK:
        cs = _load(CUSTOMERS, {})
    rows = ""
    for code in sorted(cs):
        c = cs[code]
        rows += ("<tr><td><b dir=\"ltr\">" + esc(code) + "</b> "
                 f"<button type=\"button\" onclick=\"copyCode(this,'{esc(code)}')\">کپی</button>"
                 "<br><span class=\"small\">" + esc(c.get("display_name", "")) + "</span></td>"
                 f"<td>{esc(c.get('months', 0))} ماه" + (f" / {esc(c.get('duration_hours'))} ساعت" if c.get("duration_hours") else "") + "</td>"
                 f"<td>{esc(status_of(c, now))}<br><span class=\"small\">{esc(fmt_ts(c.get('start_ts')))} ← {esc(fmt_ts(c.get('end_ts')))}</span><br><span class=\"small\">مانده: {esc(remaining(c.get('end_ts'), now))}</span></td>"
                 f"<td dir=\"ltr\">{esc(c.get('current_ip') or '-')}</td>"
                 f"<td>{esc(c.get('total_bytes', 0))}</td>"
                 "<td><form method=\"post\" action=\"/admin/users/renew\" style=\"display:inline\">"
                 f"<input type=\"hidden\" name=\"code\" value=\"{esc(code)}\">"
                 "<input name=\"months\" type=\"number\" value=\"1\" min=\"1\" style=\"width:60px\">"
                 "<button>تمدید</button></form> "
                 "<form method=\"post\" action=\"/admin/users/delete\" style=\"display:inline\" "
                 "onsubmit=\"return confirm('این یوزر پاک شود؟')\">"
                 f"<input type=\"hidden\" name=\"code\" value=\"{esc(code)}\">"
                 "<button class=\"danger\">حذف</button></form></td></tr>")
    if not rows:
        rows = "<tr><td colspan=\"6\">هنوز یوزری ساخته نشده است.</td></tr>"
    admin = _load(ADMIN_FILE, {})
    warn = ""
    if admin.get("must_change"):
        warn = ("<div class=\"warn\">⚠️ رمز ادمین هنوز <b>admin</b> است! همین حالا از "
                "<a href=\"/admin/settings\">تنظیمات</a> عوضش کنید.</div>")
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    body = (f"{warn}{m}<div class=\"card\"><h2>ساخت یوزر تازه</h2>"
            "<form method=\"post\" action=\"/admin/users/create\"><div class=\"row\">"
            "<div><label>نام نمایشی (اختیاری)</label><input name=\"name\"></div>"
            "<div><label>کد دلخواه (اختیاری)</label><input name=\"code\" dir=\"ltr\" placeholder=\"خالی = خودکار\"></div>"
            "<div><label>مدت (ماه)</label><input name=\"months\" type=\"number\" value=\"1\" min=\"1\"></div>"
            "<div><label>یا مدت (ساعت)</label><input name=\"hours\" type=\"number\" min=\"1\" placeholder=\"مثلاً 24\"></div>"
            "</div><button>ساختن یوزر</button>"
            "<p class=\"small\">برای امنیت بهتر، کد را خالی بگذارید تا خودکار و تصادفی ساخته شود (۵ کاراکتر). اگر خودتان می‌نویسید، هر چیزی می‌توانید بنویسید. ساعت یوزر با اولین استارت در برنامه شروع می‌شود، نه با ساختن.</p></form></div>"
            "<div class=\"card\"><h2>یوزرها</h2><table><tr><th>یوزر / نام</th><th>مدت</th><th>وضعیت و تاریخ</th><th>آی‌پی</th><th>حجم</th><th>کار</th></tr>"
            f"{rows}</table></div>")
    return page("یوزرها", body)


def whitelist_page(msg=""):
    now = int(time.time())
    with LOCK:
        cs = _load(CUSTOMERS, {})
    items = rebuild_whitelist(cs)  # refresh both files so the page never shows a stale list
    rows = ""
    for it in items:
        c = cs.get(it["code"], {})
        rows += ("<tr><td dir=\"ltr\">" + esc(it["ip"]) + "</td>"
                 "<td dir=\"ltr\">" + esc(it["code"]) + "</td>"
                 "<td>" + esc(c.get("display_name", "")) + "</td>"
                 f"<td>{esc(fmt_ts(c.get('last_seen_ts')))}<br><span class=\"small\">مانده: {esc(remaining(c.get('end_ts'), now))}</span></td>"
                 "<td><form method=\"post\" action=\"/admin/whitelist/remove\" onsubmit=\"return confirm('این آی‌پی از لیست سفید پاک شود؟ یوزر باید دوباره ثبت کند.')\">"
                 f"<input type=\"hidden\" name=\"code\" value=\"{esc(it['code'])}\">"
                 "<button class=\"danger\">حذف آی‌پی</button></form></td></tr>")
    if not rows:
        rows = "<tr><td colspan=\"5\">لیست سفید خالی است — هنوز هیچ یوزری وصل نشده است.</td></tr>"
    opts = "".join(
        f"<option value=\"{esc(code)}\">{esc(code)} ({esc(cs[code].get('display_name', ''))})</option>"
        for code in sorted(cs))
    if not opts:
        opts = "<option value=\"\">— یوزری نیست —</option>"
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    body = (f"{m}<div class=\"card\"><h2>لیست سفید</h2>"
            "<p class=\"small\">لیست سفید از روی یوزرها ساخته می‌شود: فقط یوزرهای فعال که وصل شده‌اند اینجا هستند. "
            "حذف آی‌پی یعنی آن آی‌پی از آن یوزر پاک می‌شود و یوزر باید دوباره در برنامه استارت بزند تا برگردد. "
            "افزودن آی‌پی یعنی یک آی‌پی را به یک یوزر وصل می‌کنی؛ اگر یوزر هنوز شروع نکرده باشد، آی‌پی تا اولین ثبت او فعال نمی‌شود.</p>"
            "<table><tr><th>آی‌پی</th><th>یوزر</th><th>نام</th><th>آخرین اتصال</th><th>کار</th></tr>"
            f"{rows}</table></div>"
            "<div class=\"card\"><h2>افزودن آی‌پی به لیست سفید</h2>"
            "<form method=\"post\" action=\"/admin/whitelist/add\"><div class=\"row\">"
            f"<div><label>یوزر</label><select name=\"code\">{opts}</select></div>"
            "<div><label>آی‌پی</label><input name=\"ip\" dir=\"ltr\" placeholder=\"مثلاً 1.2.3.4\"></div>"
            "</div><button>افزودن آی‌پی</button></form></div>")
    return page("لیست سفید", body)


def games_page(msg=""):
    domains = load_domains()
    rows = ""
    for i, item in enumerate(domains):
        rows += ("<tr><td dir=\"ltr\">" + esc(item.get("domain", "")) + "</td>"
                 f"<td>{esc(item.get('category', ''))}</td>"
                 f"<td>{'عبور مستقیم' if item.get('mode') == 'transparent' else 'از سرور'}</td>"
                 "<td><form method=\"post\" action=\"/admin/games/delete\" onsubmit=\"return confirm('این دامنه پاک شود؟')\">"
                 f"<input type=\"hidden\" name=\"idx\" value=\"{i}\"><button class=\"danger\">حذف</button></form></td></tr>")
    if not rows:
        rows = "<tr><td colspan=\"4\">فهرست خالی است.</td></tr>"
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    body = (f"{m}<div class=\"card\"><h2>افزودن بازی / دامنه</h2>"
            "<form method=\"post\" action=\"/admin/games/add\"><div class=\"row\">"
            "<div><label>دامنه (مثلاً steam.com)</label><input name=\"domain\" dir=\"ltr\" placeholder=\"example.com\"></div>"
            "<div><label>دسته</label><input name=\"category\" placeholder=\"بازی\"></div>"
            "<div><label>حالت</label><select name=\"mode\"><option value=\"redirect\">از سرور</option>"
            "<option value=\"transparent\">عبور مستقیم</option></select></div>"
            "</div><button>افزودن</button>"
            "<p class=\"small\">با هر تغییر، جدول Unbound همان لحظه بازسازی و سرویس‌ها بازخوانی می‌شوند. دامنهٔ پایه، زیردامنه‌هایش را هم می‌گیرد.</p></form></div>"
            "<div class=\"card\"><h2>فهرست بازی‌ها و دامنه‌ها</h2>"
            "<form method=\"post\" action=\"/admin/games/reset\" onsubmit=\"return confirm('فهرست به دیفالت برگردد؟ اضافه‌های خودت پاک می‌شوند.')\">"
            "<button class=\"ghost\">↩ برگشت به دیفالت</button></form>"
            "<table>"
            "<tr><th>دامنه</th><th>دسته</th><th>حالت</th><th>کار</th></tr>"
            f"{rows}</table></div>")
    return page("بازی‌ها", body)


def blocklist_page(msg=""):
    blocked = _load(BLOCKED, [])
    rows = ""
    for i, dom in enumerate(blocked):
        rows += ("<tr><td dir=\"ltr\">" + esc(dom) + "</td>"
                 "<td><form method=\"post\" action=\"/admin/blocklist/delete\" onsubmit=\"return confirm('این دامنه از لیست سیاه پاک شود؟')\">"
                 f"<input type=\"hidden\" name=\"idx\" value=\"{i}\"><button class=\"danger\">حذف (باز کردن)</button></form></td></tr>")
    if not rows:
        rows = "<tr><td colspan=\"2\">لیست سیاه خالی است — همهٔ سایت‌ها باز می‌شوند.</td></tr>"
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    body = (f"{m}<div class=\"card\"><h2>افزودن به لیست سیاه</h2>"
            "<form method=\"post\" action=\"/admin/blocklist/add\"><div class=\"row\">"
            "<div><label>دامنه (مثلاً fortnite.com)</label><input name=\"domain\" dir=\"ltr\" placeholder=\"example.com\"></div>"
            "</div><button>بلاک کردن</button>"
            "<p class=\"small\">دامنه‌های این فهرست <b>اصلاً باز نمی‌شوند</b> — DNS برایشان جواب نمی‌دهد (NXDOMAIN). "
            "برای تست اینکه DNS کار می‌کند، یک سایت را اینجا بلاک کن: اگر باز نشد یعنی DNS دارد کار می‌دهد؛ "
            "با حذف از این فهرست دوباره باز می‌شود. دامنهٔ پایه، زیردامنه‌هایش را هم می‌گیرد.</p></form></div>"
            "<div class=\"card\"><h2>لیست سیاه</h2>"
            "<table><tr><th>دامنه</th><th>کار</th></tr>"
            f"{rows}</table></div>")
    return page("لیست سیاه", body)


def guide_page():
    body = """<div class="card"><h2>آدرس بازی‌ها را چطور پیدا کنم؟</h2>
<p>برای اینکه یک بازی از سرور رد شود، باید دامنه‌هایی که موقع ورود (لاگین) می‌پرسد را پیدا کنی و در صفحهٔ <a href="/admin/games">بازی‌ها</a> اضافه کنی. چهار راه دارد:</p></div>
<div class="card"><h2>روش ۱ — لاگ سرور (دقیق‌ترین راه)</h2>
<ol>
<li>DNS دستگاه (پلی‌استیشن، گوشی یا کامپیوتر) را بگذار روی آی‌پی همین سرور.</li>
<li>وارد بازی شو و دکمهٔ ورود / لاگین را بزن — حتی اگر خطا بدهد، بازی دامنه‌ها را پرسیده است.</li>
<li>روی سرور لاگ را ببین (لاگ پرس‌وجو روشن است):<br><code dir="ltr">journalctl -u unbound --since "10 minutes ago" | grep query:</code><br>
اگر آنجا چیزی نبود: <code dir="ltr">grep "query:" /var/log/syslog</code></li>
<li>خط‌هایی که <code dir="ltr">query:</code> دارند، دامنه‌های بازی‌اند. دامنه‌های مال بازی را بردار؛ تبلیغات و دامنه‌های سیستمی گوشی را نه.</li>
</ol></div>
<div class="card"><h2>روش ۲ — گوشی اندروید (PCAPdroid، رایگان)</h2>
<ol>
<li>برنامهٔ PCAPdroid را نصب کن و گرفتن DNS را روشن کن.</li>
<li>وارد بازی شو و لاگین بزن.</li>
<li>در فهرست DNS، دامنه‌هایی که همان موقع پرسیده شده‌اند مال بازی‌اند.</li>
</ol></div>
<div class="card"><h2>روش ۳ — کامپیوتر (Wireshark، رایگان)</h2>
<ol>
<li>Wireshark را باز کن و فیلتر <code dir="ltr">dns</code> را بزن.</li>
<li>وارد بازی شو و لاگین بزن.</li>
<li>در ستون Query دامنه‌ها را ببین.</li>
</ol></div>
<div class="card"><h2>روش ۴ — حدس هوشمند</h2>
<p>دامنهٔ اصلی بازی + زیردامنه‌های <code dir="ltr">account</code> ،<code dir="ltr">auth</code> ،<code dir="ltr">login</code> ،<code dir="ltr">api</code> + دامنهٔ شرکت سازنده. مثال: برای فورتنایت فقط <code dir="ltr">epicgames.com</code> کافی بود.</p></div>
<div class="card"><h2>بعد از پیدا کردن</h2>
<ol>
<li>فقط <b>دامنهٔ پایه</b> را در پنل اضافه کن — زیردامنه‌ها خودشان می‌آیند.</li>
<li>حالت «از سرور» برای لاگین و احراز هویت؛ حالت «عبور مستقیم» برای دانلود و CDN (مثل akamaized.net).</li>
<li>تست کن؛ اگر باز نشد، دوباره لاگ را ببین — معمولاً یک دامنه جا مانده است.</li>
</ol></div>
<div class="card"><h2>هشدارها</h2>
<ul>
<li>دامنهٔ خیلی کلی اضافه نکن — کل google.com نه، فقط accounts.google.com.</li>
<li>CDN دانلود را «از سرور» نکن؛ مستقیم بماند تا ترافیک از سرور رد نشود و کند نشود.</li>
</ul></div>"""
    return page("آموزش", body)


def guide_app_page():
    body = """<div class="card"><h2>آموزش نرم‌افزار اندروید — برای مشتری</h2>
<p>این آموزش را به مشتری بدهید (یا خودتان بخوانید و به او بگویید). نرم‌افزار <b>VPN نیست</b> و ترافیک را رد نمی‌کند؛ فقط آی‌پی خانهٔ مشتری را به سرور خبر می‌دهد تا توی لیست سفید برود.</p></div>
<div class="card"><h2>اولین ورود</h2>
<ol>
<li>نرم‌افزار را از لینکی که ادمین داده نصب کنید.</li>
<li>کد یوزر را که ادمین داده وارد کنید و <b>استارت</b> را بزنید.</li>
<li>ساعت اشتراک از <b>همین لحظه</b> شروع می‌شود — نه از وقتی که یوزر ساخته شده است.</li>
</ol></div>
<div class="card"><h2>صفحهٔ اصلی چی نشان می‌دهد؟</h2>
<ul>
<li><b>یوزر</b> و <b>وضعیت</b> (فعال / منقضی / شروع نشده)</li>
<li><b>تاریخ شروع و پایان</b> اشتراک</li>
<li><b>آی‌پی فعلی</b> خانهٔ شما</li>
<li><b>باقی‌مانده</b> به‌صورت ماه و روز و ساعت</li>
</ul></div>
<div class="card"><h2>دکمه‌ها یعنی چه؟</h2>
<ul>
<li><b>استارت:</b> ثبت آی‌پی خانه در سرور و شروع / به‌روز کردن وضعیت. این دکمهٔ اصلی است.</li>
<li><b>ریفرش:</b> گرفتن آی‌پی DNS تازهٔ <b>سرور ما</b> — مال شما نیست؛ فقط وقتی سرور عوض شده باشد لازم است.</li>
<li><b>آپدیت:</b> به‌روز کردن نسخهٔ خود برنامه.</li>
</ul></div>
<div class="card"><h2>قانون طلایی — حتماً روی وای‌فای خانه</h2>
<p>برنامه باید روی <b>همان وای‌فای خانه</b> باز شود، <b>نه اینترنت موبایل</b>. چون سرور همان آی‌پی‌ای را ثبت می‌کند که درخواست از آن آمده است؛ با اینترنت موبایل، آی‌پی موبایل ثبت می‌شود و پلی‌استیشن — که روی وای‌فای خانه است — وصل نمی‌شود.</p></div>
<div class="card"><h2>هر بار که وصل نشد، چه کار کنم؟</h2>
<ol>
<li>مطمئن شوید روی <b>وای‌فای خانه</b> هستید (نه اینترنت موبایل).</li>
<li>برنامه را باز کنید و <b>استارت</b> را بزنید تا آی‌پی تازه توی لیست سفید بیاید.</li>
<li>چند ثانیه صبر کنید، بعد دوباره وارد بازی شوید.</li>
</ol>
<p>هر بار که مودم خاموش‌روشن می‌شود یا آی‌پی خانه عوض می‌شود، همین کار لازم است. آی‌پی قبلی همان یوزر پاک می‌شود و آی‌پی تازه جای آن می‌نشیند؛ <b>ساعت و حجم صفر نمی‌شوند.</b></p></div>
<div class="card"><h2>اگر باز هم وصل نشد</h2>
<ol>
<li>وای‌فای خانه است؟ (نه موبایل)</li>
<li>اشتراک فعال است یا منقضی؟ تاریخ پایان را ببینید؛ اگر منقضی است، تمدید لازم است — با ادمین تماس بگیرید.</li>
<li>DNS پلی‌استیشن هر دو همان آدرسی است که ادمین داده؟ (Primary و Secondary هر دو، بعد خاموش‌روشن کامل، نه Rest Mode؛ Secondary هرگز به 8.8.8.8 برنگردد.)</li>
<li>دوباره استارت بزنید و چند ثانیه صبر کنید.</li>
</ol></div>
<div class="card"><h2>نکته‌ها</h2>
<ul>
<li>برنامه لازم نیست همیشه روشن بماند؛ فقط موقع ثبت لازم است.</li>
<li>حجم را برنامه نمی‌بیند؛ فقط سرور می‌شمرد.</li>
<li>کد یوزر را به کسی ندهید — هر کس آن را وارد کند، به اشتراک شما وصل می‌شود.</li>
</ul></div>"""
    return page("آموزش نرم‌افزار", body)


def svc_status(unit):
    # sniproxy is a forking daemon without Type=forking, so systemd reports
    # it "inactive" even while it serves traffic on 443/80. Check the
    # process itself instead — if the daemon runs, it is active.
    if unit == "sniproxy":
        try:
            r = subprocess.run(["pgrep", "-x", "sniproxy"], timeout=10,
                               capture_output=True)
            return "فعال" if r.returncode == 0 else "خاموش"
        except Exception:
            pass
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", unit],
                           timeout=10)
        return "فعال" if r.returncode == 0 else "خاموش"
    except Exception:
        return "نامشخص"


def svc_action(unit, action):
    """Run systemctl start/stop/restart for an allow-listed unit.

    The panel itself needs a delayed call, otherwise it kills its own
    process before the answer is sent.
    """
    if unit == "hachi-dns-panel" and action in ("restart", "stop"):
        subprocess.Popen(["bash", "-c", f"sleep 1; systemctl {action} hachi-dns-panel"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if action == "restart":
            return "پنل در حال ریستارت است — چند ثانیه صبر کنید و صفحه را تازه کنید."
        return "پنل در حال خاموش شدن است — برای روشن‌کردن دوباره از کنسول: systemctl start hachi-dns-panel"
    try:
        r = subprocess.run(["systemctl", action, unit], timeout=30,
                           capture_output=True, text=True)
    except Exception as e:
        return f"خطا: {e}"
    if r.returncode == 0:
        return ""
    return f"خطا: {(r.stderr or r.stdout or '').strip()}"


def services_page(msg=""):
    rows = ""
    for unit, label, desc in SERVICES:
        st = svc_status(unit)
        rows += (f"<tr><td><b>{esc(label)}</b><br><span class=\"small\">{esc(desc)}</span>"
                 f"<br><code dir=\"ltr\">{esc(unit)}</code></td>"
                 f"<td>{st}</td><td>"
                 f"<form method=\"post\" action=\"/admin/services/action\" style=\"display:inline\">"
                 f"<input type=\"hidden\" name=\"service\" value=\"{esc(unit)}\">"
                 f"<button name=\"action\" value=\"start\" class=\"ghost\">🟢 روشن</button>"
                 f"<button name=\"action\" value=\"restart\" class=\"ghost\">🔄 ریستارت</button>"
                 f"<button name=\"action\" value=\"stop\" class=\"ghost\" "
                 f"onclick=\"return confirm('«{esc(label)}» خاموش شود؟')\">🔴 خاموش</button>"
                 f"</form></td></tr>")
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    return page("سرویس‌ها",
        (f"{m}<div class=\"card\"><h2>سرویس‌ها</h2>"
         "<p class=\"small\">اگر DNS کار نمی‌کند، معمولاً ریستارت همین سرویس‌ها کافی است. "
         "خاموش‌کردن Unbound یعنی DNS برای همهٔ مشتری‌ها قطع می‌شود.</p>"
         "<table><tr><th>سرویس</th><th>وضعیت</th><th>کار</th></tr>"
         f"{rows}</table></div>"))


def settings_page(msg="", err=""):
    with LOCK:
        cs = _load(CUSTOMERS, {})
    wl = []
    now = int(time.time())
    for code in sorted(cs):
        c = cs[code]
        ip = c.get("current_ip")
        if c.get("start_ts") and c.get("end_ts") and now <= c["end_ts"] and ip:
            wl.append(f"<tr><td dir=\"ltr\">{esc(ip)}</td><td>{esc(code)}</td></tr>")
    dns = _load(DNS_SERVERS, {})
    m = f"<div class=\"ok\">{esc(msg)}</div>" if msg else ""
    e = f"<div class=\"err\">{esc(err)}</div>" if err else ""
    w = ""
    if _load(ADMIN_FILE, {}).get("must_change"):
        w = ("<div class=\"warn\">⚠️ رمز ادمین هنوز <b>admin</b> است و پنل تا عوض‌شدن آن قفل است. "
             "همین حالا زیر رمز تازه را بزنید.</div>")
    body = (f"{m}{e}{w}<div class=\"card\"><h2>تغییر رمز ادمین</h2>"
            "<form method=\"post\" action=\"/admin/settings/password\">"
            "<label>رمز فعلی</label><input type=\"password\" name=\"old\">"
            "<label>رمز تازه</label><input type=\"password\" name=\"new\">"
            "<label>تکرار رمز تازه</label><input type=\"password\" name=\"new2\">"
            "<button>عوض کردن رمز</button></form></div>"
            "<div class=\"card\"><h2>آدرس‌های DNS</h2>"
            "<form method=\"post\" action=\"/admin/settings/dns\"><div class=\"row\">"
            f"<div><label>اولیه</label><input name=\"primary\" dir=\"ltr\" value=\"{esc(dns.get('primary', ''))}\"></div>"
            f"<div><label>ثانویه</label><input name=\"secondary\" dir=\"ltr\" value=\"{esc(dns.get('secondary', ''))}\"></div>"
            "</div><button>ذخیره</button></form></div>"
            "<div class=\"card\"><h2>لیست سفید فعلی</h2><table><tr><th>آی‌پی</th><th>یوزر</th></tr>"
            + ("".join(wl) if wl else "<tr><td colspan=\"2\">خالی است.</td></tr>") + "</table></div>")
    return page("تنظیمات", body)


def must_change_pw():
    """True while the admin password is still the default (admin/admin).

    Until it is changed, the panel is locked: every admin page redirects
    to Settings and every admin action is refused. Default credentials
    left usable are the first thing anyone criticises in a release.
    """
    return bool(_load(ADMIN_FILE, {}).get("must_change"))


# ---------------------------------------------------------------- handlers
class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.client_address[0]} {fmt % args}", flush=True)

    def _html(self, body, code=200, cookie=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def _redir(self, loc, cookie=None):
        self.send_response(303)
        self.send_header("Location", loc)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _form(self):
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(ln).decode("utf-8") if ln else ""
        except Exception:
            raw = ""
        return {k: v[0] for k, v in parse_qs(raw).items()}

    def _need_auth(self):
        if valid_session(self.headers):
            return True
        self._redir("/")
        return False

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/health":
            data = b'{"ok": true, "service": "hachi-dns-panel"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if p == "/":
            if valid_session(self.headers):
                return self._redir("/admin")
            return self._html(login_page())
        if p == "/admin/logout":
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("hachi_admin="):
                    SESSIONS.pop(part[len("hachi_admin="):], None)
            return self._redir("/", cookie="hachi_admin=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
        if not self._need_auth():
            return
        if must_change_pw() and p != "/admin/settings":
            return self._redir("/admin/settings")
        if p == "/admin":
            return self._html(users_page())
        if p == "/admin/games":
            return self._html(games_page())
        if p == "/admin/blocklist":
            return self._html(blocklist_page())
        if p == "/admin/whitelist":
            return self._html(whitelist_page())
        if p == "/admin/guide":
            return self._html(guide_page())
        if p == "/admin/guide-app":
            return self._html(guide_app_page())
        if p == "/admin/services":
            return self._html(services_page())
        if p == "/admin/settings":
            return self._html(settings_page())
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        p = urlparse(self.path).path
        f = self._form()
        if p == "/login":
            if (f.get("username") or "").strip() == "admin" and check_pw(f.get("password") or ""):
                tok = make_session()
                cookie = f"hachi_admin={tok}; Path=/; Max-Age=7200; HttpOnly; SameSite=Lax"
                return self._redir("/admin", cookie=cookie)
            return self._html(login_page("نام کاربری یا رمز اشتباه است."))
        if not self._need_auth():
            return
        if must_change_pw() and p != "/admin/settings/password":
            return self._html(settings_page("", "اول رمز ادمین را عوض کنید — تا وقتی رمز admin است، پنل قفل است."))
        now = int(time.time())
        if p == "/admin/users/create":
            name = (f.get("name") or "").strip()
            hours = (f.get("hours") or "").strip()
            months = (f.get("months") or "1").strip()
            manual = (f.get("code") or "").strip().lower()
            with LOCK:
                cs = _load(CUSTOMERS, {})
                if manual:
                    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", manual):
                        msg = "کد دلخواه درست نیست — فقط حروف و عدد و خط تیره، بدون فاصله."
                    elif manual in cs:
                        msg = "این کد از قبل هست — یکی دیگر بنویسید یا خالی بگذارید."
                    else:
                        code = manual
                        msg = None
                else:
                    while True:
                        code = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(5))
                        if code not in cs:
                            break
                    msg = None
                if msg is None:
                    rec = {"display_name": name, "months": 0, "start_ts": None, "end_ts": None,
                           "current_ip": None, "total_bytes": 0, "created_ts": now, "last_seen_ts": None}
                    if hours.isdigit() and int(hours) > 0:
                        rec["duration_hours"] = int(hours)
                    else:
                        rec["months"] = int(months) if months.isdigit() and int(months) > 0 else 1
                    cs[code] = rec
                    _save_atomic(CUSTOMERS, cs)
                    msg = f"یوزر ساخته شد: {code}"
            return self._html(users_page(msg))
        if p == "/admin/users/delete":
            code = (f.get("code") or "").strip().lower()
            with LOCK:
                cs = _load(CUSTOMERS, {})
                if code in cs:
                    del cs[code]
                    _save_atomic(CUSTOMERS, cs)
                    rebuild_whitelist(cs)
                    msg = f"یوزر {code} پاک شد."
                else:
                    msg = "یوزر پیدا نشد."
            return self._html(users_page(msg))
        if p == "/admin/users/renew":
            code = (f.get("code") or "").strip().lower()
            months = int(f.get("months") or 1) if (f.get("months") or "1").isdigit() else 1
            with LOCK:
                cs = _load(CUSTOMERS, {})
                c = cs.get(code)
                if not c:
                    msg = "یوزر پیدا نشد."
                else:
                    c["months"] = int(c.get("months", 0)) + months
                    if c.get("start_ts") is None:
                        pass
                    elif c.get("end_ts") and now > c["end_ts"]:
                        c["end_ts"] = now + months * 30 * DAY
                    else:
                        c["end_ts"] = int(c["end_ts"]) + months * 30 * DAY
                    _save_atomic(CUSTOMERS, cs)
                    msg = f"یوزر {code} {months} ماه تمدید شد."
            return self._html(users_page(msg))
        if p == "/admin/whitelist/remove":
            code = (f.get("code") or "").strip().lower()
            with LOCK:
                cs = _load(CUSTOMERS, {})
                c = cs.get(code)
                if not c:
                    msg = "یوزر پیدا نشد."
                else:
                    ip = c.get("current_ip") or "-"
                    c["current_ip"] = None
                    _save_atomic(CUSTOMERS, cs)
                    rebuild_whitelist(cs)
                    msg = f"آی‌پی {ip} از لیست سفید پاک شد (یوزر {code} باید دوباره ثبت کند)."
            return self._html(whitelist_page(msg))
        if p == "/admin/whitelist/add":
            code = (f.get("code") or "").strip().lower()
            ip = (f.get("ip") or "").strip()
            try:
                ip = str(ipaddress.IPv4Address(ip))
            except Exception:
                return self._html(whitelist_page("آی‌پی درست نیست — چهار عدد با نقطه، مثلاً 1.2.3.4."))
            with LOCK:
                cs = _load(CUSTOMERS, {})
                c = cs.get(code)
                if not c:
                    msg = "یوزر پیدا نشد."
                    items = []
                else:
                    c["current_ip"] = ip
                    _save_atomic(CUSTOMERS, cs)
                    items = rebuild_whitelist(cs)
            if not c:
                return self._html(whitelist_page(msg))
            if c.get("start_ts") is None:
                note = "آی‌پی به یوزر وصل شد ولی چون یوزر هنوز شروع نکرده، تا اولین ثبت او در لیست سفید فعال نمی‌شود."
            elif c.get("end_ts") and now > c["end_ts"]:
                note = "آی‌پی به یوزر وصل شد ولی یوزر منقضی است؛ تا تمدید نشود در لیست سفید نیست."
            elif any(it["code"] == code for it in items):
                note = f"آی‌پی {ip} به لیست سفید اضافه شد (یوزر {code})."
            else:
                note = f"آی‌پی {ip} به یوزر {code} وصل شد."
            return self._html(whitelist_page(note))
        if p == "/admin/games/add":
            dom = (f.get("domain") or "").strip().lower().rstrip(".")
            cat = (f.get("category") or "بازی").strip()
            mode = f.get("mode") or "redirect"
            if not dom or "." not in dom:
                return self._html(games_page("دامنه درست نیست."))
            with LOCK:
                domains = load_domains()
                if any((d.get("domain") or "").lower() == dom for d in domains):
                    return self._html(games_page("این دامنه از قبل هست."))
                blocked = _load(BLOCKED, [])
                if dom in [str(b).lower() for b in blocked]:
                    return self._html(games_page("این دامنه توی لیست سیاه است — اول از آنجا پاکش کنید."))
                domains.append({"domain": dom, "category": cat, "mode": mode})
                _save_atomic(DOMAINS, domains)
                msg = rebuild_sni()
            return self._html(games_page(f"{dom} اضافه شد. {msg}"))
        if p == "/admin/games/delete":
            idx = f.get("idx") or ""
            with LOCK:
                domains = load_domains()
                if not idx.isdigit() or int(idx) >= len(domains):
                    return self._html(games_page("ردیف پیدا نشد."))
                dom = domains[int(idx)].get("domain", "")
                del domains[int(idx)]
                _save_atomic(DOMAINS, domains)
                msg = rebuild_sni()
            return self._html(games_page(f"{dom} پاک شد. {msg}"))
        if p == "/admin/games/reset":
            with LOCK:
                defaults = _load(DOMAINS_DEFAULT, [])
                if not defaults:
                    return self._html(games_page("فایل دیفالت پیدا نشد."))
                _save_atomic(DOMAINS, defaults)
                msg = rebuild_sni()
            return self._html(games_page(f"فهرست به دیفالت برگشت ({len(defaults)} دامنه). {msg}"))
        if p == "/admin/blocklist/add":
            dom = (f.get("domain") or "").strip().lower().rstrip(".")
            if not dom or "." not in dom:
                return self._html(blocklist_page("دامنه درست نیست."))
            with LOCK:
                domains = load_domains()
                if any((d.get("domain") or "").lower() == dom for d in domains):
                    msg = "این دامنه توی لیست بازی‌هاست (از سرور رد می‌شود) — اول از آنجا پاکش کنید."
                else:
                    blocked = _load(BLOCKED, [])
                    if dom in [str(b).lower() for b in blocked]:
                        msg = "این دامنه از قبل توی لیست سیاه است."
                    else:
                        blocked.append(dom)
                        _save_atomic(BLOCKED, blocked)
                        msg = f"{dom} بلاک شد. {rebuild_blocklist()}"
            return self._html(blocklist_page(msg))
        if p == "/admin/blocklist/delete":
            idx = f.get("idx") or ""
            with LOCK:
                blocked = _load(BLOCKED, [])
                if not idx.isdigit() or int(idx) >= len(blocked):
                    msg = "ردیف پیدا نشد."
                else:
                    dom = blocked[int(idx)]
                    del blocked[int(idx)]
                    _save_atomic(BLOCKED, blocked)
                    msg = f"{dom} از لیست سیاه پاک شد (دوباره باز می‌شود). {rebuild_blocklist()}"
            return self._html(blocklist_page(msg))
        if p == "/admin/services/action":
            unit = f.get("service") or ""
            action = f.get("action") or ""
            units = {u for u, _, _ in SERVICES}
            if unit not in units or action not in ("start", "stop", "restart"):
                return self._html(services_page("سرویس یا دستور درست نیست."))
            label = next(l for u, l, _ in SERVICES if u == unit)
            err = svc_action(unit, action)
            if err:
                return self._html(services_page(err))
            verbs = {"start": "روشن شد", "stop": "خاموش شد", "restart": "ریستارت شد"}
            return self._html(services_page(f"«{label}» {verbs[action]}."))
        if p == "/admin/settings/dns":
            prim = (f.get("primary") or "").strip()
            sec = (f.get("secondary") or "").strip()
            if prim and sec:
                _save_atomic(DNS_SERVERS, {"primary": prim, "secondary": sec})
                return self._html(settings_page("آدرس‌های DNS ذخیره شد."))
            return self._html(settings_page("", "هر دو آدرس را وارد کنید."))
        if p == "/admin/settings/password":
            old, new, new2 = f.get("old") or "", f.get("new") or "", f.get("new2") or ""
            if not check_pw(old):
                return self._html(settings_page("", "رمز فعلی اشتباه است."))
            if len(new) < 6:
                return self._html(settings_page("", "رمز تازه دست‌کم ۶ کاراکتر باشد."))
            if new != new2:
                return self._html(settings_page("", "تکرار رمز با رمز تازه یکی نیست."))
            set_pw(new)
            return self._html(settings_page("رمز عوض شد."))
        self.send_response(404)
        self.end_headers()


if __name__ == "__main__":
    os.makedirs(BASE, exist_ok=True)
    ensure_admin()
    if not os.path.exists(CUSTOMERS):
        _save_atomic(CUSTOMERS, {})
    if not os.path.exists(DOMAINS):
        _save_atomic(DOMAINS, [])
    if not os.path.exists(BLOCKED):
        _save_atomic(BLOCKED, [])
    print(rebuild_blocklist(), flush=True)
    print(f"hachi-dns-panel on {BIND}:{PORT} (first login: admin / admin — change it!)", flush=True)
    ThreadingHTTPServer((BIND, PORT), H).serve_forever()
