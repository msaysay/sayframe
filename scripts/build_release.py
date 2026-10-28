"""Package the explicit skill manifest. No projects, media, runtime or git history."""
import hashlib,json,re,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def build():
    data=json.loads((ROOT/'manifest.json').read_text('utf-8'));version=re.search(r"^VERSION='([^']+)'",(ROOT/'engine/agent.py').read_text('utf-8'),re.M).group(1)
    files={}
    for name in data['files']:
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or ':' in name or {'runtime','uploads','exports','credentials','.git'}&set(path.parts):raise ValueError('Unsafe release entry.')
        files[name]=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    data.update(version=version,files=files);(ROOT/'manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    release=ROOT/'dist';release.mkdir(exist_ok=True);target=release/f'SAYFRAME-WorkBuddy-{version}.zip'
    if target.exists():raise ValueError('Release already exists; bump the version instead of overwriting it.')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name in [*files,'manifest.json']:archive.write(ROOT/name,'sayframe-workbuddy/'+name)
    digest=hashlib.sha256(target.read_bytes()).hexdigest();(release/'SHA256SUMS').write_text(f'{digest}  {target.name}\n',encoding='ascii')
    print(json.dumps({'zip':str(target),'files':len(files)+1,'sha256':digest}))
if __name__=='__main__':build()
