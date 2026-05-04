import subprocess, sys, json, re

YTDLP_BASE = 'yt-dlp --cookies cookies.txt --js-runtimes deno --remote-components ejs:npm --no-progress'

def parse_duration(number, unit):
    val = float(number)
    if unit == 'h':
        return val * 3600.0
    elif unit == 'm':
        return val * 60.0
    else:
        return val

def try_parse_delay(tokens, i):
    if i + 1 >= len(tokens):
        return None
    if re.match(r'^\d+(\.\d+)?$', tokens[i]) and tokens[i+1] in ('h','m','s'):
        return (parse_duration(tokens[i], tokens[i+1]), i + 2)
    return None

def skip_delays(tokens, i):
    while i < len(tokens):
        res = try_parse_delay(tokens, i)
        if res is None:
            break
        i = res[1]
    return i

output = []

with open('tasks.txt') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        url = parts[0]
        if not ('youtube.com/watch?v=' in url or 'youtu.be/' in url):
            continue
        video_id = url.split('v=')[-1].split('/')[0] if 'v=' in url else url.split('youtu.be/')[-1].split('/')[0]
        opts = parts[1:]
        if not opts:
            opts = ['v', 'max']

        tempfile = f'temp_{video_id}.json'
        try:
            subprocess.run(f'{YTDLP_BASE} -j "{url}" > {tempfile}', shell=True, check=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f'ERROR: yt-dlp failed for {url}: {e.stderr.decode()}')
            continue
        with open(tempfile) as jf:
            data = json.load(jf)
        title = data.get('title', video_id)
        formats = data.get('formats', [])
        combined = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
        audio_only = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']

        groups = []
        i = 0
        first_group = True

        while i < len(opts):
            token = opts[i]

            if token in ('v', 'a'):
                typ = token
                i += 1
                i = skip_delays(opts, i)
                if i >= len(opts):
                    val1 = 'max'
                    val2 = ''
                else:
                    val1 = opts[i]
                    i += 1
                    if typ == 'v':
                        if val1 == '2k': val1 = '1440'
                        elif val1 == '4k': val1 = '2160'
                    val2 = ''
                    if typ == 'v' and val1.isdigit():
                        i = skip_delays(opts, i)
                        if i < len(opts) and opts[i].isdigit():
                            val2 = opts[i]
                            i += 1
                internal_delay = 0.0
                if val1 == 'all':
                    if i < len(opts) and opts[i].startswith('('):
                        expr = ''
                        while i < len(opts):
                            expr += opts[i] + ' '
                            if ')' in opts[i]:
                                break
                            i += 1
                        i += 1
                        expr_clean = expr.replace('(', '').replace(')', '').strip()
                        delay_parts = expr_clean.split()
                        j = 0
                        while j < len(delay_parts):
                            if j+1 < len(delay_parts) and re.match(r'^\d+(\.\d+)?$', delay_parts[j]) and delay_parts[j+1] in ('h','m','s'):
                                internal_delay += parse_duration(delay_parts[j], delay_parts[j+1])
                                j += 2
                            else:
                                j += 1
                delay_after = 0.0
                while True:
                    res = try_parse_delay(opts, i)
                    if res is None:
                        break
                    delay_after += res[0]
                    i = res[1]
                groups.append({
                    'type': typ,
                    'val1': val1,
                    'val2': val2,
                    'internal_delay': internal_delay,
                    'delay_after': delay_after
                })
                first_group = False

            elif token == 'all':
                i += 1
                internal_delay = 0.0
                if i < len(opts) and opts[i].startswith('('):
                    expr = ''
                    while i < len(opts):
                        expr += opts[i] + ' '
                        if ')' in opts[i]:
                            break
                        i += 1
                    i += 1
                    expr_clean = expr.replace('(', '').replace(')', '').strip()
                    delay_parts = expr_clean.split()
                    j = 0
                    while j < len(delay_parts):
                        if j+1 < len(delay_parts) and re.match(r'^\d+(\.\d+)?$', delay_parts[j]) and delay_parts[j+1] in ('h','m','s'):
                            internal_delay += parse_duration(delay_parts[j], delay_parts[j+1])
                            j += 2
                        else:
                            j += 1
                delay_after = 0.0
                while True:
                    res = try_parse_delay(opts, i)
                    if res is None:
                        break
                    delay_after += res[0]
                    i = res[1]
                groups.append({'type':'v', 'val1':'all', 'val2':'', 'internal_delay':internal_delay, 'delay_after':0})
                groups.append({'type':'a', 'val1':'all', 'val2':'', 'internal_delay':internal_delay, 'delay_after':delay_after})
                first_group = False

            else:
                i += 1

        downloads = []
        for grp in groups:
            typ = grp['type']
            val1 = grp['val1']
            val2 = grp.get('val2', '')
            internal = grp['internal_delay']
            da = grp['delay_after']
            if val1 == 'all':
                if typ == 'v':
                    fmts = sorted(combined, key=lambda x: (x.get('height', 0), x.get('fps', 0)), reverse=True)
                else:
                    fmts = sorted(audio_only, key=lambda x: x.get('abr', 0) or x.get('tbr', 0), reverse=True)
                if not fmts:
                    print(f'WARNING: No formats for {typ} all in {url}')
                    continue
                count = len(fmts)
                for idx, f in enumerate(fmts):
                    fid = f['format_id']
                    if idx == count - 1:
                        delay = da
                    else:
                        delay = internal
                    downloads.append({'format_id': fid, 'type': typ, 'delay_after': delay})
            else:
                if val1 == 'max':
                    if typ == 'v':
                        fid = max(combined, key=lambda x: (x.get('height', 0), x.get('fps', 0)))['format_id']
                    else:
                        fid = max(audio_only, key=lambda x: (x.get('abr', 0) or x.get('tbr', 0)))['format_id']
                elif val1 == 'min':
                    if typ == 'v':
                        fid = min(combined, key=lambda x: (x.get('height', 0), x.get('fps', 0)))['format_id']
                    else:
                        fid = min(audio_only, key=lambda x: (x.get('abr', 0) or x.get('tbr', 0)))['format_id']
                else:
                    if typ == 'v':
                        target_h = int(val1)
                        target_fps = int(val2) if val2 else 0
                        same_h = [f for f in combined if f.get('height') == target_h]
                        if not same_h:
                            closest = min(combined, key=lambda x: abs(x.get('height', 0) - target_h))
                            same_h = [f for f in combined if f.get('height') == closest['height']]
                        if target_fps > 0:
                            exact = [f for f in same_h if f.get('fps') == target_fps]
                            if exact:
                                fid = exact[0]['format_id']
                            else:
                                fid = max(same_h, key=lambda x: x.get('fps', 0))['format_id']
                        else:
                            fid = max(same_h, key=lambda x: x.get('fps', 0))['format_id']
                    else:
                        target_br = int(val1)
                        best = min(audio_only, key=lambda x: abs((x.get('abr', 0) or x.get('tbr', 0)) - target_br))
                        fid = best['format_id']
                downloads.append({'format_id': fid, 'type': typ, 'delay_after': da})

        entry = {
            'url': url,
            'video_id': video_id,
            'title': title,
            'downloads': downloads
        }
        output.append(entry)

with open('selected_formats.json', 'w') as f:
    json.dump(output, f, indent=2)

queue = []
for entry in output:
    for dl in entry['downloads']:
        queue.append({
            'url': entry['url'],
            'title': entry['title'],
            'video_id': entry['video_id'],
            'format_id': dl['format_id'],
            'type': dl['type'],
            'delay_after': dl['delay_after']
        })
if queue:
    queue[-1]['delay_after'] = 0.0

with open('download_queue.json', 'w') as f:
    json.dump(queue, f, indent=2)
