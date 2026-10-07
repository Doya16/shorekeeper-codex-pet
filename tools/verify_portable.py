"""Exercise the distributed executable without access to development runtimes."""
import argparse,json,os,pathlib,subprocess,sys,zipfile
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from shorekeeper_pet.paths import EXECUTABLE_NAME

def verify(folder):
    folder=pathlib.Path(folder).resolve()
    report=folder/'package-check.json'
    if report.exists(): report.unlink()
    env=os.environ.copy()
    env['PATH']=str(pathlib.Path(env.get('SystemRoot','C:/Windows'))/'System32')
    # Exercise the actual Windows font loader. The offscreen plugin has a
    # different font backend and fails on some non-ASCII font paths.
    env['QT_QPA_PLATFORM']='windows'
    for key in ('PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH','QML2_IMPORT_PATH'):
        env.pop(key,None)
    result=subprocess.run([str(folder/EXECUTABLE_NAME),'--verify-package'],cwd=folder.parent,env=env,timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode or not report.exists():
        error=folder/'startup-error.log'
        raise RuntimeError(error.read_text('utf8') if error.exists() else f'Package failed, exit={result.returncode}')
    data=json.loads(report.read_text('utf8'))
    assert data['ok'] and data['frozen'] and data['assets']>=83, data
    return data

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    parser=argparse.ArgumentParser(); parser.add_argument('folder'); args=parser.parse_args()
    print(json.dumps(verify(args.folder),ensure_ascii=False))
