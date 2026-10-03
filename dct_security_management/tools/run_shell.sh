#!/usr/bin/env bash
set -euo pipefail
export ODOO_RC=/dev/null
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB="${1:?Specify isolated dct_security_test_* database}"
SCRIPT="${2:?Specify Python validation script}"
case "$DB" in dct_security_test_*) ;; *) echo 'Only dedicated test databases are allowed.' >&2; exit 2;; esac
exec "${ODOO_PYTHON:-/home/mustafa/work/env/bin/python}" "${ODOO_ROOT:-/home/mustafa/work/odoo}/odoo-bin" shell \
 -c /dev/null --addons-path="${ODOO_ROOT:-/home/mustafa/work/odoo}/addons,$ROOT" \
 --db_host=/var/run/postgresql --db_user="$(id -un)" -d "$DB" --no-http --max-cron-threads=0 \
 --data-dir=/home/mustafa/.local/share/dct-security-validation --log-level=warn < "$SCRIPT"
