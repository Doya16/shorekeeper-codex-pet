"""Keep startup diagnostics available even when the packaged UI cannot load."""
import pathlib,sys,traceback

def run():
    try:
        from pet import main
        return main()
    except Exception:
        root=pathlib.Path(sys.executable).parent if getattr(sys,'frozen',False) else pathlib.Path(__file__).parent
        (root/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        if '--verify-package' not in sys.argv:
            raise
        return 1

if __name__=='__main__':
    sys.exit(run())
