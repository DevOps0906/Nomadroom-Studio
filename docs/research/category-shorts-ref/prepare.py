"""Download/normalize source, find scene candidates and export timestamped sheets."""
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, ImageDraw, ImageFont
from common import FONTS, ffmpeg, probe, run, write_json

def download(url, work):
    import yt_dlp
    # Download elementary streams separately, then merge with our known ffmpeg.
    # This also works when only imageio-ffmpeg (without ffprobe) is installed.
    options = {'noplaylist': True, 'quiet': True, 'retries': 2,
               'socket_timeout': 30, 'restrictfilenames': True,
               'outtmpl': str(work / 'download_video.%(ext)s'),
               'format': 'bv*[height<=1920]/b[height<=1920]/b'}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        video = Path(downloader.prepare_filename(info))
    audio = None
    audio_available = any(f.get('acodec') not in (None, 'none') for f in info.get('formats', []))
    if not probe(video)['has_audio'] and audio_available:
        audio_options = {**options, 'format': 'ba/b',
                         'outtmpl': str(work / 'download_audio.%(ext)s')}
        try:
            with yt_dlp.YoutubeDL(audio_options) as downloader:
                audio_info = downloader.extract_info(url, download=True)
                audio = Path(downloader.prepare_filename(audio_info))
        except yt_dlp.utils.DownloadError as exc:
            raise RuntimeError('Video downloaded but its audio failed. Retry or supply the original video file.') from exc
    return video, audio, {'url': url, 'title': info.get('title'),
                          'uploader': info.get('uploader'), 'id': info.get('id')}

def prepare(source, work, start=0.0, duration=None):
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    if (work / 'source.mp4').exists():
        raise ValueError('Work folder already contains source.mp4; choose a new work folder.')
    is_url = source.startswith(('https://', 'http://'))
    if is_url:
        video, audio, origin = download(source, work)
    else:
        video, audio, origin = Path(source).resolve(), None, {'file': Path(source).name}
    meta = probe(video)
    if start < 0 or start >= meta['duration']:
        raise ValueError('start must be inside the source duration.')
    duration = duration if duration is not None else meta['duration'] - start
    if not 0.1 <= duration <= meta['duration'] - start + 0.05:
        raise ValueError('Invalid duration for selected source.')
    if duration > 180:
        raise ValueError('Source is longer than 180 seconds. Select a short segment with --start and --duration.')
    args = [ffmpeg(), '-y', '-ss', str(start), '-i', video]
    if audio:
        args += ['-ss', str(start), '-i', audio]
    args += ['-t', str(duration), '-map', '0:v:0', '-map', '1:a:0?' if audio else '0:a:0?',
             '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1', '-r', '30',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-movflags', '+faststart', work / 'source.mp4']
    run(args)
    source_file = work / 'source.mp4'
    actual = probe(source_file)
    scenes = run([ffmpeg(), '-hide_banner', '-i', source_file, '-vf',
                  "scale=270:-2,select='gt(scene,0.08)',showinfo", '-an', '-f', 'null', '-'])
    candidates = sorted(set(float(x) for x in re.findall(
        r'pts_time:([\d.]+)', scenes.stderr.decode('utf-8', 'replace'))))
    write_json(work / 'analysis.json', {**actual, 'origin': origin, 'source_start': start,
                                      'scene_candidates': candidates,
                                      'note': 'Candidates only; visually verify. Sheet frames every 0.5 seconds.'})
    sheet_dir = work / 'sheets'
    sheet_dir.mkdir(exist_ok=True)
    label_font = ImageFont.truetype(str(FONTS / 'Pretendard-Black.otf'), 15)
    with tempfile.TemporaryDirectory(prefix='category-frames-') as temp:
        run([ffmpeg(), '-y', '-i', source_file, '-vf',
             'fps=2,scale=180:320:force_original_aspect_ratio=decrease,pad=180:320:(ow-iw)/2:(oh-ih)/2',
             Path(temp) / '%05d.jpg'])
        frames = sorted(Path(temp).glob('*.jpg'))
        for page in range(math.ceil(len(frames)/24)):
            sheet = Image.new('RGB', (6*180, 4*346), '#191919')
            draw = ImageDraw.Draw(sheet)
            for local, frame in enumerate(frames[page*24:(page+1)*24]):
                x, y = (local % 6)*180, (local // 6)*346
                with Image.open(frame) as im:
                    sheet.paste(im, (x, y+26))
                draw.text((x+6, y+4), f'{(page*24+local)*0.5:.1f}s', font=label_font, fill='white')
            sheet.save(sheet_dir / f'sheet_{page+1:03d}.jpg', quality=90)
    print('PREPARED:', work)
    print('AI: inspect analysis.json, source.mp4 and every sheets/*.jpg; then author project.json.')
    return work
