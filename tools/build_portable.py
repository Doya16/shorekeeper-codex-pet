import os,pathlib,subprocess,sys,shutil
root=pathlib.Path(__file__).resolve().parents[1]
args=[sys.executable,'-m','PyInstaller','--clean','--noconfirm','--onedir','--windowed','--name','Shorekeeper','--icon',str(root/'assets/shorekeeper.ico'),'--distpath',str(root/'dist'),'--workpath',str(root/'build'),'--specpath',str(root)]
for module in ('pandas','scipy','matplotlib','tkinter','PySide6.QtWebEngineCore','PySide6.QtQml'): args+=['--exclude-module',module]
args+=[str(root/'launcher.py')]
# Do not let unrelated developer tools supply DLLs with system-library names.
# In particular, Poppler's ICU exports versioned symbols incompatible with Qt.
env=os.environ.copy()
windows=pathlib.Path(env.get('SystemRoot','C:/Windows'))
env['PATH']=os.pathsep.join(map(str,(windows/'System32',windows,pathlib.Path(sys.executable).parent)))
subprocess.run(args,cwd=root,env=env,check=True)
dest=root/'dist/Shorekeeper'
for folder in ('assets','fonts','licenses','defaults'):
    if (root/folder).is_dir(): shutil.copytree(root/folder,dest/folder,dirs_exist_ok=True)
(dest/'audio').mkdir(exist_ok=True)
for name in ('README.md','MIGRATION.txt','CreateShortcut.vbs','THIRD_PARTY.txt','requirements.txt'): shutil.copy2(root/name,dest/name)
subprocess.run([sys.executable,str(root/'tools/verify_portable.py'),str(dest)],cwd=root,check=True)
print('Built '+str(dest))
