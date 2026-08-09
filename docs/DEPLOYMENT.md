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
| 13 | Prove the backup works | Before there is anything to lose |

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

**If either printed something,** aaPanel manages it. Confirm and move on:

```bash
systemctl is-enabled pgsql        # want: enabled (or generated)
```

**If both were empty,** PostgreSQL is running only because someone started it by hand.
Create a boot unit:

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

**Why this is not optional:** there is no `postgresql.service` on this box, so nothing
guarantees the database starts after a power cut or a kernel update reboot. The failure
mode is nasty: Odoo's own service *will* start and report `active`, so every check says
"running" while every page errors with a database connection failure. You would be
debugging Odoo when the problem is PostgreSQL being absent.

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

```bash
su - odoo -s /bin/bash -c "/opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf -d ostore_live \
  -i l10n_pk,pos_retail --without-demo=True --stop-after-init"
tail -20 /var/log/odoo/odoo.log
```

**Expect:** `Modules loaded.` and no `CRITICAL`. Takes 5–10 minutes.

`-s /bin/bash` lends the `--system` account a shell for this one command; without it you
get *"This account is currently not available"*.

**`l10n_pk` must be installed in this same command.** Installing it sets the chart of
accounts, and **a chart of accounts cannot be changed once a journal entry exists**.
Getting this wrong is not a cosmetic problem: with the generic (US) chart, an
auto-applying *Foreign Trade* fiscal position matches any non-US address, and every
Pakistani customer is silently **zero-rated**. There is one chance to get it right.

Use `--without-demo=True`; `all` is deprecated in 19.0 and logs a warning.

---

## 11. Run it as a service

```bash
cat > /etc/systemd/system/odoo.service <<'EOF'
[Unit]
Description=Odoo 19
After=network.target

[Service]
Type=simple
User=odoo
ExecStart=/opt/odoo/venv/bin/python3 /opt/odoo/odoo/odoo-bin -c /etc/odoo/odoo.conf
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now odoo
sleep 5 && systemctl is-active odoo && curl -sI http://127.0.0.1:8069/web/login | head -1
```

**Expect:** `active` then `HTTP/1.0 200 OK`

systemd restarts Odoo after a crash (`Restart=always`) and at boot (`enable`). Started
by hand instead, it dies when you close the SSH session. `User=odoo` keeps it off root.

The `curl` hits Odoo **directly on 8069**, bypassing nginx, so if something is wrong you
already know which half is at fault.

---

## 12. Web server

> ⚠️ This is the same nginx that serves aaPanel. A broken config takes the panel down
> with it. Always run `nginx -t` before reloading.

```bash
cat > /www/server/panel/vhost/nginx/odoo.conf <<'EOF'
upstream odoo { server 127.0.0.1:8069; }
upstream odoochat { server 127.0.0.1:8072; }

server {
    listen 80;
    server_name 169.58.143.45;
    client_max_body_size 200M;

    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;

    location /websocket {
        proxy_pass http://odoochat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
    location / { proxy_pass http://odoo; proxy_redirect off; }
}
EOF
nginx -t && systemctl reload nginx
```

**Expect:** `syntax is ok` / `test is successful`. Then open `http://169.58.143.45`.

**The path matters.** `/etc/nginx/conf.d/` does not exist on this server and is not
included by its nginx config; a vhost written there is silently never read. aaPanel's
nginx includes `/www/server/panel/vhost/nginx/*.conf`, which is why the file goes there.

Odoo uses **two** ports: 8069 for pages and **8072 for the live channel** that pushes
updates to the till. Omit the `odoochat` upstream and the POS appears to work but never
syncs between counters. A websocket needs the explicit `Upgrade`/`Connection` headers;
a plain proxy pass will not switch protocol.

`client_max_body_size 200M` because nginx defaults to 1 MB and would reject product
image uploads.

To undo: `rm /www/server/panel/vhost/nginx/odoo.conf && systemctl reload nginx`.

---

## 13. Prove you can take a backup — before there is anything to lose

**What you are doing:** running one real backup and confirming the file is valid.

```bash
mkdir -p /var/backups/odoo && chmod 700 /var/backups/odoo
su -s /bin/bash postgres -c \
  "pg_dump -Fc -d ostore_live -f /var/backups/odoo/ostore_live_first.dump"
ls -lh /var/backups/odoo/
pg_restore -l /var/backups/odoo/ostore_live_first.dump | head -5
```

**Expect:** a file of a few MB, and `pg_restore -l` listing table entries rather than
erroring.

**Why do it now, on an empty database:** a backup you have never restored is not a
backup. Testing the mechanism while the database holds nothing means a failure costs you
nothing. Discovering the same failure in six months, with a year of sales in it, is a
different day entirely.

**Why each part:**

- `-Fc` is PostgreSQL's compressed custom format. Smaller than plain SQL, and
  `pg_restore` can read it selectively — restore one table without the rest.
- `pg_restore -l` lists what is *inside* the dump without restoring anything. It is the
  cheapest possible proof the file is not truncated or empty.
- `chmod 700` because these dumps contain every customer name, every price and every
  ledger balance in the shop. Treat the directory like the safe.

**A database dump must never be committed to git or uploaded anywhere shared.** That is
why `.gitignore` in this repository excludes `*.dump` and `*.sql`.

The data directory holds product images and attachments, which are **not** in the
database dump. A complete backup is both:

```bash
tar czf /var/backups/odoo/filestore_first.tgz -C /opt/odoo/.local/share Odoo
```

Automating this on a schedule is listed under *Not covered here*; do it before go-live.

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
| POS syncs nothing between two counters | `odoochat` upstream missing from nginx | step 12 |

## Not covered here

- **HTTPS** — needs a domain first, then `certbot --nginx`. Until then, logins travel in
  clear text over the internet. Do not run a real shop on plain HTTP for long.
- **Scheduling the backup** from step 13 (a nightly cron plus off-server copies). A
  backup that only exists on the same machine does not survive that machine dying.
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
