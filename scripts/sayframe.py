"""SAYFRAME skill entry point. No API keys, desktop app or remote service needed."""
import sys,json,subprocess,os
from pathlib import Path
root=Path(__file__).resolve().parents[1]
config=root/'runtime/config.json'
if config.is_file():
    python=Path(json.loads(config.read_text('utf8'))['python'])
    if python.resolve()!=Path(sys.executable).resolve():
        raise SystemExit(subprocess.call([str(python),str(Path(__file__).resolve()),*sys.argv[1:]],env={**os.environ,'PYTHONUTF8':'1'}))
sys.path.insert(0,str(root/'engine'))
from agent import main
if __name__=='__main__':
    main()
