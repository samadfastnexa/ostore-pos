#!/usr/bin/env bash
# ==============================================================================
# Murshid Store catalogue & stock import on the live server (ostore_live).
#
# Reads the shared Google Sheet and imports, into one branch:
#   1. Bahria Paints                                   (scripts/import_paints.py)
#   2. Bahria POLISH, Bahria Chemicals, Bahria Electric (scripts/import_categories.py)
#
# DRY RUN by default -- prints what would change, writes nothing:
#     bash scripts/run_import_on_server.sh
# Then, once the dry run looks right:
#     APPLY=1 bash scripts/run_import_on_server.sh
#
# Optional: IMPORT_BRANCH (default Bahria), IMPORT_TABS (e.g. "Bahria Electric",
# for the second script only), FORCE_STOCK=1 (re-count already counted products,
# OVERWRITING live stock -- almost never what you want).
# ==============================================================================
set -euo pipefail

ODOO_PYTHON="/opt/odoo/venv/bin/python3"
ODOO_BIN="/opt/odoo/odoo/odoo-bin"
ODOO_CONF="/etc/odoo/odoo.conf"
ODOO_DB="${ODOO_DB:-ostore_live}"
SCRIPTS="/opt/odoo/custom_addons/pos_retail/scripts"
BRANCH="${IMPORT_BRANCH:-Bahria}"
APPLY="${APPLY:-0}"

for f in "$ODOO_CONF" "$SCRIPTS/import_paints.py" "$SCRIPTS/import_categories.py"; do
    [ -f "$f" ] || { echo "Error: $f not found"; exit 1; }
done

run() {
    sudo -u odoo env \
        APPLY="$APPLY" \
        PAINTS_BRANCH="$BRANCH" \
        IMPORT_BRANCH="$BRANCH" \
        IMPORT_TABS="${IMPORT_TABS:-}" \
        FORCE_STOCK="${FORCE_STOCK:-0}" \
        "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" --no-http < "$1"
}

echo "=============================================================================="
if [ "$APPLY" = "1" ]; then
    echo "IMPORTING into ${ODOO_DB}, branch '${BRANCH}' -- this writes to the database"
else
    echo "DRY RUN on ${ODOO_DB}, branch '${BRANCH}' -- nothing is written"
    echo "(re-run with APPLY=1 to import)"
fi
echo "=============================================================================="

run "$SCRIPTS/import_paints.py"
run "$SCRIPTS/import_categories.py"

echo "=============================================================================="
[ "$APPLY" = "1" ] && echo "Import finished." || echo "Dry run finished -- nothing was written."
echo "=============================================================================="
