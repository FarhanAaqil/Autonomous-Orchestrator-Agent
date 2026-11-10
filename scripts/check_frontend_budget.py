"""Enforce modest compressed artifact budgets and an independently loaded 3D chunk."""
import gzip
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
scripts = list((root / 'assets').glob('*.js'))
initial = [p for p in scripts if p.name.startswith('index-')]
optional = [p for p in scripts if p.name.startswith('Graph-')]
assert initial and optional, 'Expected separate main and optional 3D chunks'
for label, paths, maximum in [('initial', initial, 180_000), ('optional 3D', optional, 300_000)]:
    size = sum(len(gzip.compress(p.read_bytes())) for p in paths)
    assert size <= maximum, f'{label} exceeds {maximum} compressed bytes: {size}'
    print(f'{label}: {size} compressed bytes (limit {maximum})')
assert 'Graph-' not in (root/'index.html').read_text(), '3D must not preload on entry'
