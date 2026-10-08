import os,pathlib,sys
ROOT=pathlib.Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else pathlib.Path(__file__).resolve().parents[1]
CODEX_HOME=pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
VERSION='0.9.5'
APP_NAME='守岸人Codex桌宠启动'
EXECUTABLE_NAME=APP_NAME+'.exe'
PORTABLE_DIRNAME='守岸人Codex桌宠'
AUDIO_SESSION_NAME='守岸人 · Codex'
APPLICATION_ID='Doya16.Shorekeeper.Codex'

UPDATE_REPOSITORY='Doya16/shorekeeper-codex-pet'
