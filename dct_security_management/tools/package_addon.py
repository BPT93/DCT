"""Validate source files and build a clean, installable addon archive."""
import ast
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

root = Path(__file__).resolve().parents[1]
manifest = ast.literal_eval((root / '__manifest__.py').read_text(encoding='utf-8'))
excluded = {'.validation', '__pycache__', '.git'}
files = sorted(path for path in root.rglob('*') if path.is_file()
               and not excluded.intersection(path.relative_to(root).parts)
               and path.suffix not in {'.pyc', '.pyo'})
counts = {'python': 0, 'xml': 0}
for path in files:
    if path.suffix == '.py':
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        counts['python'] += 1
    elif path.suffix == '.xml':
        ET.parse(path)
        counts['xml'] += 1
for name in manifest['data'] + manifest.get('demo', []):
    assert (root / name).is_file(), name
for bundle in manifest['assets'].values():
    for name in bundle:
        assert (root.parent / name).is_file(), name
assert set(manifest['depends']) == {'web', 'mail', 'hr', 'hr_attendance', 'hr_holidays', 'account'}
assert manifest['installable'] and manifest['application']
for catalog in ('ar.po', 'dct_security_management.pot'):
    assert (root / 'i18n' / catalog).stat().st_size > 1000, f'Empty or incomplete translation catalog: {catalog}'
destination = root.parent / 'dist'
destination.mkdir(exist_ok=True)
archive = destination / f"{root.name}-{manifest['version']}.zip"
with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
    for path in files:
        output.write(path, arcname=Path(root.name) / path.relative_to(root))
with zipfile.ZipFile(archive) as output:
    assert output.testzip() is None
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
archive.with_suffix('.zip.sha256').write_text(f'{checksum}  {archive.name}\n', encoding='utf-8')
print({'archive': str(archive), 'files': len(files), 'bytes': archive.stat().st_size,
       'sha256': checksum, 'parsed': counts})
