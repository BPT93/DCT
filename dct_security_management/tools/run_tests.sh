#!/usr/bin/env bash
set -euo pipefail
export ODOO_RC=/dev/null
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ODOO_ROOT="${ODOO_ROOT:-/home/mustafa/work/odoo}"
PYTHON="${ODOO_PYTHON:-/home/mustafa/work/env/bin/python}"
DB="${1:-dct_security_test_20261003}"
MODE="${2:-install}"
case "$DB" in dct_security_test_*) ;; *) echo 'Use a dedicated dct_security_test_* database.' >&2; exit 2;; esac
case "$MODE" in install) OP=-i;; upgrade) OP=-u;; *) echo 'Mode must be install or upgrade';exit 2;; esac
VALIDATION_DIR="${DCT_VALIDATION_DIR:-/home/mustafa/.local/share/dct-security-validation}"
mkdir -p "$VALIDATION_DIR"
exec "$PYTHON" "$ODOO_ROOT/odoo-bin" -c /dev/null --addons-path="$ODOO_ROOT/addons,$ROOT" \
  --db_host=/var/run/postgresql --db_user="$(id -un)" -d "$DB" \
  "$OP" dct_security_management --without-demo=all --test-enable --test-tags /dct_security_management \
  --stop-after-init --max-cron-threads=0 --http-interface=127.0.0.1 --http-port=18079 \
  --data-dir="$VALIDATION_DIR" --logfile="$VALIDATION_DIR/$DB-$MODE.log"
