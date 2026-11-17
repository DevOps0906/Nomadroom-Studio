import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / 'assets/fonts'

def ffmpeg():
    candidate = os.environ.get('FFMPEG_BINARY') or shutil.which('ffmpeg')
    if candidate:
        return candidate
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def run(args, **kwargs):
    result = subprocess.run([str(x) for x in args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-5000:])
    return result

def probe(path):
    """Use ffmpeg itself so ffprobe is not a separate installation requirement."""
    result = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    text = result.stderr.decode('utf-8', 'replace')
    duration = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not duration:
        raise ValueError('Cannot read duration: ' + str(path) + '\n' + text[-1500:])
    seconds = int(duration[1])*3600 + int(duration[2])*60 + float(duration[3])
    video = re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b', text)
    return {'duration': seconds, 'has_audio': 'Audio:' in text,
            'width': int(video[1]) if video else None,
            'height': int(video[2]) if video else None}

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def resolve(base, value):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()
