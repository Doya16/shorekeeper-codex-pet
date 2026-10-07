import os,pathlib,sys
ROOT=pathlib.Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else pathlib.Path(__file__).resolve().parents[1]
CODEX_HOME=pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
VERSION='0.9.0'
APP_NAME='守岸人Codex桌宠启动'
EXECUTABLE_NAME=APP_NAME+'.exe'
PORTABLE_DIRNAME='守岸人Codex桌宠'
