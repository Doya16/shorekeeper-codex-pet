import os,pathlib,sys
ROOT=pathlib.Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else pathlib.Path(__file__).resolve().parent
CODEX_HOME=pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
VERSION='0.8.2'
