#!/usr/bin/env bash
# ==============================================================================
# Import ONLY the "3rd oct 2026" tab of the Murshid Store sheet into the Bahria
# branch. The Bahria tabs, the other dated tabs and their products are not read
# or touched. The rules are those of scripts/import_1st_oct_2026.py, which this
# runs with the tab set -- that file must be on the server too.
#
# CHECK by default -- prints what would change, writes nothing:
#     bash scripts/run_import_3rd_oct_2026.sh
# Then, once the check looks right:
#     APPLY=1 bash scripts/run_import_3rd_oct_2026.sh
#
# Optional: IMPORT_BRANCH (default Bahria).
# ==============================================================================
set -euo pipefail

TAB="3rd oct 2026"
ODOO_PYTHON="/opt/odoo/venv/bin/python3"
ODOO_BIN="/opt/odoo/odoo/odoo-bin"
ODOO_CONF="/etc/odoo/odoo.conf"
ODOO_DB="${ODOO_DB:-ostore_live}"
SCRIPT="/opt/odoo/custom_addons/pos_retail/scripts/import_1st_oct_2026.py"
BRANCH="${IMPORT_BRANCH:-Bahria}"
APPLY="${APPLY:-0}"

for f in "$ODOO_CONF" "$SCRIPT"; do
    [ -f "$f" ] || { echo "Error: $f not found"; exit 1; }
done

echo "=============================================================================="
if [ "$APPLY" = "1" ]; then
    echo "IMPORTING '${TAB}' into ${ODOO_DB}, branch '${BRANCH}' -- this writes to the database"
else
    echo "CHECK of '${TAB}' on ${ODOO_DB}, branch '${BRANCH}' -- nothing is written"
    echo "(re-run with APPLY=1 to import)"
fi
echo "=============================================================================="

sudo -u odoo env \
    APPLY="$APPLY" \
    IMPORT_BRANCH="$BRANCH" \
    IMPORT_TAB="$TAB" \
    PYTHONIOENCODING=utf-8 \
    "$ODOO_PYTHON" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$ODOO_DB" --no-http < "$SCRIPT"
