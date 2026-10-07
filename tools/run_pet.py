"""Source and PyInstaller entry point, independent of the working directory."""
import pathlib,sys

if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))

from shorekeeper_pet.launcher import run

if __name__=='__main__':
    raise SystemExit(run())
