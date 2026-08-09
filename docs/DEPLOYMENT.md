# Deploying pos_retail to the production server

Written for the Contabo VPS at `169.58.143.45` (Ubuntu 24.04, aaPanel, PostgreSQL 18).

**Substitute your own values wherever you see `CHANGEME_DB` and `CHANGEME_MASTER`.**

Before starting, know the one thing that makes this box unusual: **aaPanel owns it**.
PostgreSQL and nginx are both installed under `/www/server`, not the system paths, so
generic Odoo guides send you to directories that either do not exist here or are never
read. Every step below accounts for that.

Run every command as `root`. Allow about **an hour**, most of it waiting on steps 8 and
10. Do them in order; each one assumes the previous succeeded.

| # | Step | What it gets you |
|---|---|---|
| 1 | Safety net and swap | A rollback point, and memory headroom so nothing gets killed |
| 2 | PostgreSQL boot unit | The database comes back after a reboot |
| 3 | PostgreSQL tools | Working `psql` and `pg_dump` — needed for backups |
| 4 | Host checks | Encoding, search extension, password format — cheap now, expensive later |
| 5 | System packages | Compilers, fonts, and a PDF engine that works |
| 6 | Database role | The non-superuser account Odoo insists on |
| 7 | Fetch the code | Odoo 19 core plus the `pos_retail` addon |
| 8 | Python environment | An isolated virtualenv with every dependency |
| 9 | Configuration | `odoo.conf`, sized for this machine |
| 10 | Create the database | Pakistani chart of accounts — **one chance to get right** |
| 11 | Run it as a service | Survives logout, crash and reboot |
| 12 | Web server | Reachable on port 80, POS live-sync included |
| 13 | Nightly backup, proven | Before there is anything to lose |

Each step is written the same way: **what you are doing**, the commands, an **Expect**
line telling you what success looks like, and **why** — because the reasons are the part
you need when the next server behaves differently.

---

## 1. Safety net and swap

**What you are doing:** taking a rollback point, then giving the machine an overflow
area for memory.

```bash
mkdir -p /root/preinstall
cp /www/server/pgsql/data/pg_hba.conf     /root/preinstall/pg_hba.conf.orig
cp /www/server/pgsql/data/postgresql.conf /root/preinstall/postgresql.conf.orig
nginx -T > /root/preinstall/nginx-full.orig 2>&1
ls /www/server/panel/vhost/nginx/ > /root/preinstall/vhosts.orig

fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h; nproc
```

**Expect:** `Swap: 2.0Gi`, and `nproc` prints your CPU count (note it, step 9 uses it).

**Why:** this install touches two files aaPanel owns (its nginx include directory and,
potentially, PostgreSQL config). Copying them first means any mistake is one `cp` away
from undone. `nginx -T` dumps the *entire* running config including every include, so
you have a record of what worked before you added anything.

The swapfile matters because this server ships with **none**. Without swap a memory
spike does not slow the machine down — the kernel picks the largest process and kills
it outright, which is Odoo, or worse, PostgreSQL. `chmod 600` because swap holds
fragments of memory including passwords. The `fstab` line is what makes it survive a
reboot; without it the swap disappears on restart.

---

## 2. Make sure PostgreSQL comes back after a reboot

**What you are doing:** checking whether anything starts PostgreSQL at boot, and
creating that if nothing does.

```bash
systemctl list-unit-files | grep -Ei 'pgsql|postgre'
ls -l /etc/init.d/ | grep -Ei 'pgsql|postgre'
```

**On this server both printed something** — `pgsql.service  generated` and
`/etc/init.d/pgsql`. That means aaPanel installed an old-style SysV startup script and
systemd auto-translates it into a unit at every boot. Translated is not the same as
wired to boot, so confirm:

```bash
systemctl is-enabled pgsql
```

**Expect:** `enabled`.

It prints a notice first — *"pgsql.service is not a native service, redirecting to
systemd-sysv-install"*. That is **not an error**. systemd is saying "this isn't mine,
let me ask the legacy tool", and the legacy tool's answer is the line after it.

> **If it says `enabled`, this step is done — go to step 3.** Do **not** create the unit
> file below. A second service competing to start the same database is worse than the
> problem it was meant to solve.

**Only if `is-enabled` said `disabled`, or both commands printed nothing at all,**
nothing starts PostgreSQL at boot. Try aaPanel's own script first, which is always
preferable to bolting on a competing unit:

```bash
systemctl enable pgsql && systemctl is-enabled pgsql
```

If *that* fails — no init script exists to enable — then write a unit of your own.
Check the real user and data path first so the unit matches reality rather than this
example:

```bash
ps -eo user,pid,cmd | grep '[p]ostgres' | head -3
```

```bash
cat > /etc/systemd/system/pgsql.service <<'EOF'
[Unit]
Description=PostgreSQL 18 (aaPanel build)
After=network.target

[Service]
Type=forking
User=postgres
Group=postgres
Environment=PGDATA=/www/server/pgsql/data
ExecStart=/www/server/pgsql/bin/pg_ctl -D /www/server/pgsql/data -l /www/server/pgsql/data/pg.log start
ExecStop=/www/server/pgsql/bin/pg_ctl -D /www/server/pgsql/data stop -m fast
TimeoutSec=120
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable pgsql
systemctl is-enabled pgsql
```

**Expect:** `enabled`

> Do **not** `systemctl start pgsql` now — PostgreSQL is already running. The unit only
> matters at boot.

**Why check at all, if it turned out fine?** Because the failure mode is silent and the
check costs one second. There is no `postgresql.service` here — the service is called
`pgsql` and it is generated rather than installed — so the obvious command
(`systemctl status postgresql`) reports "not found" and tells you nothing either way.

If nothing did start the database at boot, here is what you would see after a power cut
or a kernel-update reboot: `odoo.service` starts normally and reports `active`. Every
status check says running. Every page in the browser throws a database connection
error. You would spend an hour debugging Odoo while Odoo is perfectly healthy and the
database simply is not there.

`Type=forking` because `pg_ctl start` launches the server and returns rather than
staying in the foreground. `-m fast` on stop closes client connections and shuts down
cleanly instead of waiting for sessions to end.

---

## 3. PostgreSQL command-line tools

**What you are doing:** putting version-18 tools on your PATH.

> ⚠️ **Do NOT run `apt install postgresql-client`.** Ubuntu 24.04 ships client version
> **16**, and `pg_dump` **refuses to dump a server newer than itself**. Your server is
> 18.0, so every backup you ever took would fail with a version-mismatch error. Symlink
> aaPanel's own tools instead.

```bash
for b in psql pg_dump pg_restore createdb dropdb pg_isready; do
  ln -sf /www/server/pgsql/bin/$b /usr/local/bin/$b
done
psql --version
ldd /usr/local/bin/pg_dump | grep -i 'not found'
```

**Expect:** `psql (PostgreSQL) 18.0`, and the `ldd` line prints **nothing**.

**Why:** aaPanel installs PostgreSQL outside the system PATH, which is why `psql` came
back "command not found". The symlinks fix that without installing a second, older
PostgreSQL.

`ldd` lists the shared libraries a program needs; if it reports `libpq.so.5 => not
found`, the binaries cannot find their own library once run from `/usr/local/bin`. Fix
that once:

```bash
echo /www/server/pgsql/lib > /etc/ld.so.conf.d/pgsql.conf && ldconfig
ldd /usr/local/bin/pg_dump | grep -i 'not found'   # must now print nothing
```

---

## 4. Check PostgreSQL can host what Odoo needs

**What you are doing:** three checks that are cheap now and expensive later.

```bash
su -s /bin/bash postgres -c "psql -Atc 'show server_encoding'"
su -s /bin/bash postgres -c "psql -Atc \"select name from pg_available_extensions where name='pg_trgm'\""
su -s /bin/bash postgres -c "psql -Atc 'show password_encryption'"
```

**Expect:** `UTF8`, then `pg_trgm`, then `scram-sha-256` (or `md5`).

**Why each:**

**`server_encoding` must be UTF8.** Odoo stores everything as UTF-8; on a `SQL_ASCII`
server, Urdu text and even the `²` in `ft²` corrupt on write, and there is no repair
short of rebuilding the database.

**`pg_trgm` is how search stays fast.** Odoo runs `CREATE EXTENSION IF NOT EXISTS
pg_trgm` when it creates a database, but that call sits inside a `try` block
(`odoo/service/db.py:154`) — if it fails, Odoo logs one warning line and **carries on**.
Search still works; it just degrades to a full table scan on every keystroke. Fine at
500 products, unusable at 40,000, and nothing ever tells you. If the query above returns
nothing, install PostgreSQL 18's contrib modules before building the database.

**`password_encryption`** tells you how the role's password will be stored, so if you
ever tighten `pg_hba.conf` you know whether to write `scram-sha-256` or `md5` in it.
Writing the wrong one gives an authentication failure that looks like a wrong password.

---

## 5. System packages

```bash
apt update
apt install -y python3-venv python3-dev build-essential \
  libxml2-dev libxslt1-dev libzip-dev libldap2-dev libsasl2-dev \
  libjpeg-dev libpq-dev libffi-dev libssl-dev \
  node-less npm fonts-noto-core fonts-dejavu-core
npm install -g rtlcss

cd /tmp
wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_amd64.deb
apt install -y ./wkhtmltox_0.12.6.1-3.jammy_amd64.deb
wkhtmltopdf --version
```

**Expect:** `wkhtmltopdf 0.12.6.1 (with patched qt)` — the words *with patched qt* must
appear.

Several of Odoo's Python libraries have no prebuilt binary for Ubuntu 24.04, so pip
compiles them and needs a compiler plus header files: `build-essential` and
`python3-dev`. `libpq-dev` lets Python talk to PostgreSQL; the XML pair underpins
Odoo's whole view and report engine; `libjpeg`/`libzip` cover product photos and xlsx
files. The LDAP headers are needed even though you will never use LDAP, because a
library in Odoo's requirements will not *build* without them.

`node-less` and `rtlcss` compile stylesheets at runtime — **rtlcss specifically handles
right-to-left, which is what Urdu needs.** Fonts matter because without them PDF
invoices print as empty boxes.

wkhtmltopdf renders invoices to PDF. Ubuntu's own package is built against stock Qt and
silently produces broken page breaks and margins: it does not error, the invoices are
just wrong. There is no build for 24.04 "noble", so the 22.04 "jammy" one is used,
which is what Odoo's own documentation recommends.

---

## 6. Database role

```bash
su - postgres -c "/www/server/pgsql/bin/psql -c \"CREATE USER odoo WITH CREATEDB PASSWORD 'CHANGEME_DB';\""
su - postgres -c "/www/server/pgsql/bin/psql -c '\du'"
```

**Expect:** an `odoo` row whose attributes read `Create DB`, and **not** Superuser.

Odoo refuses to run as the `postgres` superuser. This is not advice — `odoo/cli/server.py`
exits with status 1 and the message *"Using the database user 'postgres' is a security
risk, aborting."* The separate role also limits the blast radius: any bug or bad module
can only reach Odoo's own database, not everything PostgreSQL hosts.

`su - postgres` is needed because a local PostgreSQL trusts the `postgres` OS user
without a password, and root has no credentials of its own to offer. The full binary
path is needed because aaPanel installed PostgreSQL outside the system PATH.

`CREATEDB` is required: Odoo creates and drops databases itself, and step 10 fails
without it. It is deliberately **not** `SUPERUSER`.

> On this server `pg_hba.conf` is set to `trust`, so the password is not actually
> checked. Set a real one anyway, so nothing breaks when that is hardened later.

---

## 7. Fetch the code

```bash
adduser --system --home=/opt/odoo --group odoo
git clone https://github.com/odoo/odoo.git --depth 1 --branch 19.0 /opt/odoo/odoo
mkdir -p /opt/odoo/custom_addons
git clone https://github.com/samadfastnexa/ostore-pos.git /opt/odoo/custom_addons/pos_retail
ls /opt/odoo/custom_addons/pos_retail/__manifest__.py
```

**Expect:** the manifest path prints.

`adduser --system` creates a service account with no password and no login shell, and
creates `/opt/odoo` as its home. Odoo is internet-facing and runs third-party module
code; as root a compromise reaches the whole machine, as `odoo` it reaches `/opt/odoo`.
(Odoo only *warns* when run as root — it will not stop you.)

`--depth 1` fetches just the latest commit rather than years of history: a few hundred
MB instead of several GB. The custom addon goes in a **separate** directory so that
upgrading Odoo never touches your code.

**The clone target name is the module name.** This repository has `__manifest__.py` at
its root, so Odoo reads the *folder* name as the module name. Clone it as `ostore-pos`
and Odoo will look for a module called `ostore-pos`, find none, and the addon simply
never appears — with no error to tell you why.

---

## 8. Python environment

```bash
python3 -m venv /opt/odoo/venv
/opt/odoo/venv/bin/pip install --upgrade pip wheel
/opt/odoo/venv/bin/pip install -r /opt/odoo/odoo/requirements.txt
chown -R odoo:odoo /opt/odoo
/opt/odoo/venv/bin/python -c "import xlsxwriter, openpyxl, psycopg2; print('deps ok')"
```

**Expect:** `deps ok`

Ubuntu 24.04 refuses system-wide pip installs (PEP 668, *externally-managed-environment*).
A virtualenv is the sanctioned way around it and keeps Odoo's library versions from
colliding with anything aaPanel depends on.

`chown -R` hands ownership to the service account; without it Odoo cannot write its own
log file or store attachments.

The explicit import check exists because **`tools/import_templates.py` imports
`xlsxwriter` at module load**. If it were missing, the entire addon would fail to import
rather than one feature degrading. Both it and `openpyxl` are already in Odoo's
`requirements.txt`, so this should pass; it is cheap to confirm here rather than
discover in step 10.

---

## 9. Configuration

```bash
mkdir -p /etc/odoo /var/log/odoo && chown odoo:odoo /var/log/odoo
cat > /etc/odoo/odoo.conf <<'EOF'
[options]
admin_passwd = CHANGEME_MASTER
db_host = 127.0.0.1
db_port = 5432
db_user = odoo
db_password = CHANGEME_DB
addons_path = /opt/odoo/odoo/addons,/opt/odoo/custom_addons
data_dir = /opt/odoo/.local/share/Odoo
logfile = /var/log/odoo/odoo.log
proxy_mode = True
workers = 3
max_cron_threads = 2
limit_memory_soft = 1610612736
limit_memory_hard = 2147483648
limit_time_cpu = 120
limit_time_real = 300
db_maxconn = 32
list_db = False
EOF
chown odoo:odoo /etc/odoo/odoo.conf && chmod 640 /etc/odoo/odoo.conf
```

Edit both `CHANGEME` values before continuing.

| Setting | Why it is there |
|---|---|
| `admin_passwd` | Guards database create/drop/restore. Not a login password. |
| `db_host = 127.0.0.1` | PostgreSQL listens on localhost only here. Keep it that way. |
| `addons_path` | Where Odoo looks for modules; core first, then yours. |
| `data_dir` | Attachments, product images and sessions on disk. |
| `proxy_mode = True` | Tells Odoo it sits behind nginx so it trusts forwarded headers. **Without it every generated link points at the wrong address.** |
| `workers = 3` | Separate processes rather than one thread. **Never 1**: Odoo logs *"You need to start Odoo with at least two workers to print a pdf version of the reports"* (`ir_actions_report.py:119`) and silently stops producing PDF invoices. |
| `max_cron_threads = 2` | Background jobs. Counts toward memory, so it is sized with the workers. |
| `limit_memory_soft/hard` | **Sized down from Odoo's defaults on purpose.** |
| `limit_time_cpu / real` | Kills a request stuck beyond 2 minutes of CPU or 5 minutes of wall clock, so one bad report cannot hang a worker forever. |
| `db_maxconn = 32` | Caps Odoo's share of PostgreSQL connections so it cannot starve aaPanel's other databases (the server allows 100 in total). |
| `list_db = False` | Hides the database selector from the internet. |

**On the memory limits.** Odoo defaults to `limit_memory_soft = 2048 MB` and
`limit_memory_hard = 2560 MB` **per worker** (`odoo/tools/config.py:462-472`), which
assumes a dedicated server. Three workers plus cron threads at those numbers is over
7 GB on a box with 7.8 GB that is *also* running PostgreSQL and aaPanel — the kernel
would start killing processes, quite possibly the database. The values above give each
worker 1.5 GB soft / 2 GB hard, which fits.

Adjust for the machine you are on:

| Total RAM | `workers` | `max_cron_threads` | `limit_memory_soft` | `limit_memory_hard` |
|---|---|---|---|---|
| 4 GB | 2 | 1 | `1073741824` | `1342177280` |
| **8 GB (this server)** | **3** | **2** | **1610612736** | **2147483648** |
| 16 GB+ | 5 | 2 | `2147483648` | `2684354560` |

`chmod 640` because the file holds two passwords in clear text.

---

## 10. Create the database

> ⚠️ **`-i l10n_pk` on its own does NOT give you the Pakistani chart of accounts.**
> Learned the hard way on 2026-08-09. Odoo's default company is created by `base` as
> *"My Company (San Francisco)"* with **country = United States**. When `account`
> installs, it reads the company's country to decide which chart to apply — so it
> applies the American one. `-i l10n_pk` only makes the Pakistani chart *available*,
> never applied. The company's country must already be Pakistan **before accounting
> installs**, which means the build has to run in phases.

Write the build as a script rather than pasting commands:

```bash
cat > /opt/odoo/build_db.sh <<'SCRIPT'
#!/bin/bash
set -e
BIN="/opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin"
CONF="-c /etc/odoo/odoo.conf -d ostore_live"

echo ">>> PHASE 1/5  create database, base module only"
$BIN $CONF -i base --without-demo=True --stop-after-init

echo ">>> PHASE 2/5  set company country to Pakistan"
$BIN shell $CONF <<'PY'
company = env.ref('base.main_company')
company.write({'country_id': env.ref('base.pk').id})
env.cr.commit()
print('COUNTRY =', company.country_id.code)
PY

echo ">>> PHASE 3/5  install accounting, l10n_pk and pos_retail"
$BIN $CONF -i l10n_pk,pos_retail --without-demo=True --stop-after-init

echo ">>> PHASE 4/5  make sure the Pakistani chart is applied"
$BIN shell $CONF <<'PY'
company = env.ref('base.main_company')
if not company.chart_template:
    env['account.chart.template'].try_loading('pk', company=company, install_demo=False)
    env.cr.commit()
company.invalidate_recordset()
print('CHART =', company.chart_template, '| CURRENCY =', company.currency_id.name,
      '| ACCOUNTS =', env['account.account'].search_count([]))
PY

echo ">>> PHASE 5/5  set the admin login"
$BIN shell $CONF <<'PY'
admin = env.ref('base.user_admin')
admin.write({'login': 'CHANGEME_ADMIN_EMAIL', 'password': 'CHANGEME_ADMIN_PASS'})
admin.partner_id.write({'email': 'CHANGEME_ADMIN_EMAIL'})
env.cr.commit()
print('LOGIN =', admin.login)
PY

echo ">>> BUILD COMPLETE"
SCRIPT

chmod 755 /opt/odoo/build_db.sh && chown odoo:odoo /opt/odoo/build_db.sh
setsid nohup su - odoo -s /bin/bash -c /opt/odoo/build_db.sh > /var/log/odoo/build.log 2>&1 &
tail -f /var/log/odoo/build.log
```

Edit the two `CHANGEME_ADMIN_*` values before running it.

**Expect**, after roughly four minutes:

```
COUNTRY = PK
CHART = pk | CURRENCY = PKR | ACCOUNTS = 130
LOGIN = your@email
>>> BUILD COMPLETE
```

**Why a detached script rather than pasted commands** — three separate failures, each of
which cost an hour:

- **Never interrupt a module install.** Ctrl+C, a dropped SSH session, or just running
  the next command before this one finished, leaves every module stuck in state
  `to install` instead of `installed`. The database still *works* — you can log in and
  query it — so nothing announces the problem. It surfaces much later as
  `Some modules have inconsistent states` and a chart of accounts that refuses to load.
  `setsid nohup` detaches the build from your terminal so none of that can reach it, and
  Ctrl+C on the `tail -f` then stops only the watching.
- **Never run a second Odoo process against a database mid-install.** Two registries on
  one half-built database is exactly what produces those inconsistent states.
- **`shell` is a subcommand, so it goes immediately after `odoo-bin`**, before any
  options: `odoo-bin shell -c … -d …`. Written as `odoo-bin -c … -d … shell` you get
  `error: unrecognized parameters: shell`, because anything not starting with a known
  subcommand is handled by the default `server` command.

**Why phase 4 exists** even though phase 3 should have covered it: on a Community
install the chart does not always apply during module installation. `try_loading` is
Odoo's own entry point — the same call the browser setup wizard makes when you pick a
country — and the `if not company.chart_template` guard makes it a no-op when phase 3
already worked.

**Why the admin login is set here, before the service exists.** Odoo creates the admin
user as `admin`/`admin` and there is no CLI flag to change it at creation time. Port
8069 is reachable the instant the service starts, so doing it now means `admin`/`admin`
is never live on a public address.

`--without-demo=True` keeps out the fake products and customers; `all` is deprecated in
19.0 and logs a warning.

**Then verify. This is not optional:**

```bash
su -s /bin/bash postgres -c "psql -d ostore_live -Atc \"select name||' = '||state from ir_module_module where name in ('account','l10n_pk','point_of_sale','pos_retail')\""
su -s /bin/bash postgres -c "psql -d ostore_live -Atc \"select 'taxes = '||count(*) from account_tax\""
su -s /bin/bash postgres -c "psql -d ostore_live -Atc \"select 'PK tax tags = '||count(*) from account_account_tag t join res_country c on t.country_id=c.id where c.code='PK'\""
```

**Expect:** four `= installed` (**not** `to install`), around 61 taxes, around 122
Pakistani tax tags.

**If the chart is wrong, fix it now or never.** Odoo will not swap a chart of accounts
once a journal entry exists. With the American chart an auto-applying *Foreign Trade*
fiscal position matches every non-US address and silently **zero-rates every Pakistani
customer** — no error, no warning, simply no tax collected. While the posted-entry count
is zero the repair is `dropdb --if-exists ostore_live` and run the script again. After
the first sale there is no repair.

A related symptom to recognise: if the chart fails to load with *"missing tax tag …​ for
country Pakistan"*, the cause is almost always that `l10n_pk` is sitting in `to install`
rather than `installed`. Its tax tags come from `data/account_tax_vat_report.xml`, which
never ran. Finish the install; don't go hunting for the tags.

---

## 11. Run it as a service

```bash
cat > /etc/systemd/system/odoo.service <<'EOF'
[Unit]
Description=Odoo 19
After=network.target pgsql.service

[Service]
Type=simple
User=odoo
ExecStart=/opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin -c /etc/odoo/odoo.conf
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now odoo
sleep 8; systemctl is-active odoo; curl -sI http://127.0.0.1:8069/web/login | head -1
```

**Expect:** `active` then `HTTP/1.0 200 OK`

systemd restarts Odoo after a crash (`Restart=always`) and at boot (`enable`). Started
by hand instead, it dies when you close the SSH session. `User=odoo` keeps it off root.

**`After=pgsql.service`** matters because of what step 2 found: PostgreSQL here is a
generated SysV unit, not a native one. Without this line systemd is free to start Odoo
first, and Odoo exits immediately because there is no database to connect to.

The `curl` deliberately targets **8069 directly**, bypassing nginx, so a failure tells
you the fault is Odoo's and not the web server's.

---

## 12. Web server

> ⚠️ This is the same nginx that serves aaPanel. A broken config takes the panel down
> with it. Always run `nginx -t` before reloading.

**Do not open port 8069 in the firewall.** ufw is active here with a default-DROP policy
and 8069 is not on its allow-list — which is correct. nginx on port 80 (already open) is
how the world reaches Odoo. If a browser on `http://SERVER_IP:8069` times out, that is
the firewall working as intended, not a fault.

First read what aaPanel already defines, because two of its files affect this one:

```bash
cat /www/server/panel/vhost/nginx/0.websocket.conf
head -25 /www/server/panel/vhost/nginx/0.default.conf
```

On this server `0.websocket.conf` contains:

```nginx
map $http_upgrade $connection_upgrade { default upgrade; '' close; }
```

**That map already exists, so do not write your own.** Two `map` blocks with the same
variable name make nginx refuse to start — *"duplicate map"* — and since aaPanel shares
this nginx, the control panel goes down with the site. The config below **uses**
`$connection_upgrade` rather than defining it.

`0.default.conf` is a catch-all holding port 80 with `server_name _`. An exact
`server_name` beats a catch-all in nginx, so the vhost below coexists with it instead of
replacing it.

```bash
cat > /www/server/panel/vhost/nginx/odoo.conf <<'EOF'
upstream odoo_app  { server 127.0.0.1:8069; }
upstream odoo_chat { server 127.0.0.1:8072; }

server {
    listen 80;
    server_name 169.58.143.45;
    client_max_body_size 200M;

    proxy_read_timeout 720s;
    proxy_connect_timeout 720s;
    proxy_send_timeout 720s;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;

    location /websocket {
        proxy_pass http://odoo_chat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
    }

    location / {
        proxy_pass http://odoo_app;
        proxy_redirect off;
    }

    gzip on;
    gzip_min_length 1100;
    gzip_types text/plain text/css text/javascript application/javascript application/json application/xml;
}
EOF
nginx -t
grep -c proxy_pass /www/server/panel/vhost/nginx/odoo.conf
nginx -s reload
sleep 2
curl -sI http://169.58.143.45/web/login | head -1
```

**Expect:** `syntax is ok` / `test is successful`, then `2`, then `HTTP/1.1 200 OK`.

> **Reload with `nginx -s reload`, not `systemctl reload nginx`.** Like PostgreSQL,
> nginx here is not a systemd service — `systemctl` answers *"nginx.service is not
> active, cannot reload"* and, critically, **changes nothing while looking like a
> plain warning**. The config test passes, you assume it worked, and the site keeps
> serving the old config. `nginx -s reload` signals the running master through its pid
> file and works regardless of init system.

`grep -c proxy_pass` should print **2** — one for the app, one for the websocket. It
catches a truncated paste that still happens to be valid nginx syntax.

**The path matters.** `/etc/nginx/conf.d/` does not exist on this server and is not
included by its nginx config; a vhost written there is silently never read. aaPanel's
nginx includes `/www/server/panel/vhost/nginx/*.conf`, which is why the file goes there.
It also means the vhost survives aaPanel restarting nginx from its own control panel.

Odoo uses **two** ports: 8069 for pages and **8072 for the live channel** that pushes
updates to the till. Omit the `odoo_chat` upstream and the POS appears to work but never
syncs between counters. A websocket needs the explicit `Upgrade`/`Connection` headers; a
plain proxy pass will not switch protocol.

`client_max_body_size 200M` because nginx defaults to 1 MB and would reject product
image uploads. `proxy_read_timeout 720s` because nginx defaults to 60 seconds, and a
long POS sync or a large report then dies as a 504 in the middle of a sale.

To undo: `rm /www/server/panel/vhost/nginx/odoo.conf && nginx -s reload`.

### While you are in the firewall

```bash
ss -tlnp | grep 5432
ufw delete allow 5432/tcp
ufw delete allow 5432/udp
```

**Expect:** `127.0.0.1:5432` only, then two `Rule deleted` lines.

aaPanel's default ufw rules open **5432 to the whole internet**. Combined with
`pg_hba.conf` set to `trust`, that would mean anyone, anywhere, connecting as the
PostgreSQL superuser with no password. Today you are saved only by PostgreSQL binding to
loopback — that rule is a loaded gun waiting for someone to change `listen_addresses`.
Nothing needs it: Odoo reaches PostgreSQL over loopback, which ufw does not filter.

---

## 13. Prove you can take a backup — before there is anything to lose

**What you are doing:** installing a nightly backup and proving it works before there is
anything to lose.

> **aaPanel's Databases page will not show `ostore_live`.** It lists only databases
> created through the panel, and Odoo created this one directly. That is normal —
> PostgreSQL is the authority, and `psql -Atc "select datname from pg_database"` shows
> it. Do **not** use the panel's *"Get DB from server"* button to adopt it: adoption can
> reassign ownership or attach a panel-managed role, which risks breaking Odoo's access
> in exchange for a row in a list. It also means **aaPanel's backup feature does not
> cover this database** — which is what this step is for.

```bash
cat > /usr/local/bin/odoo-backup.sh <<'EOF'
#!/bin/bash
set -e
KEEP=14
DEST=/var/backups/odoo
STAMP=$(date +%F_%H%M)
mkdir -p "$DEST" && chmod 700 "$DEST"

pg_dump -h 127.0.0.1 -U postgres -Fc -d ostore_live -f "$DEST/ostore_live_$STAMP.dump"
tar czf "$DEST/filestore_$STAMP.tgz" -C /opt/odoo/.local/share Odoo

find "$DEST" -name 'ostore_live_*.dump' -mtime +$KEEP -delete
find "$DEST" -name 'filestore_*.tgz'    -mtime +$KEEP -delete
echo "$(date '+%F %T') backup ok"
EOF
chmod 700 /usr/local/bin/odoo-backup.sh

echo '30 2 * * * root /usr/local/bin/odoo-backup.sh >> /var/log/odoo/backup.log 2>&1' > /etc/cron.d/odoo-backup

/usr/local/bin/odoo-backup.sh
pg_restore -l /var/backups/odoo/*.dump | head -5
ls -lh /var/backups/odoo/
```

**Expect:** `backup ok`, `pg_restore -l` listing table entries rather than erroring, and
two files.

**Connect over loopback as root, not via `su postgres`.** `/var/backups/odoo` is mode
`700` and root-owned, so the `postgres` user cannot write into it —
`su -s /bin/bash postgres -c "pg_dump … -f /var/backups/odoo/…"` fails with *Permission
denied*. Root running `pg_dump -h 127.0.0.1 -U postgres` writes the file itself.

> That connection needs no password only because `pg_hba.conf` is set to `trust`. If you
> ever harden it, **this cron breaks silently at 2:30 AM** — and a silently broken backup
> is worse than no backup, because you will believe you have one. Add the credentials to
> a `~/.pgpass` at the same time you make that change.

**Why do it now, on an empty database:** a backup you have never restored is not a
backup. Testing the mechanism while the database holds nothing means a failure costs you
nothing. Discovering the same failure in six months, with a year of sales in it, is a
different day entirely.

**Why each part:**

- `-Fc` is PostgreSQL's compressed custom format. Smaller than plain SQL, and
  `pg_restore` can read it selectively — restore one table without the rest.
- **The `tar` of the data directory is not optional.** Product images and attachments
  live on disk, not in the database. A SQL dump alone restores a shop with no pictures.
- `pg_restore -l` lists what is *inside* the dump without restoring anything. It is the
  cheapest possible proof the file is not truncated or empty.
- `KEEP=14` deletes anything older than two weeks. Without it the disk fills up, and a
  full disk stops PostgreSQL writing — an outage caused by the backups.
- `chmod 700` because these dumps contain every customer name, every price and every
  ledger balance in the shop. Treat the directory like the safe.
- 2:30 AM because nobody is selling.

**A database dump must never be committed to git or uploaded anywhere shared.** That is
why `.gitignore` in this repository excludes `*.dump` and `*.sql`.

**Copy these off the server.** A backup that only exists on the machine it came from
does not survive that machine dying. `rsync` them somewhere else on a schedule too.

---

## First three things in the browser

1. **Settings → Companies** — set the country to Pakistan, then check
   Accounting → Configuration → Fiscal Positions.
2. **Point of Sale → Configuration** — create the register; leave *Restrict Categories*
   off unless you mean it.
3. **Load the catalogue** with the import sheets, in order:
   Suppliers → Categories → Products → Packages.

Do **not** restore a dump from a development machine. It carries the wrong chart of
accounts, demo products and posted journal entries.

---

## If it breaks

| Symptom | Cause | Fix |
|---|---|---|
| `Using the database user 'postgres' … aborting` | `db_user` wrong in odoo.conf | must be `odoo` |
| `role "odoo" does not exist` | step 6 not run | re-run step 6 |
| `no pg_hba.conf entry for host` | PostgreSQL rejecting TCP auth | check `pg_hba.conf`; restore `/root/preinstall/pg_hba.conf.orig` |
| nginx 502 | Odoo not running | `journalctl -u odoo -n 50` |
| Login page loads unstyled | `node-less` / `rtlcss` missing | re-run step 5, `systemctl restart odoo` |
| Addon not in the Apps list | cloned to the wrong folder name | must be `pos_retail` |
| `This account is currently not available` | `--system` user has no shell | keep `-s /bin/bash` |
| Everything "running" but every page errors | PostgreSQL did not start after a reboot | step 2; `systemctl start pgsql` |
| Invoices download but look wrong | wkhtmltopdf is not the patched-Qt build | step 5; version must say *with patched qt* |
| No PDF at all | `workers` is 1 | set 2 or more; see step 9 |
| `pg_dump: server version mismatch` | using Ubuntu's client 16 against server 18 | step 3; never `apt install postgresql-client` |
| Search slow once the catalogue grows | `pg_trgm` was missing at database creation | step 4; install contrib, then re-create the database |
| Odoo or PostgreSQL killed at random | memory limits left at Odoo's defaults | step 9 sizing table |
| POS syncs nothing between two counters | `odoo_chat` upstream missing from nginx | step 12 |
| Every Pakistani customer charged 0% tax | US chart applied; company country was US when `account` installed | step 10 — only fixable before the first posted entry |
| `Some modules have inconsistent states` | a module install was interrupted; modules stuck in `to install` | step 10; `dropdb` and re-run the build script detached |
| Chart load fails: *missing tax tag … for country Pakistan* | `l10n_pk` never finished installing, so its tax report never ran | step 10 — finish the install, don't hunt for the tags |
| `error: unrecognized parameters: shell` | `shell` placed after the options | `odoo-bin shell -c … -d …`, subcommand first |
| Browser times out on port 8069 | ufw default-DROP; 8069 not allowed | correct — reach Odoo through nginx on port 80 |
| nginx config edited but nothing changed | `systemctl reload nginx` printed *"not active, cannot reload"* and did nothing | `nginx -s reload` |
| nginx refuses to start: *duplicate map* | redefining `$connection_upgrade`, which `0.websocket.conf` already declares | step 12 — use it, don't declare it |

## Not covered here

- **HTTPS** — needs a domain first, then `certbot --nginx`. Until then, logins travel in
  clear text over the internet. Do not run a real shop on plain HTTP for long.
- **Copying the step 13 backups off the server**, and actually restoring one into a
  scratch database once. Until you have done that, you have a file, not a backup.
- **Firewalling 8069/8072** once nginx is proxying — `ufw deny 8069` — so nobody can
  bypass nginx and reach Odoo directly.
- **Monitoring**, so you learn the disk is full before the shop does.
- **`pg_hba.conf` is left at `trust`**, meaning anyone with shell access reaches
  PostgreSQL without a password. Worth hardening once the system is stable, and
  carefully: aaPanel may rely on it, and the original is at
  `/root/preinstall/pg_hba.conf.orig`.

## Order these steps run in, and why

Steps 1–4 touch nothing and install nothing; they establish that the machine can host
what comes next. Everything after them is hard to undo, which is the point of doing the
checks first. Within the install itself the order is forced: packages before pip
(compilers must exist first), the role before the database, the database before the
service, the service before nginx — so that when something fails you always know the
layer below it was already working.
