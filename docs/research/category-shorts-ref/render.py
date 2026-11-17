"""Render category shorts from an AI-authored project.json; no cloud AI key required."""
import argparse
import math
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from common import FONTS, ffmpeg, probe, read_json, resolve, write_json
from tts import make_hook

W, H, FPS = 608, 1080, 30

def numeric(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + ' must be a finite number.')
    return float(value)

def validate(project, base):
    if project.get('lang') not in ('ko', 'ja'):
        raise ValueError('lang must be ko or ja.')
    header = project.get('header')
    if not isinstance(header, list) or len(header) != 2 or not all(isinstance(x, str) and x.strip() for x in header):
        raise ValueError('header must contain two nonempty strings.')
    source = resolve(base, project['source'])
    meta = probe(source)
    if meta['width'] is None:
        raise ValueError('Source must contain video.')
    duration = numeric(project.get('duration', meta['duration']), 'duration')
    if not 0.1 <= duration <= min(180, meta['duration'] + 0.05):
        raise ValueError('duration is outside source bounds (maximum 180s).')
    shots = project.get('shots', [])
    if not shots:
        raise ValueError('shots must cover the full timeline.')
    previous = 0.0
    for shot in shots:
        if not isinstance(shot, list) or len(shot) != 4:
            raise ValueError('shot format: [start, end, zoom, y]')
        start, end, zoom, y = [numeric(v, 'shot value') for v in shot]
        if abs(start-previous) > 0.001 or end <= start or end > duration+0.001:
            raise ValueError('Shots must be continuous, ordered and within duration.')
        if not 1 <= zoom <= 3 or y > 280 or y + H*zoom < H-0.01:
            raise ValueError('Shot transform leaves a blank area or uses zoom outside 1..3.')
        previous = end
    if abs(previous-duration) > 0.001:
        raise ValueError('Shots must end at duration.')
    items = project.get('items', [])
    if not items:
        raise ValueError('At least one caption is required.')
    previous = 0.0
    for item in items:
        if not isinstance(item, list) or len(item) not in (4, 5):
            raise ValueError('caption format: [start, end, white|paren|emph, text, optional_y]')
        start, end = numeric(item[0], 'caption start'), numeric(item[1], 'caption end')
        if start < previous-0.001 or end <= start or end > duration+0.001:
            raise ValueError('Captions must be ordered, nonoverlapping and within duration.')
        if item[2] not in ('white', 'paren', 'emph') or not isinstance(item[3], str) or not item[3].strip():
            raise ValueError('Invalid caption kind/text.')
        if len(item) == 5 and not 310 <= numeric(item[4], 'caption y') <= 1030:
            raise ValueError('caption y must be between 310 and 1030.')
        previous = end
    if abs(items[0][0]) > 0.001:
        raise ValueError('First hook caption must start at zero.')
    if not project.get('hook_audio') and not str(project.get('hook', '')).strip():
        raise ValueError('hook text or hook_audio is required.')
    if any('\n' in text for text in [*header, *(i[3] for i in items)]):
        raise ValueError('Each header/caption is one line; remove embedded newlines.')
    return source, meta, duration

def text_center(draw, text, font_path, size, width, cy, fill, stroke=0, box=False):
    for current in range(size, 11, -1):
        font = ImageFont.truetype(str(font_path), current)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if bounds[2]-bounds[0] <= width:
            break
    else:
        raise ValueError('Caption/title is too long; shorten it: ' + text)
    tw, th = bounds[2]-bounds[0], bounds[3]-bounds[1]
    x, y = (W-tw)/2-bounds[0], cy-th/2-bounds[1]
    if box:
        draw.rounded_rectangle(((W-tw)/2-16, cy-th/2-10, (W+tw)/2+16, cy+th/2+10),
                               radius=12, fill=(0, 0, 0, 235))
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill='black')

def overlays(project):
    ko = project['lang'] == 'ko'
    title_font = FONTS / ('Pretendard-Black.otf' if ko else 'NotoSansCJKjp-Bold.otf')
    caption_font = FONTS / ('NotoSansCJKkr-Bold.otf' if ko else 'NotoSansCJKjp-Bold.otf')
    title = Image.new('RGBA', (W, H))
    draw = ImageDraw.Draw(title)
    draw.rectangle((0, 0, W, 279), fill='black')
    for index, text in enumerate(project['header']):
        text_center(draw, text, title_font, 66 if ko else 54, 570 if ko else 540,
                    ([155, 228] if ko else [164, 241])[index],
                    '#FFDC00' if ko and index else 'white')
    layers = []
    for item in project['items']:
        layer = Image.new('RGBA', (W, H))
        draw = ImageDraw.Draw(layer)
        kind, text = item[2:4]
        sizes = {'white': 28 if ko else 22, 'paren': 34 if ko else 28, 'emph': 36 if ko else 31}
        color = {'white': 'white', 'paren': '#FCCC2C', 'emph': '#04FC04'}[kind]
        stroke = {'white': 2, 'paren': 4, 'emph': 0}[kind]
        cy = item[4] if len(item) == 5 else (390 if kind == 'emph' else 700)
        text_center(draw, text, caption_font, sizes[kind], 520 if kind == 'emph' else 560,
                    cy, color, stroke, kind == 'emph')
        layers.append(layer)
    return title, layers

def read_exact(stream, size):
    chunks, remaining = [], size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b''.join(chunks)

def render(project_path, overwrite=False):
    project_path = Path(project_path).resolve()
    base = project_path.parent
    project = read_json(project_path)
    source, meta, duration = validate(project, base)
    output = resolve(base, project.get('output', 'result_' + project['lang'] + '.mp4'))
    if output == source or output == project_path:
        raise ValueError('Output must not overwrite input.')
    if output.exists() and not overwrite:
        raise ValueError('Output already exists. Choose a new output or use --overwrite.')
    output.parent.mkdir(parents=True, exist_ok=True)
    title, captions = overlays(project)
    frames = math.ceil(duration * FPS - 1e-6)
    encoded_duration = frames/FPS
    with tempfile.TemporaryDirectory(prefix='category-render-', dir=output.parent) as temp:
        temp = Path(temp)
        hook = temp / 'hook.wav'
        hook_duration = make_hook(project.get('hook', ''), hook, project['lang'],
                                  voice=project.get('voice'), rate=project.get('rate', '+50%'),
                                  audio=resolve(base, project['hook_audio']) if project.get('hook_audio') else None)
        hook_end = hook_duration + 0.08
        if hook_end > min(duration, project['items'][0][1]) + 0.02:
            raise ValueError(f'Hook needs {hook_end:.2f}s but first caption ends at '
                             f'{project["items"][0][1]:.2f}s. Shorten hook or extend first caption.')
        decoder_args = [ffmpeg(), '-hide_banner', '-loglevel', 'error', '-i', source,
                        '-an', '-vf', 'fps=30,scale=608:1080:force_original_aspect_ratio=increase,'
                        'crop=608:1080,setsar=1,eq=saturation=1.15:contrast=1.08,'
                        'tpad=stop_mode=clone:stop_duration=0.1',
                        '-frames:v', str(frames), '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        encoder_args = [ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', 'pipe:0']
        if meta['has_audio']:
            encoder_args += ['-i', source]
        else:
            encoder_args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        encoder_args += ['-i', hook, '-filter_complex',
                        f"[1:a]asetpts=PTS-STARTPTS,volume='if(lt(t,{hook_end}),0.2,1)':eval=frame[bg];"
                        '[2:a]asetpts=PTS-STARTPTS[voice];'
                        '[bg][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,'
                        f'loudnorm=I=-14:TP=-1:LRA=11,apad,atrim=duration={encoded_duration}[audio]',
                        '-map', '0:v:0', '-map', '[audio]', '-t', str(encoded_duration),
                        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
                        '-movflags', '+faststart', temp / 'render.mp4']
        decoder, encoder = None, None
        with (temp / 'decode.log').open('wb') as dl, (temp / 'encode.log').open('wb') as el:
            try:
                decoder = subprocess.Popen([str(x) for x in decoder_args], stdout=subprocess.PIPE, stderr=dl)
                encoder = subprocess.Popen([str(x) for x in encoder_args], stdin=subprocess.PIPE, stderr=el)
                shot_index = 0
                for n in range(frames):
                    raw = read_exact(decoder.stdout, W*H*3)
                    if len(raw) != W*H*3:
                        raise RuntimeError(f'Decoder stopped at frame {n}/{frames}.')
                    t = n/FPS
                    while shot_index+1 < len(project['shots']) and t >= project['shots'][shot_index][1]-1e-6:
                        shot_index += 1
                    _, _, zoom, y = project['shots'][shot_index]
                    frame = Image.frombytes('RGB', (W, H), raw)
                    frame = frame.resize((round(W*zoom), round(H*zoom)), Image.Resampling.LANCZOS)
                    frame = frame.filter(ImageFilter.UnsharpMask(radius=2, percent=100, threshold=3))
                    canvas = Image.new('RGB', (W, H), 'black')
                    canvas.paste(frame, ((W-frame.width)//2, round(y)))
                    canvas.paste(title, (0, 0), title)
                    for index, item in enumerate(project['items']):
                        if item[0] <= t < item[1]:
                            canvas.paste(captions[index], (0, 0), captions[index])
                            break
                    encoder.stdin.write(canvas.tobytes())
                    if n % (FPS*5) == 0:
                        print(f'RENDER {n/FPS:.1f}/{duration:.1f}s', flush=True)
                encoder.stdin.close()
                decoder.stdout.close()
                if decoder.wait(timeout=30) != 0 or encoder.wait(timeout=120) != 0:
                    raise RuntimeError('ffmpeg failed; inspect logs.')
            except Exception as exc:
                for process in (decoder, encoder):
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait()
                dl.flush()
                el.flush()
                logs = '\n'.join((temp / name).read_text(encoding='utf-8', errors='replace')[-2000:]
                                 for name in ('decode.log', 'encode.log'))
                raise RuntimeError(str(exc) + '\n' + logs) from exc
        result = probe(temp / 'render.mp4')
        if (result['width'], result['height']) != (W, H) or not result['has_audio']:
            raise RuntimeError('Output validation failed.')
        if abs(result['duration']-encoded_duration) > 0.15:
            raise RuntimeError('Output duration does not match project.')
        (temp / 'render.mp4').replace(output)
        hook.replace(output.with_suffix('.hook.wav'))
    write_json(output.with_suffix('.report.json'), {'output': output.name, **result,
               'fps': FPS, 'hook_duration': hook_duration, 'hook_end': hook_end,
               'tts': 'supplied recording' if project.get('hook_audio') else 'edge-tts',
               'fonts': ['Pretendard Black', 'Noto Sans CJK'],
               'review_required': 'Watch final video and inspect every cut before delivery.'})
    print('COMPLETE:', output)
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('project')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()
    render(args.project, args.overwrite)
