from pathlib import Path
from io import BytesIO
from odoo.modules.module import get_module_path
from odoo.tools.translate import trans_export

root = Path(get_module_path('dct_security_management'))
(root / 'i18n').mkdir(exist_ok=True)
output = BytesIO()
trans_export(None, ['dct_security_management'], output, 'po', env)
target = root / 'i18n/dct_security_management.pot'
temporary = target.with_suffix('.pot.new')
try:
    temporary.write_bytes(output.getvalue())
    temporary.replace(target)
finally:
    temporary.unlink(missing_ok=True)
print('TRANSLATION_TEMPLATE_EXPORTED')
