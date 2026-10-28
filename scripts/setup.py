"""Prepare only this skill's runtime. No keys or application config are read."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tarfile,urllib.request,uuid,venv,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'runtime'
PACKAGES=['faster-whisper==1.2.1','av==15.1.0','numpy==2.2.6','onnxruntime==1.22.1','kaldi-native-fbank==1.21.2','Pillow==11.3.0','jieba==0.42.1']
def download(url,target):
    target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix(target.suffix+'.part')
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'SAYFRAME-WorkBuddy/0.1'}),timeout=90) as response,temp.open('wb') as out:shutil.copyfileobj(response,out)
    os.replace(temp,target)
def validate_members(names):
    for name in names:
        normalized=name.replace('\\','/')
        if normalized.startswith('/') or ':' in normalized or '..' in Path(normalized).parts:raise ValueError('不安全的压缩包路径，未解压。')
def main():
    p=argparse.ArgumentParser(description='仅初始化SAYFRAME技能私有运行环境。首次需联网下载依赖及模型，不需要API Key。')
    p.add_argument('--skip-install',action='store_true');p.add_argument('--ffmpeg');p.add_argument('--ffprobe');p.add_argument('--acoustic-model');p.add_argument('--whisper-model');a=p.parse_args()
    if not (3,11)<=sys.version_info[:2]<=(3,12):raise SystemExit('本版请使用Python 3.11或3.12，以匹配音视频依赖。')
    RUNTIME.mkdir(parents=True,exist_ok=True)
    python=Path(sys.executable)
    if not a.skip_install:
        env=RUNTIME/'python';venv.create(env,with_pip=True)
        python=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check',*PACKAGES],check=True)
    ff=Path(a.ffmpeg).resolve() if a.ffmpeg else Path(shutil.which('ffmpeg') or '')
    probe=Path(a.ffprobe).resolve() if a.ffprobe else ff.with_name('ffprobe.exe' if os.name=='nt' else 'ffprobe')
    if not ff.is_file() or not probe.is_file():
        if os.name!='nt':raise SystemExit('本版自动准备面向Windows；其他系统请提供--ffmpeg和--ffprobe。')
        archive=RUNTIME/'ffmpeg-release-essentials.zip';base='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
        download(base+'.sha256',archive.with_suffix('.sha256'));expected=archive.with_suffix('.sha256').read_text().split()[0].lower()
        download(base,archive)
        with archive.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=expected:raise SystemExit('FFmpeg发行方校验失败，未运行。')
        with zipfile.ZipFile(archive) as z:validate_members(z.namelist());z.extractall(RUNTIME/'ffmpeg')
        ff=next((RUNTIME/'ffmpeg').rglob('ffmpeg.exe'));probe=next((RUNTIME/'ffmpeg').rglob('ffprobe.exe'))
    model=Path(a.acoustic_model).resolve() if a.acoustic_model else RUNTIME/'models/sensevoice'
    if not (model/'model.int8.onnx').is_file() or not (model/'tokens.txt').is_file():
        archive=RUNTIME/'sensevoice.tar.bz2'
        download('https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2',archive)
        with tarfile.open(archive) as t:
            validate_members(t.getnames())
            if any(m.issym() or m.islnk() or not (m.isfile() or m.isdir()) for m in t.getmembers()):raise ValueError('模型包包含非普通文件，未解压。')
            t.extractall(RUNTIME/'models/sensevoice-download',filter='data')
        downloaded=next((RUNTIME/'models/sensevoice-download').rglob('model.int8.onnx')).parent;model.mkdir(parents=True,exist_ok=True)
        for name in ('model.int8.onnx','tokens.txt'):shutil.copyfile(downloaded/name,model/name)
    config={'version':1,'python':str(python),'ffmpeg':str(ff),'ffprobe':str(probe),'acousticModel':str(model),'whisperModel':str(Path(a.whisper_model).resolve()) if a.whisper_model else 'small','apiKeysRequired':False}
    (RUNTIME/'config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf8')
    subprocess.run([str(python),str(ROOT/'scripts/sayframe.py'),'doctor'],check=True)
    print('SAYFRAME本地组件已准备好。优先WorkBuddy原生转写加本地声音定位；Whisper为可选模式，首次选用时下载模型。无需额外API Key。')
if __name__=='__main__':main()
