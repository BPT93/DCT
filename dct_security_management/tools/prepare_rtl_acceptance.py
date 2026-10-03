"""Rebuild Arabic translations and generated CSS in the disposable review DB."""
assert env.cr.dbname.startswith('dct_security_test_')
env['ir.module.module'].search([('name', '=', 'dct_security_management')])._update_translations(
    filter_lang=['ar_001'], overwrite=True)
assets = env['ir.attachment'].search([('url', '=like', '/web/assets/%'), ('mimetype', '=', 'text/css')])
count = len(assets)
assets.unlink()
env.cr.commit()
print('ARABIC_CATALOG_RELOADED_AND_GENERATED_CSS_INVALIDATED', count)
print('CONFIGURED_COMPANY_LOGO_BYTES', len(env.company.logo or b''))
