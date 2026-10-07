"""Package an existing project GIF frame as a multi-resolution Windows icon."""
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]

def build():
    # The shipped idle expression; artwork credit remains in assets/CREDITS.txt.
    with Image.open(ROOT/'assets/originals/p2-31.gif') as source:
        frame=source.convert('RGBA')
    frame.thumbnail((256,256),Image.Resampling.LANCZOS)
    canvas=Image.new('RGBA',(256,256))
    canvas.alpha_composite(frame,((256-frame.width)//2,(256-frame.height)//2))
    canvas.save(ROOT/'assets/shorekeeper.ico',format='ICO',bitmap_format='bmp',
                sizes=[(n,n) for n in (16,24,32,48,64,128,256)])

if __name__=='__main__': build()
