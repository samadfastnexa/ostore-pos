#!/usr/bin/env bash
# ==============================================================================
# Murshid Store catalogue & stock import on the live server (ostore_live).
#
# Reads the shared Google Sheet -- every tab whose name starts with "Bahria",
# new tabs included -- and creates/updates the products and categories of one
# branch (scripts/import_catalogue.py).
#
# CHECK by default -- prints what would change, writes nothing:
#     bash scripts/run_import_on_server.sh
# Then, once the check looks right:
#     APPLY=1 bash scripts/run_import_on_server.sh
#
# Optional: IMPORT_BRANCH (default Bahria), IMPORT_TABS (e.g. "Bahria Hardware"
# or "Bahria Hardware,Bahria Electric"), FORCE_STOCK=1 (re-count already counted
# products, OVERWRITING live stock -- almost never what you want).
# ==============================================================================
set -euo pipefail

ODOO_PYTHON="/opt/odoo/venv/bin/python3"
ODOO_BIN="/opt/odoo/odoo/odoo-bin"
ODOO_CONF="/etc/odoo/odoo.conf"
ODOO_DB="${ODOO_DB:-ostore_live}"
SCRIPT="/opt/odoo/custom_addons/pos_retail/scripts/import_catalogue.py"
BRANCH="${IMPORT_BRANCH:-Bahria}"
APPLY="${APPLY:-0}"

for f in "$ODOO_CONF" "$SCRIPT"; do
    [ -f "$f" ] || { echo "Error: $f not found"; exit 1; }
done

echo "=============================================================================="
if [ "$APPLY" = "1" ]; then
    echo "IMPORTING into ${ODOO_DB}, branch '${BRANCH}' -- this writes to the database"
else
    echo "CHECK on ${ODOO_DB}, branch '${BRANCH}' -- nothing is written"
    echo "(re-run with APPLY=1 to import)"
fi
echo "=============================================================================="

sudo -u odoo env \
    APPLY="$APPLY" \
    IMPORT_BRANCH="$BRANCH" \
    IMPORT_TABS="${IMPORT_TABS:-}" \
    FORCE_STOCK="${FORCE_STOCK:-0}" \
    PYTHONIOENCODING=utf-8 \
    "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" --no-http < "$SCRIPT"
