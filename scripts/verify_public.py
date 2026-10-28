"""Fail closed on private paths/media and verify installable file integrity."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEXT={'.py','.md','.json','.html','.svg','.txt','.yml','.yaml'}
MEDIA={'.mp4','.mkv','.mov','.avi','.webm','.mp3','.m4a','.wav','.ogg','.flac','.pem','.key','.env'}
PATTERNS=[re.compile(r'C:[/\\]Users[/\\]'+r'admin',re.I),re.compile(r'(?:sk-api-|sk-|tp-)[a-zA-Z0-9_-]{32,}'),re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')]
IMAGES={'assets/covers/style-reference.png',*[f'assets/github/{kind}.{lang}.png' for kind in ('banner','workflow') for lang in ('en','zh-CN')]}

def verify():
    manifest=json.loads((ROOT/'manifest.json').read_text('utf-8'))
    for name,sha in manifest['files'].items():
        path=Path(name)
        assert not path.is_absolute() and '..' not in path.parts and ':' not in name,name
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,'Integrity: '+name
    checked=0
    for path in ROOT.rglob('*'):
        relative=path.relative_to(ROOT)
        if {'.git','dist','__pycache__','.pytest_cache'}&set(relative.parts):continue
        if not path.is_file():continue
        name=relative.as_posix();checked+=1
        assert not {'runtime','uploads','exports','projects','node_modules'}&set(relative.parts),'Private directory: '+name
        assert path.suffix.lower() not in MEDIA,'Private media/key: '+name
        if path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.gif'}:assert name in IMAGES,'Unreviewed image: '+name
        if path.suffix.lower() in TEXT:
            value=path.read_text('utf-8-sig')
            assert not any(pattern.search(value) for pattern in PATTERNS),'Private pattern: '+name
    for readme in ('README.md','README.zh-CN.md'):
        value=(ROOT/readme).read_text('utf-8')
        for ref in re.findall(r'(?:src="|\]\()([^"\)]+)',value):
            if '://' in ref or ref.startswith('#'):continue
            assert (ROOT/ref.split('#')[0]).is_file(),'Broken documentation link: '+ref
    return {'passed':True,'version':manifest['version'],'reviewedFiles':checked,'manifestFiles':len(manifest['files']),'privateMediaIncluded':False}

if __name__=='__main__':print(json.dumps(verify()))
