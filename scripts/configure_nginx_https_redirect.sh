#!/bin/bash
set -e

# Turnkey Script to Configure Nginx HTTP->HTTPS Redirect & Odoo Proxy Mode
# Run as root on the server (169.58.143.45)

echo "============================================================"
echo "CONFIGURING NGINX HTTP->HTTPS REDIRECT & ODOO PROXY MODE"
echo "============================================================"

NGINX_CONF="/www/server/panel/vhost/nginx/odoo.conf"
ODOO_CONF="/etc/odoo/odoo.conf"

# 1. Ensure proxy_mode = True in /etc/odoo/odoo.conf
if [ -f "$ODOO_CONF" ]; then
    if grep -q "proxy_mode" "$ODOO_CONF"; then
        sed -i 's/^[# ;]*proxy_mode.*/proxy_mode = True/' "$ODOO_CONF"
    else
        sed -i '/\[options\]/a proxy_mode = True' "$ODOO_CONF"
    fi
    echo "[OK] /etc/odoo/odoo.conf verified with proxy_mode = True"
else
    echo "[WARN] $ODOO_CONF not found at default location!"
fi

# 2. Check Nginx certificate location
CERT_PATH=""
KEY_PATH=""
for p in \
    "/www/server/panel/vhost/cert/169-58-143-45.sslip.io" \
    "/www/server/panel/vhost/cert/odoo" \
    "/etc/letsencrypt/live/169-58-143-45.sslip.io"
do
    if [ -f "$p/fullchain.pem" ] && [ -f "$p/privkey.pem" ]; then
        CERT_PATH="$p/fullchain.pem"
        KEY_PATH="$p/privkey.pem"
        echo "[OK] Found SSL certs at $p"
        break
    fi
done

# If certs not in standard directory, find existing configured cert in nginx
if [ -z "$CERT_PATH" ]; then
    EXISTING_CERT=$(grep -m 1 "ssl_certificate " /www/server/panel/vhost/nginx/*.conf 2>/dev/null | awk '{print $2}' | tr -d ';' || true)
    EXISTING_KEY=$(grep -m 1 "ssl_certificate_key " /www/server/panel/vhost/nginx/*.conf 2>/dev/null | awk '{print $2}' | tr -d ';' || true)
    if [ -n "$EXISTING_CERT" ] && [ -f "$EXISTING_CERT" ]; then
        CERT_PATH="$EXISTING_CERT"
        KEY_PATH="$EXISTING_KEY"
        echo "[OK] Found active SSL cert in Nginx: $CERT_PATH"
    fi
fi

# 3. Back up any conflicting duplicate aaPanel vhost files
for other in /www/server/panel/vhost/nginx/*.conf; do
    if [ "$other" != "$NGINX_CONF" ] && grep -q "169-58-143-45.sslip.io" "$other" 2>/dev/null; then
        echo "[OK] Backing up conflicting duplicate vhost $other to ${other}.bak"
        mv "$other" "${other}.bak"
    fi
done

# 4. Create single unified Nginx config with HTTP -> HTTPS 301 redirection
if [ -n "$CERT_PATH" ] && [ -f "$CERT_PATH" ]; then
    cat > "$NGINX_CONF" <<EOF
upstream odoo_app  { server 127.0.0.1:8069; }
upstream odoo_chat { server 127.0.0.1:8072; }

# HTTP: Redirect all plain HTTP traffic (IP and Domain) to secure HTTPS
server {
    listen 80;
    server_name 169.58.143.45 169-58-143-45.sslip.io;
    return 301 https://169-58-143-45.sslip.io\$request_uri;
}

# HTTPS: Secure Odoo service with strict forwarding headers
server {
    listen 443 ssl;
    server_name 169-58-143-45.sslip.io 169.58.143.45;
    client_max_body_size 200M;

    ssl_certificate $CERT_PATH;
    ssl_certificate_key $KEY_PATH;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers EECDH+CHACHA20:EECDH+AES128:RSA+AES128:EECDH+AES256:RSA+AES256:!MD5;
    ssl_prefer_server_ciphers on;

    proxy_read_timeout 720s;
    proxy_connect_timeout 720s;
    proxy_send_timeout 720s;

    proxy_set_header Host \$host;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Real-IP \$remote_addr;

    location /websocket {
        proxy_pass http://odoo_chat;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
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
    echo "[OK] Generated clean $NGINX_CONF with HTTP->HTTPS 301 redirection."
    nginx -t
    nginx -s reload
    echo "[OK] Nginx reloaded successfully without warnings."
else
    echo "[WARN] Could not automatically locate SSL cert paths. Please verify aaPanel SSL settings."
fi

echo "============================================================"
echo "NGINX & PROXY MODE CONFIGURATION COMPLETE"
echo "============================================================"
