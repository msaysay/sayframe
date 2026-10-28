"""Install only manifest-listed SAYFRAME files; never copy a developer runtime."""
import argparse,datetime,hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def install(dest):
    manifest=json.loads((ROOT/'manifest.json').read_text('utf-8'));files=manifest['files'];dest=Path(dest).expanduser().resolve()
    if dest==ROOT:raise ValueError('Source and installation directory must differ.')
    for name,sha in files.items():
        parts=Path(name).parts
        if Path(name).is_absolute() or '..' in parts or ':' in name or {'runtime','uploads','exports','credentials','.git'}&set(parts):raise ValueError('Unsafe manifest path: '+name)
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:raise ValueError('Source integrity mismatch: '+name)
    if dest.exists() and not (dest/'manifest.json').is_file():raise ValueError('Destination exists without a SAYFRAME manifest; nothing overwritten.')
    backup=None
    if (dest/'manifest.json').is_file():
        previous=json.loads((dest/'manifest.json').read_text('utf-8'))
        if not {'SKILL.md','engine/agent.py'}<=set(previous.get('files',{})):raise ValueError('Destination is not a recognized SAYFRAME installation.')
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');backup=dest.parent.parent/'skill-backups'/('sayframe-'+stamp)
        for name in [*previous['files'],'manifest.json']:
            path=Path(name)
            if path.is_absolute() or '..' in path.parts or ':' in name or {'runtime','uploads','exports','credentials','.git'}&set(path.parts):raise ValueError('Unsafe previous manifest.')
            if (dest/name).is_file():target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(dest/name,target)
    for name in [*files,'manifest.json']:
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,target)
    return {'installed':str(dest),'version':manifest['version'],'files':len(files)+1,'runtimePreserved':True,'codeBackup':str(backup) if backup else None,'next':'Start a new WorkBuddy conversation. Explain first-run downloads before setup. Do not update during active editing jobs.'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dest',default=str(Path.home()/'.workbuddy/skills/sayframe-workbuddy'));args=p.parse_args()
    print(json.dumps(install(args.dest),ensure_ascii=False))
