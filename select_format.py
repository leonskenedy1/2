import subprocess, sys, json

YTDLP_BASE = 'yt-dlp --cookies cookies.txt --js-runtimes deno --remote-components ejs:npm --no-progress'
selected = []

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
        print(f'Processing YouTube URL: {url}')
        opts = parts[1:]
        if not opts:
            opts = ['v', 'max']
        groups = []
        i = 0
        while i < len(opts):
            t = opts[i].lower()
            if t not in ('v','a'):
                i += 1
                continue
            i += 1
            if i >= len(opts):
                groups.append((t, 'max', ''))
                continue
            val1 = opts[i]
            i += 1
            if t == 'v':
                if val1 == '2k': val1 = '1440'
                elif val1 == '4k': val1 = '2160'
            val2 = ''
            if t == 'v' and val1.isdigit() and i < len(opts) and opts[i].isdigit():
                val2 = opts[i]
                i += 1
            groups.append((t, val1, val2))
        seen = set()
        unique_groups = []
        for g in groups:
            if g not in seen:
                seen.add(g)
                unique_groups.append(g)
        tempfile = f'temp_{video_id}.json'
        try:
            subprocess.run(f'{YTDLP_BASE} -j "{url}" > {tempfile}', shell=True, check=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            print(f'ERROR: yt-dlp failed for {url}: {e.stderr.decode()}')
            continue
        with open(tempfile) as jf:
            data = json.load(jf)
        formats = data.get('formats', [])
        combined = [f for f in formats if f.get('vcodec') != 'none' and f.get('acodec') != 'none']
        audio_only = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']

        formats_to_download = {}
        for t, val1, val2 in unique_groups:
            if t == 'v':
                if val1 == 'all':
                    for f in combined:
                        formats_to_download[f['format_id']] = 'video'
                    continue
                if val1 == 'max':
                    fid = max(combined, key=lambda x: (x.get('height',0), x.get('fps',0)))['format_id']
                elif val1 == 'min':
                    fid = min(combined, key=lambda x: (x.get('height',0), x.get('fps',0)))['format_id']
                else:
                    target_height = int(val1)
                    target_fps = int(val2) if val2 else 0
                    same_height = [f for f in combined if f.get('height') == target_height]
                    if not same_height:
                        closest_height = min(combined, key=lambda x: abs(x.get('height',0)-target_height))['height']
                        same_height = [f for f in combined if f.get('height') == closest_height]
                    if target_fps > 0:
                        exact = [f for f in same_height if f.get('fps') == target_fps]
                        if exact:
                            fid = exact[0]['format_id']
                        else:
                            fid = max(same_height, key=lambda x: x.get('fps',0))['format_id']
                    else:
                        fid = max(same_height, key=lambda x: x.get('fps',0))['format_id']
                formats_to_download[fid] = 'video'
            else:
                if val1 == 'all':
                    for f in audio_only:
                        formats_to_download[f['format_id']] = 'audio'
                    continue
                if val1 == 'max':
                    fid = max(audio_only, key=lambda x: x.get('abr') or x.get('tbr') or 0)['format_id']
                elif val1 == 'min':
                    fid = min(audio_only, key=lambda x: x.get('abr') or x.get('tbr') or 0)['format_id']
                else:
                    target_br = int(val1)
                    best = min(audio_only, key=lambda x: abs((x.get('abr') or x.get('tbr') or 0) - target_br))
                    fid = best['format_id']
                formats_to_download[fid] = 'audio'

        title = data.get('title', video_id)

        entry = {
            'url': url,
            'video_id': video_id,
            'title': title,
            'formats': formats_to_download
        }
        selected.append(entry)

with open('selected_formats.json', 'w') as outfile:
    json.dump(selected, outfile)
