"""Normalize local audio to PCM16; playback does not use system media codecs."""
import hashlib,pathlib,wave,subprocess,sys

def playable_path(source,cache):
    source=pathlib.Path(source)
    import soundfile
    if source.stat().st_size>100_000_000: raise ValueError('音频过大，请先裁剪为提醒短句。')
    if source.suffix.lower()=='.wav':
        try:
            with wave.open(str(source),'rb') as audio:
                if audio.getsampwidth()==2 and audio.getnchannels() in (1,2) and audio.getnframes()/audio.getframerate()<=600: return source
        except (wave.Error,EOFError): pass
    with source.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    cache=pathlib.Path(cache); cache.mkdir(parents=True,exist_ok=True); target=cache/(digest+'.wav')
    if target.exists(): return target
    # Different rapid auditions can decode concurrently; give each a distinct temp.
    import uuid
    temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    try:
        if source.suffix.lower() in ('.m4a','.aac'):
            import imageio_ffmpeg
            result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-i',str(source),'-vn','-t','601','-ac','2','-ar','48000','-c:a','pcm_s16le','-f','wav',str(temporary)],capture_output=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            if result.returncode: raise ValueError('无法解码音频：'+result.stderr.decode('utf8',errors='replace')[-300:])
            with wave.open(str(temporary),'rb') as audio:
                if audio.getnframes()/audio.getframerate()>600: raise ValueError('音频超过 10 分钟，请先裁剪。')
            temporary.replace(target); return target
        with soundfile.SoundFile(str(source)) as audio, wave.open(str(temporary),'wb') as out:
            if audio.channels not in (1,2) or audio.frames/audio.samplerate>600: raise ValueError('请使用不超过 10 分钟的单声道或双声道提醒音频。')
            out.setnchannels(audio.channels); out.setsampwidth(2); out.setframerate(audio.samplerate)
            while audio.tell()<audio.frames: out.writeframes(audio.buffer_read(65536,dtype='int16'))
        temporary.replace(target)
    finally:
        if temporary.exists(): temporary.unlink()
    return target

def verify_decoder(directory):
    import soundfile
    directory=pathlib.Path(directory); source=directory/'silent.ogg'
    with soundfile.SoundFile(str(source),'w',samplerate=16000,channels=1,format='OGG',subtype='VORBIS') as audio:
        audio.buffer_write(b'\0\0'*4000,dtype='int16')
    decoded=playable_path(source,directory/'cache')
    with wave.open(str(decoded),'rb') as audio:
        if audio.getnframes()!=4000 or audio.getframerate()!=16000: return False
    import imageio_ffmpeg
    for extension in ('m4a','aac','mp3','flac'):
        encoded=directory/('format-check.'+extension)
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-i',str(decoded),str(encoded)],capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        if result.returncode: return False
        ready=playable_path(encoded,directory/'cache')
        with wave.open(str(ready),'rb') as audio:
            if audio.getsampwidth()!=2 or not .15<audio.getnframes()/audio.getframerate()<.5: return False
    return True
