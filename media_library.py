"""Discover user-supplied character images in the portable asset directory."""
import hashlib,json,pathlib,shutil
from PIL import Image,UnidentifiedImageError

IMAGE_EXTS={'.gif','.webp','.png','.jpg','.jpeg'}
IMAGE_FILTER='角色图片 (*.gif *.webp *.png *.jpg *.jpeg)'
IMAGE_HELP='支持 GIF、动画 WebP、PNG、JPG/JPEG、静态 WebP。每个文件最多 20 MB，尺寸不超过 2048 × 2048，最多 600 帧。'

def inspect_image(path,root):
    path=pathlib.Path(path); root=pathlib.Path(root).resolve()
    if path.suffix.lower() not in IMAGE_EXTS: raise ValueError('不支持的图片类型')
    if not path.resolve().is_relative_to(root): raise ValueError('素材必须位于桌宠目录内')
    if path.stat().st_size>20*1024*1024: raise ValueError('文件超过 20 MB')
    try:
        with Image.open(path) as im:
            count=getattr(im,'n_frames',1)
            if im.width>2048 or im.height>2048 or count>600 or im.width*im.height*count>70_000_000: raise ValueError('图片尺寸或动画帧数过大')
            durations=[]
            for i in range(count):
                im.seek(i); im.load(); durations.append(max(20,int(im.info.get('duration',100))))
            relative=path.relative_to(root).as_posix()
            return dict(id='user-'+hashlib.sha256(relative.casefold().encode()).hexdigest()[:16],name=path.name,path=relative,width=im.width,height=im.height,frames=count,duration_ms=sum(durations),durations_ms=durations,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),origin='custom')
    except (UnidentifiedImageError,OSError,EOFError) as error: raise ValueError('图片无法读取或已损坏') from error

def load_catalog(root):
    root=pathlib.Path(root).resolve(); builtin=json.loads((root/'assets/catalog.json').read_text('utf8'))
    folder=root/'assets/custom'; folder.mkdir(parents=True,exist_ok=True); records=[]; warnings=[]
    for path in sorted(folder.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS: continue
        try: records.append(inspect_image(path,root))
        except (OSError,ValueError) as error: warnings.append(path.name+'：'+str(error))
    return builtin+records,warnings

def import_images(paths,root):
    root=pathlib.Path(root).resolve(); folder=root/'assets/custom'; folder.mkdir(parents=True,exist_ok=True)
    imported=[]; warnings=[]
    for value in paths:
        source=pathlib.Path(value).resolve()
        try:
            # Validate before copying; root is the selected source's own directory.
            inspect_image(source,source.parent)
            target=folder/source.name
            if target.exists() and target.resolve()!=source:
                if target.read_bytes()==source.read_bytes(): imported.append(target); continue
                target=folder/(source.stem+'-'+hashlib.sha256(source.read_bytes()).hexdigest()[:10]+source.suffix.lower())
            if target.resolve()!=source: shutil.copy2(source,target)
            imported.append(target)
        except (OSError,ValueError) as error: warnings.append(source.name+'：'+str(error))
    return imported,warnings
