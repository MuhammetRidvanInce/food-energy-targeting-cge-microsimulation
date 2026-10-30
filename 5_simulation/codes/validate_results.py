"""Strict input checks for reruns in the portable English replication package."""
from common import sha

def verify_source(path,expected):
    actual=sha(path)
    if actual!=expected:
        raise AssertionError(f'Input changed since the reference run: {path.name}. Regenerate the base analysis before dependent coverage analyses.')

if __name__=='__main__':
    import runpy
    from pathlib import Path
    runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/validate_public_release.py'),run_name='__main__')
