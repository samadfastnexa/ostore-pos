# Deploying pos_retail to the production server

Written for the Contabo VPS at `169.58.143.45` (Ubuntu 24.04, aaPanel). Every step
says what it does and why, because the reasons are the part you need when something
behaves differently on the next server.

**Substitute your own values wherever you see `CHANGEME_DB` and `CHANGEME_MASTER`.**

Before starting, know the one thing that makes this box unusual: **aaPanel owns it**.
PostgreSQL and nginx are both installed under `/www/server`, not the system paths, so
generic Odoo guides send you to directories that either do not exist here or are never
read. Every step below accounts for that.

---

## 1. Safety net and swap

```bash
cp /www/server/pgsql/data/pg_hba.conf /root/pg_hba.conf.bak
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h
```

**Expect:** `Swap: 2.0Gi`

`pg_hba.conf` is PostgreSQL's access-rules file; back it up before anything else goes
near it. The swapfile matters because the server ships with **none**: without swap a
memory spike does not slow the machine, the kernel simply kills the largest process,
which is Odoo. `chmod 600` because swap can contain fragments of memory including
passwords. The `fstab` line is what makes it survive a reboot.

---

## 2. System packages

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

## 3. Database role

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

`CREATEDB` is required: Odoo creates and drops databases itself, and step 7 fails
without it. It is deliberately **not** `SUPERUSER`.

> On this server `pg_hba.conf` is set to `trust`, so the password is not actually
> checked. Set a real one anyway, so nothing breaks when that is hardened later.

---

## 4. Fetch the code

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

## 5. Python environment

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
discover in step 7.

---

## 6. Configuration

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
limit_time_real = 300
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
| `workers = 3` | Separate processes rather than one thread. Below 2, the POS long-polling channel blocks the whole server. |
| `limit_time_real = 300` | Kills a request stuck beyond 5 minutes, so one bad report cannot hang a worker forever. |
| `list_db = False` | Hides the database selector from the internet. |

`chmod 640` because the file holds two passwords in clear text.

---

## 7. Create the database

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

## 8. Run it as a service

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

## 9. Web server

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
| `role "odoo" does not exist` | step 3 not run | re-run step 3 |
| `no pg_hba.conf entry for host` | PostgreSQL rejecting TCP auth | check `pg_hba.conf`; restore `/root/pg_hba.conf.bak` if needed |
| nginx 502 | Odoo not running | `journalctl -u odoo -n 50` |
| Login page loads unstyled | `node-less` / `rtlcss` missing | re-run step 2, `systemctl restart odoo` |
| Addon not in the Apps list | cloned to the wrong folder name | must be `pos_retail` |
| `This account is currently not available` | `--system` user has no shell | keep `-s /bin/bash` |

## Not covered here

HTTPS (needs a domain, then `certbot --nginx`), automated backups, monitoring, and
firewalling port 8069 once nginx is proxying (`ufw deny 8069`). `pg_hba.conf` is left at
`trust`, which means anyone with shell access can reach PostgreSQL without a password —
worth hardening once the system is stable, carefully, because aaPanel may rely on it.
