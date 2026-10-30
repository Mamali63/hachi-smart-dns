# Hachi Smart DNS — هچی اسمارت دی‌ان‌اس

[English](README.md) | **فارسی**

سرویس ثبت و مدیریت Smart DNS با لیست سفید تک‌آی‌پی — برای رد کردن لاگین و لابی بازی‌ها (پلی‌استیشن، فورتنایت، یوتیوب) از سرور شما، بدون VPN و بدون رد کردن ترافیک بازی.

> **وضعیت:** نسخهٔ اول — هستهٔ پایتون (سرور ثبت + مدیریت ادمین + پاک‌سازی انقضا) + نمونهٔ پیکربندی. اسکریپت نصب خودکار، پنل ادمین و نرم‌افزار اندروید در آپدیت بعدی می‌آیند.

## این چیست؟

- **سرور ثبت** (`server/reg_server.py`): سرویس HTTP با فقط کتابخانهٔ استاندارد پایتون، پورت ۸۷۹۲. هر مشتری یک کد دارد؛ با اولین ثبت، ساعت اشتراک شروع می‌شود؛ با ثبت‌های بعدی فقط آی‌پی به‌روز می‌شود.
- **مدیریت ادمین** (`server/dns_admin.py`): ساخت کد، تمدید، حذف، فهرست و بازسازی لیست سفید — فقط روی سرور اجرا می‌شود.
- **پاک‌سازی انقضا** (`server/dns_expire.py`): با تایمر ساعتی systemd، کدهای منقضی‌شده را از لیست سفید بیرون می‌اندازد (رکورد مشتری پاک نمی‌شود).
- **هستهٔ DNS**: Unbound (پورت ۵۳) + Sniproxy (پورت ۴۴۳/۸۰) — نمونهٔ پیکربندی در `config-samples/`.

## قانون‌های اصلی

- هر مشتری فقط **یک آی‌پی /32** دارد؛ با ثبت تازه، آی‌پی قبلی **جایگزین** می‌شود، نه اضافه.
- کد هیچ اطلاعاتی (ماه، قیمت، انقضا) در خودش ندارد؛ همه‌چیز سمت سرور است.
- شمارندهٔ ترافیک به کد چسبیده است، نه به آی‌پی؛ با عوض‌شدن آی‌پی صفر نمی‌شود.
- کد همان کلید کامل دسترسی است: هرگز نام، موبایل یا شمارهٔ ترتیبی نباشد؛ فقط با `secrets` ساخته شود و فقط از کانال خصوصی به مشتری داده شود.

## نصب دستی (نسخهٔ اول)

روی اوبونتو ۲۴٫۰۴ تازه، با دسترسی root. `SERVER_IP` را با آی‌پی عمومی سرورتان عوض کنید:

```bash
# ۱) بسته‌ها
apt-get update -y
apt-get install -y python3 unbound sniproxy curl

# ۲) فایل‌های سرور
mkdir -p /opt/hachi-dns
cp server/reg_server.py server/dns_admin.py server/dns_expire.py /opt/hachi-dns/
chmod +x /opt/hachi-dns/*.py

# ۳) آدرس‌های DNS که به مشتری نشان داده می‌شود
python3 /opt/hachi-dns/dns_admin.py set-dns SERVER_IP SERVER_IP

# ۴) کانفیگ Unbound (نمونه‌ها آی‌پی 203.0.113.10 دارند؛ عوضش کنید)
mkdir -p /etc/unbound/unbound.conf.d
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-dns.conf > /etc/unbound/unbound.conf.d/hachi-dns.conf
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-sni.conf > /etc/unbound/unbound.conf.d/hachi-sni.conf

# ۵) کانفیگ Sniproxy
cp config-samples/sniproxy.conf /etc/sniproxy.conf

# ۶) چک کانفیگ‌ها
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-dns.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-sni.conf

# ۷) واحدهای systemd
cp systemd/hachi-dns-reg.service systemd/hachi-dns-expire.service systemd/hachi-dns-expire.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer

# ۸) ریستارت سرویس‌های DNS
systemctl restart unbound sniproxy
systemctl enable unbound sniproxy
```

## ساخت مشتری

```bash
# یک مشتری یک‌ماهه بسازید (کد تصادفی امن ساخته می‌شود)
python3 /opt/hachi-dns/dns_admin.py add 1 "first customer"

# فهرست مشتری‌ها
python3 /opt/hachi-dns/dns_admin.py list

# تمدید (۲ ماه اضافه) و حذف
python3 /opt/hachi-dns/dns_admin.py renew <CODE> 2
python3 /opt/hachi-dns/dns_admin.py remove <CODE>

# بازسازی لیست سفید (از روی مشتری‌ها)
python3 /opt/hachi-dns/dns_admin.py rebuild
```

مشتری کد را داخل نرم‌افزار وارد می‌کند و استارت می‌زند؛ ساعت اشتراک از همان لحظه شروع می‌شود و آی‌پی‌اش توی لیست سفید ست می‌شود.

## ⚠️ پیش از فروش، حتماً این‌ها را انجام دهید

1. **HTTPS**: نسخهٔ اول HTTP ساده است. پیش از فروش، سرویس ثبت را پشت دامنهٔ خودتان با TLS ببرید (مثلاً `https://dns.example.com`).
2. **بستن resolver باز**: نمونهٔ `hachi-dns.conf` فقط به localhost جواب می‌دهد. هرگز `0.0.0.0/0 allow` را در production باز نگذارید — فقط آی‌پی‌های لیست سفید به پروکسی برسند، بقیه DNS معمولی بگیرند.
3. **هرگز این فایل‌ها را commit نکنید**: `customers.json` ،`whitelist.txt` ،`whitelist.json` و هر فایلی که کد مشتری، آی‌پی مشتری یا رمز دارد. این سرویس موقع اجرا، فایل خالی می‌سازد.

## ساختار

```
server/
  reg_server.py      # سرویس ثبت (پورت 8792)
  dns_admin.py       # مدیریت ادمین (ساخت/تمدید/حذف/فهرست)
  dns_expire.py      # پاک‌سازی ساعتی انقضا
systemd/
  hachi-dns-reg.service
  hachi-dns-expire.service
  hachi-dns-expire.timer
config-samples/
  hachi-dns.conf     # نمونهٔ Unbound (آی‌پی نمونه 203.0.113.10 را عوض کنید)
  hachi-sni.conf     # نمونهٔ جدول SNI (دامنه‌هایی که از سرور رد می‌شوند)
  sniproxy.conf      # نمونهٔ Sniproxy
```

## در آپدیت بعدی

- اسکریپت نصب خودکار (`install.sh`) — نصب با یک دستور.
- پنل ادمین وب (فارسی و راست‌به‌چپ) — ساخت و مدیریت یوزر، فهرست بازی‌ها، لیست سفید و لیست سیاه.
- نرم‌افزار اندروید (۱٫۲٫۰) — ثبت آی‌پی مشتری با کد.

## راه‌های ارتباطی

- ایمیل: [baxirani248059@gmail.com](mailto:baxirani248059@gmail.com)

## دونیت (حمایت مالی)

اگر این پروژه به کارتان آمد، با رمز ارز حمایت کنید — تتر (USDT) روی شبکهٔ BEP20 (BSC):

`0xf714196efb17afac7395bb182d021c101b2b0206`

⚠️ **هشدار — فقط BEP20 (BSC).** تتر را روی ترون (TRC20)، اتریوم (ERC20) یا پالیگان نفرستید. فرستادن روی شبکهٔ دیگر ممکن است پول را برای همیشه گم کند و قابل برگشت نباشد.

## لایسنس

GNU Affero General Public License v3.0 (AGPL-3.0) — ببینید `LICENSE`.
