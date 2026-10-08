#!/usr/bin/env bash
# ==============================================================================
# Move a vendor's khata from the customer ledger to the vendor ledger, every
# adjustment and payment row at once (scripts/move_khata_to_vendor.py).
#
# CHECK by default -- prints what would move, writes nothing:
#     PARTNER_IDS="44,52" bash scripts/run_move_khata_to_vendor.sh
# Then, once the check looks right:
#     PARTNER_IDS="44,52" APPLY=1 bash scripts/run_move_khata_to_vendor.sh
#
# PARTNER_IDS are the ids printed by: bash scripts/run_check_ledger_sides.sh
# ==============================================================================
set -euo pipefail

ODOO_PYTHON="/opt/odoo/venv/bin/python3"
ODOO_BIN="/opt/odoo/odoo/odoo-bin"
ODOO_CONF="/etc/odoo/odoo.conf"
ODOO_DB="${ODOO_DB:-ostore_live}"
SCRIPT="/opt/odoo/custom_addons/pos_retail/scripts/move_khata_to_vendor.py"

for f in "$ODOO_CONF" "$SCRIPT"; do
    [ -f "$f" ] || { echo "Error: $f not found"; exit 1; }
done

sudo -u odoo env \
    APPLY="${APPLY:-0}" \
    PARTNER_IDS="${PARTNER_IDS:-}" \
    PYTHONIOENCODING=utf-8 \
    "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" --no-http < "$SCRIPT"
