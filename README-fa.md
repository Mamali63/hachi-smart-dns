# Hachi Smart DNS — هچی اسمارت دی‌ان‌اس

[English](README.md) | **فارسی**

سرویس ثبت و مدیریت Smart DNS با لیست سفید تک‌آی‌پی — برای رد کردن لاگین و لابی بازی‌ها (پلی‌استیشن، فورتنایت، یوتیوب) از سرور شما، بدون VPN و بدون رد کردن ترافیک بازی.

> **وضعیت:** نسخهٔ کامل — هستهٔ پایتون + اسکریپت نصب خودکار + پنل ادمین + نرم‌افزار اندروید.

## این چیست؟

- **سرور ثبت** (`server/reg_server.py`): سرویس HTTP با فقط کتابخانهٔ استاندارد پایتون، پورت ۸۷۹۲. هر مشتری یک کد دارد؛ با اولین ثبت، ساعت اشتراک شروع می‌شود؛ با ثبت‌های بعدی فقط آی‌پی به‌روز می‌شود.
- **پنل ادمین** (`server/admin_panel.py`): پنل وب فارسی و راست‌به‌چپ، پورت ۸۰۸۰ (پیش‌فرض؛ موقع نصب با y/N قابل تغییر است، رد کردن یعنی همان ۸۰۸۰ می‌ماند) — یوزر بسازد و پاک کند و تمدید کند، فهرست بازی‌ها را اضافه و پاک کند (با هر تغییر، جدول Unbound همان لحظه بازسازی و سرویس‌ها بازخوانی می‌شوند)، آدرس‌های DNS و لیست سفید را ببیند، و رمز ادمین را عوض کند. ورود اول: `admin` / `admin` — بعد از اولین ورود عوضش کنید.
- **مدیریت ادمین** (`server/dns_admin.py`): ساخت کد، تمدید، حذف، فهرست و بازسازی لیست سفید — فقط روی سرور اجرا می‌شود.
- **پاک‌سازی انقضا** (`server/dns_expire.py`): با تایمر ساعتی systemd، کدهای منقضی‌شده را از لیست سفید بیرون می‌اندازد (رکورد مشتری پاک نمی‌شود).
- **هستهٔ DNS**: Unbound (پورت ۵۳) + Sniproxy (پورت ۴۴۳/۸۰) — نمونهٔ پیکربندی در `config-samples/`.

## قانون‌های اصلی

- هر مشتری فقط **یک آی‌پی /32** دارد؛ با ثبت تازه، آی‌پی قبلی **جایگزین** می‌شود، نه اضافه.
- کد هیچ اطلاعاتی (ماه، قیمت، انقضا) در خودش ندارد؛ همه‌چیز سمت سرور است.
- شمارندهٔ ترافیک به کد چسبیده است، نه به آی‌پی؛ با عوض‌شدن آی‌پی صفر نمی‌شود.
- کد همان کلید کامل دسترسی است: هرگز نام، موبایل یا شمارهٔ ترتیبی نباشد؛ فقط با `secrets` ساخته شود و فقط از کانال خصوصی به مشتری داده شود.

## نصب دستی (نسخهٔ اول)

```bash
# 1. فایل‌ها را بریزید
sudo mkdir -p /opt/hachi-dns
sudo cp server/*.py /opt/hachi-dns/

# 2. آی‌پی سرور خودتان را ست کنید
python3 /opt/hachi-dns/dns_admin.py set-dns <PRIMARY_IP> <SECONDARY_IP>

# 3. سرویس‌ها را فعال کنید
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer

# 4. مشتری بسازید (کد تصادفی امن ساخته می‌شود)
python3 /opt/hachi-dns/dns_admin.py add 1 "first customer"
```

نمونهٔ پیکربندی Unbound و Sniproxy در `config-samples/` است — آی‌پی نمونه `203.0.113.10` را با آی‌پی سرور خودتان عوض کنید.

## نصب آسان (یک دستور)

```bash
sudo bash install.sh
```

اسکریپت موقع نصب آی‌پی سرور را می‌پرسد (خودکار تشخیص می‌دهد، شما تأیید می‌کنید)، همه‌چیز را نصب می‌کند و آخرش آدرس پنل را می‌دهد:

```
Admin panel: http://SERVER_IP:8080  (first login: admin / admin — change it!)
```

وارد پنل شوید، رمز را عوض کنید، یوزر و ماه را انتخاب کنید و بسازید؛ یوزر را به خریدار بدهید؛ خریدار آن را داخل نرم‌افزار وارد می‌کند، استارت می‌زند و آی‌پی‌اش توی لیست سفید ست می‌شود. هر یوزر همیشه فقط یک آی‌پی دارد. پورت پنل پیش‌فرض ۸۰۸۰ است و موقع نصب با y/N می‌شود عوضش کرد؛ اگر پورت درگیر باشد، نصب هشدار می‌دهد و یکی دیگر می‌پرسد؛ رد کردن یعنی همان ۸۰۸۰ می‌ماند.

## نصب دستی (قدم‌به‌قدم)

اگر نمی‌خواهید از اسکریپت نصب استفاده کنید، همین کارها را دونه‌دونه در ترمینال سرور (با دسترسی root، روی اوبونتو ۲۴٫۰۴ تازه) بزنید. `SERVER_IP` را با آی‌پی عمومی سرورتان عوض کنید:

```bash
# ۱) بسته‌ها
apt-get update -y
apt-get install -y python3 unbound sniproxy curl

# ۲) فایل‌های سرور
mkdir -p /opt/hachi-dns
cp server/reg_server.py server/dns_admin.py server/dns_expire.py /opt/hachi-dns/
cp server/admin_panel.py server/domains.json server/domains.default.json /opt/hachi-dns/
chmod +x /opt/hachi-dns/*.py

# ۳) آدرس‌های DNS که به مشتری نشان داده می‌شود
python3 /opt/hachi-dns/dns_admin.py set-dns SERVER_IP SERVER_IP

# نسخهٔ نرم‌افزار که سرور به کلاینت گزارش می‌دهد (چک آپدیت)
printf '{"versionCode": 3, "versionName": "1.2.0"}' > /opt/hachi-dns/version.json

# ۴) کانفیگ Unbound (نمونه‌ها آی‌پی 203.0.113.10 دارند؛ عوضش کنید)
mkdir -p /etc/unbound/unbound.conf.d
sed "s/203\.0\.113\.10/SERVER_IP/g" config-samples/hachi-dns.conf > /etc/unbound/unbound.conf.d/hachi-dns.conf

# ۵) جدول SNI را از domains.json بسازید (منبع حقیقت پنل همین فایل است)
cd /opt/hachi-dns
HACHI_SNI_CONF=/etc/unbound/unbound.conf.d/hachi-sni.conf HACHI_RELOAD=0 python3 -c "import admin_panel; print(admin_panel.rebuild_sni())"
cd -

# ۶) کانفیگ Sniproxy
cp config-samples/sniproxy.conf /etc/sniproxy.conf

# ۷) چک کانفیگ‌ها
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-dns.conf
unbound-checkconf /etc/unbound/unbound.conf.d/hachi-sni.conf

# ۸) واحدهای systemd (پورت پنل پیش‌فرض ۸۰۸۰ است؛ برای عوض‌کردن، خط Environment را در hachi-dns-panel.service عوض کنید)
cp systemd/hachi-dns-reg.service systemd/hachi-dns-expire.service systemd/hachi-dns-expire.timer systemd/hachi-dns-panel.service /etc/systemd/system/
# همیشه روشن: اگر unbound یا sniproxy از کار افتاد، systemd دوباره بالا می‌آوردشان
for svc in unbound sniproxy; do mkdir -p /etc/systemd/system/$svc.service.d; printf '[Service]\nRestart=always\nRestartSec=5\n' > /etc/systemd/system/$svc.service.d/restart.conf; done
systemctl daemon-reload
systemctl enable --now hachi-dns-reg.service hachi-dns-expire.timer hachi-dns-panel.service

# ۹) ریستارت سرویس‌های DNS
systemctl restart unbound sniproxy
systemctl enable unbound sniproxy
```

بعد پنل را باز کنید: `http://SERVER_IP:8080` — ورود اول `admin` / `admin`، بعد رمز را عوض کنید.

## پنل ادمین

- **یوزرها:** فهرست کامل (کد، نام، مدت، شروع و پایان، وضعیت، آی‌پی فعلی، حجم) + ساختن (ماه یا ساعت) + تمدید + حذف.
- **بازی‌ها:** فهرست دامنه‌های دیفالت (۵۴ دامنه: فورتنایت، پلی‌استیشن، استیم، ایکس‌باکس، نینتندو، EA، یوبی‌سافت، بتل‌نت، رایوت، راک‌استار، ماینکرفت، پابجی، اکتیویژن، سوپرسل، روبلاکس، یوتیوب و...) + افزودن و حذف توسط ادمین + دکمهٔ «برگشت به دیفالت» که فهرست را به همان ۵۴ دامنهٔ اول برمی‌گرداند (دیفالت‌ها جدا در `domains.default.json` ذخیره شده‌اند).
- **لیست سیاه:** دامنه‌هایی که **اصلاً باز نمی‌شوند** (DNS برایشان NXDOMAIN می‌دهد) — برای بستن یک سایت یا تست اینکه DNS کار می‌کند (سایت را بلاک کن: اگر باز نشد یعنی DNS دارد کار می‌دهد؛ با حذف از فهرست دوباره باز می‌شود). یک دامنه نمی‌تواند هم‌زمان هم توی لیست بازی‌ها باشد هم توی لیست سیاه.
- **لیست سفید:** آخرین آی‌پی هر یوزر + آخرین اتصال + حذف آی‌پی از لیست سفید + افزودن آی‌پی به یک یوزر (لیست سفید از روی یوزرها ساخته می‌شود؛ حذف آی‌پی یعنی آن آی‌پی از آن یوزر پاک می‌شود و یوزر باید دوباره ثبت کند).
- **تنظیمات:** آدرس‌های DNS، لیست سفید فعلی، تغییر رمز ادمین.
- **آموزش:** دو صفحه داخل پنل — «آموزش بازی‌ها» (چطور آدرس بازی‌ها را پیدا کنی: لاگ سرور، PCAPdroid، Wireshark، حدس هوشمند) و «آموزش نرم‌افزار» (نرم‌افزار اندروید برای مشتری: قانون وای‌فای خانه، هر بار که وصل نشد استارت بزن تا آی‌پی تازه توی لیست سفید بیاید، معنی دکمه‌ها، عیب‌یابی).
- رمز ادمین فقط به‌صورت هش نمکی (pbkdf2) ذخیره می‌شود؛ با اولین اجرا رمز `admin` ساخته می‌شود و پنل تا عوض‌شدن آن هشدار نشان می‌دهد.

## ⚠️ پیش از فروش، حتماً این‌ها را انجام دهید

1. **HTTPS**: نسخهٔ اول HTTP ساده است. پیش از فروش، سرویس ثبت را پشت دامنهٔ خودتان با TLS ببرید (مثلاً `https://dns.example.com`).
2. **بستن resolver باز**: هرگز `0.0.0.0/0 allow` را در production باز نگذارید — فقط آی‌پی‌های لیست سفید به پروکسی برسند، بقیه DNS معمولی بگیرند.
3. **هرگز این فایل‌ها را commit نکنید**: `customers.json` ،`whitelist.txt` ،`whitelist.json` و هر فایلی که کد مشتری، آی‌پی مشتری یا رمز دارد. این سرویس موقع اجرا، فایل خالی می‌سازد.

## مدیریت سرویس‌ها

سه دکمه برای هر سرویس — **روشن / ریستارت / خاموش** — هم داخل پنل (صفحهٔ «سرویس‌ها»: Unbound، Sniproxy، سرویس ثبت، پنل ادمین؛ وضعیت هرکدام هم نشان داده می‌شود) و هم از کنسول:

```bash
systemctl restart unbound sniproxy hachi-dns-reg hachi-dns-panel  # ریستارت همه
systemctl stop unbound     # خاموش کردن DNS
systemctl start unbound    # روشن کردن DNS
systemctl status unbound   # دیدن وضعیت
```

اگر DNS کار نمی‌کند، معمولاً ریستارت همین سرویس‌ها کافی است.

**همیشه روشن:** همهٔ سرویس‌ها با ریبوت سرور خودکار دوباره بالا می‌آیند (`systemctl enable`) و اگر از کار بیفتند، systemd خودکار ریستارتشان می‌کند (`Restart=always`) — پس با خاموش‌روشن شدن VPS هم چیزی از کار نمی‌افتد.

## ساختار

```
server/
  reg_server.py      # سرویس ثبت (پورت 8792)
  admin_panel.py     # پنل ادمین (پورت 8080)
  domains.json       # فهرست بازی‌ها (قابل ویرایش در پنل)
  domains.default.json  # دیفالت کارخانه (۵۴ دامنه، برای دکمهٔ برگشت)
  blocked.json       # لیست سیاه (قابل ویرایش در پنل؛ خالی = هیچی بلاک نیست)
  dns_admin.py       # مدیریت ادمین (ساخت/تمدید/حذف/فهرست)
  dns_expire.py      # پاک‌سازی ساعتی انقضا
client/
  hachi-dns.apk      # نرم‌افزار اندروید ۱٫۲٫۰ (آدرس سرور را کاربر وارد می‌کند)
  src/               # سورس برنامه
  build.sh           # ساخت APK
systemd/
  hachi-dns-reg.service
  hachi-dns-panel.service
  hachi-dns-expire.service
  hachi-dns-expire.timer
config-samples/
  hachi-dns.conf     # نمونهٔ Unbound
  hachi-sni.conf     # نمونهٔ جدول دامنه‌ها
  sniproxy.conf      # نمونهٔ Sniproxy
```

## نرم‌افزار اندروید

نرم‌افزار (`client/hachi-dns.apk`، نسخهٔ ۱٫۲٫۰): مشتری فقط **کد یوزر** را می‌زند و استارت می‌زند — آدرس سرور را لازم نیست وارد کند. برنامه VPN نیست؛ فقط آی‌پی خانه را ثبت می‌کند و باید روی همان وای‌فای خانه باز شود.

**دانلود نرم‌افزار:** از بخش [Releases](https://github.com/Mamali63/hachi-smart-dns/releases) همین ریپو، فایل `hachi-dns.apk` را دانلود کنید.

## راه‌های ارتباطی

- ایمیل: [baxirani248059@gmail.com](mailto:baxirani248059@gmail.com)

## دونیت (حمایت مالی)

اگر این پروژه به کارتان آمد، با رمز ارز حمایت کنید — تتر (USDT) روی شبکهٔ BEP20 (BSC):

`0xf714196efb17afac7395bb182d021c101b2b0206`

⚠️ **هشدار — فقط BEP20 (BSC).** تتر را روی ترون (TRC20)، اتریوم (ERC20) یا پالیگان نفرستید. فرستادن روی شبکهٔ دیگر ممکن است پول را برای همیشه گم کند و قابل برگشت نباشد.

## لایسنس

GNU Affero General Public License v3.0 (AGPL-3.0) — ببینید `LICENSE`.

---

*English summary: Hachi Smart DNS — a whitelist-based Smart DNS registration service (Python stdlib only) for routing game logins through your own server. One /32 IP per customer, codes carry no data, counters are keyed by code. See the warnings above before selling: use HTTPS and never run an open resolver.*
