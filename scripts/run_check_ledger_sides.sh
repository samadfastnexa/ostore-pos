#!/usr/bin/env bash
# ==============================================================================
# READ-ONLY: list contacts whose khata sits on the wrong side -- vendors in the
# customer khata, customers in the vendor khata (scripts/check_ledger_sides.py).
# Writes nothing.
#
#     bash scripts/run_check_ledger_sides.sh
#
# Optional: IMPORT_BRANCH (e.g. Bahria) to check one branch only.
# ==============================================================================
set -euo pipefail

ODOO_PYTHON="/opt/odoo/venv/bin/python3"
ODOO_BIN="/opt/odoo/odoo/odoo-bin"
ODOO_CONF="/etc/odoo/odoo.conf"
ODOO_DB="${ODOO_DB:-ostore_live}"
SCRIPT="/opt/odoo/custom_addons/pos_retail/scripts/check_ledger_sides.py"

for f in "$ODOO_CONF" "$SCRIPT"; do
    [ -f "$f" ] || { echo "Error: $f not found"; exit 1; }
done

sudo -u odoo env \
    IMPORT_BRANCH="${IMPORT_BRANCH:-}" \
    PYTHONIOENCODING=utf-8 \
    "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" --no-http < "$SCRIPT"
