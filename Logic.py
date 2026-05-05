import subprocess, sys, json, re, os, glob, time, shutil, argparse

YTDLP_BASE = 'yt-dlp --cookies cookies.txt --js-runtimes deno --remote-components ejs:npm'
PROGRESS_TEMPLATE = "%(progress._percent_str)s of %(progress._total_bytes_str)s at %(progress._speed_str)s ETA %(progress._eta_str)s (frag %(progress.fragment_index)s/%(progress.fragment_count)s)"

def parse_duration(val, unit):
    v = float(val)
    if unit == 'h': return v * 3600.0
    if unit == 'm': return v * 60.0
    return v

def try_parse_delay(tokens, i):
    if i + 1 >= len(tokens):
        return None
    if re.match(r'^\d+(\.\d+)?$', tokens[i]) and tokens[i+1] in ('h','m','s'):
        return (parse_duration(tokens[i], tokens[i+1]), i + 2)
    return None

def select_formats(tasks_file):
    output = []
    with open(tasks_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            url = parts[0]
            if not ('youtube.com/watch?v=' in url or 'youtu.be/' in url):
                continue
            video_id = url.split('v=')[-1].split('/')[0] if 'v=' in url else url.split('youtu.be/')[-1].split('/')[0]
            opts = parts[1:] if len(parts) > 1 else ['v', 'max']

            tempfile = f'temp_{video_id}.json'
            try:
                subprocess.run(f'{YTDLP_BASE} --no-progress -j "{url}" > {tempfile}', shell=True, check=True, stderr=subprocess.PIPE)
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
                            if i < len(opts) and opts[i].isdigit():
                                next_is_fps = True
                                if i+1 < len(opts) and opts[i+1] in ('h','m','s'):
                                    next_is_fps = False
                                if next_is_fps:
                                    val2 = opts[i]
                                    i += 1
                                    while i < len(opts):
                                        res = try_parse_delay(opts, i)
                                        if res is None:
                                            break
                                        i = res[1]
                    internal_delay = 0.0
                    if val1 == 'all' and i < len(opts) and opts[i].startswith('('):
                        expr = ''
                        while i < len(opts):
                            expr += opts[i] + ' '
                            if ')' in opts[i]:
                                break
                            i += 1
                        i += 1
                        expr_clean = expr.replace('(','').replace(')','').strip()
                        parts_d = expr_clean.split()
                        j = 0
                        while j < len(parts_d):
                            if j+1 < len(parts_d) and re.match(r'^\d+(\.\d+)?$', parts_d[j]) and parts_d[j+1] in ('h','m','s'):
                                internal_delay += parse_duration(parts_d[j], parts_d[j+1])
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
                        expr_clean = expr.replace('(','').replace(')','').strip()
                        parts_d = expr_clean.split()
                        j = 0
                        while j < len(parts_d):
                            if j+1 < len(parts_d) and re.match(r'^\d+(\.\d+)?$', parts_d[j]) and parts_d[j+1] in ('h','m','s'):
                                internal_delay += parse_duration(parts_d[j], parts_d[j+1])
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
                    groups.append({'type': 'v', 'val1': 'all', 'val2': '', 'internal_delay': internal_delay, 'delay_after': 0})
                    groups.append({'type': 'a', 'val1': 'all', 'val2': '', 'internal_delay': internal_delay, 'delay_after': delay_after})
                    first_group = False
                else:
                    i += 1

            downloads = []
            for grp in groups:
                typ, val1, val2 = grp['type'], grp['val1'], grp.get('val2','')
                internal, da = grp['internal_delay'], grp['delay_after']
                if val1 == 'all':
                    fmts = sorted(
                        (combined if typ == 'v' else audio_only),
                        key=lambda x: (x.get('height', 0), x.get('fps', 0)) if typ == 'v' else (x.get('abr') or x.get('tbr') or 0),
                        reverse=True
                    )
                    if not fmts:
                        print(f'WARNING: No formats for {typ} all in {url}')
                        continue
                    for idx, f in enumerate(fmts):
                        fid = f['format_id']
                        delay = da if idx == len(fmts) - 1 else internal
                        downloads.append({'format_id': fid, 'type': typ, 'delay_after': delay})
                else:
                    if val1 == 'max':
                        fid = (max if typ == 'v' else max)(
                            combined if typ == 'v' else audio_only,
                            key=lambda x: (x.get('height', 0), x.get('fps', 0)) if typ == 'v' else (x.get('abr') or x.get('tbr') or 0)
                        )['format_id']
                    elif val1 == 'min':
                        fid = (min if typ == 'v' else min)(
                            combined if typ == 'v' else audio_only,
                            key=lambda x: (x.get('height', 0), x.get('fps', 0)) if typ == 'v' else (x.get('abr') or x.get('tbr') or 0)
                        )['format_id']
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
                                fid = exact[0]['format_id'] if exact else max(same_h, key=lambda x: x.get('fps', 0))['format_id']
                            else:
                                fid = max(same_h, key=lambda x: x.get('fps', 0))['format_id']
                        else:
                            target_br = int(val1)
                            best = min(audio_only, key=lambda x: abs((x.get('abr') or x.get('tbr') or 0) - target_br))
                            fid = best['format_id']
                    downloads.append({'format_id': fid, 'type': typ, 'delay_after': da})

            entry = {'url': url, 'video_id': video_id, 'title': title, 'downloads': downloads}
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

def download_and_manifest():
    if not os.path.exists('download_queue.json'):
        print("No download queue found.")
        return
    with open('download_queue.json') as f:
        queue = json.load(f)
    total = len(queue)
    manifest_entries = {}
    os.makedirs('temp_downloads', exist_ok=True)

    for idx, item in enumerate(queue):
        url = item['url']
        title = item['title']
        video_id = item['video_id']
        fid = item['format_id']
        ftype = item['type']
        delay_after = item['delay_after']

        out_template = f"temp_downloads/{title}_{fid}.%(ext)s"
        print(f"[{idx+1}/{total}] Downloading {ftype} format {fid} for {title}", flush=True)

        cmd = f'stdbuf -oL {YTDLP_BASE} -f {fid} -o "{out_template}" --progress-delta 1 --progress-template "{PROGRESS_TEMPLATE}" "{url}"'
        subprocess.run(cmd, shell=True, check=True)

        get_filename_cmd = f'{YTDLP_BASE} -f {fid} --get-filename -o "{out_template}" "{url}"'
        predicted = subprocess.check_output(get_filename_cmd, shell=True).decode().strip()

        if os.path.exists(predicted):
            dl_file = os.path.basename(predicted)
        else:
            search_pattern = os.path.join('temp_downloads', f"{title}_{fid}.*")
            matches = glob.glob(search_pattern)
            if matches:
                dl_file = os.path.basename(matches[0])
            else:
                print(f"ERROR: Could not locate downloaded file for {title}_{fid}", flush=True)
                continue

        key = f"{url}|{title}"
        if key not in manifest_entries:
            manifest_entries[key] = {
                'url': url,
                'is_youtube': True,
                'video_id': video_id,
                'title': title,
                'files': []
            }
        manifest_entries[key]['files'].append({'filename': dl_file, 'type': ftype})

        if idx < total - 1 and delay_after > 0:
            print(f"⏳ Pausing for {delay_after} seconds...", flush=True)
            time.sleep(delay_after)

    manifest = list(manifest_entries.values())
    with open('download_manifest.json', 'w') as f:
        json.dump(manifest, f, indent=2)
    print("Manifest saved successfully.", flush=True)

def remux_videos():
    if not os.path.exists('download_manifest.json'):
        print("No manifest, skipping remux.", flush=True)
        return
    with open('download_manifest.json') as f:
        manifest = json.load(f)
    for entry in manifest:
        if not entry.get('is_youtube'):
            continue
        for file_info in entry.get('files', []):
            if file_info.get('type') != 'video':
                continue
            fname = file_info['filename']
            os.chdir('temp_downloads')
            print(f"Remuxing {fname}...", flush=True)
            out = f"fixed_{fname}"
            subprocess.run(f'ffmpeg -hide_banner -loglevel warning -stats -i "{fname}" -c copy "{out}" -y', shell=True, check=True)
            os.replace(out, fname)
            os.chdir('..')

def create_zips():
    if not os.path.exists('download_manifest.json'):
        print("No manifest, skipping ZIP.", flush=True)
        return
    with open('download_manifest.json') as f:
        manifest = json.load(f)
    os.makedirs('final_downloads', exist_ok=True)
    for entry in manifest:
        if not entry.get('is_youtube'):
            fname = entry['files'][0]['filename']
            os.chdir('temp_downloads')
            subprocess.run(f'zip -s 99m -r "../final_downloads/{fname}.zip" "{fname}"', shell=True, check=True)
            os.chdir('..')
        else:
            title = entry['title']
            video_files = [f['filename'] for f in entry['files'] if f['type'] == 'video']
            audio_files = [f['filename'] for f in entry['files'] if f['type'] == 'audio']
            if video_files:
                dest = f"temp_downloads/{title}_videos"
                os.makedirs(dest, exist_ok=True)
                for vf in video_files:
                    shutil.copy(f"temp_downloads/{vf}", dest)
                subprocess.run(f'zip -s 99m -r "final_downloads/{title}_videos.zip" "{dest}"', shell=True, check=True)
                shutil.rmtree(dest)
            if audio_files:
                dest = f"temp_downloads/{title}_audios"
                os.makedirs(dest, exist_ok=True)
                for af in audio_files:
                    shutil.copy(f"temp_downloads/{af}", dest)
                subprocess.run(f'zip -s 99m -r "final_downloads/{title}_audios.zip" "{dest}"', shell=True, check=True)
                shutil.rmtree(dest)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--select', action='store_true')
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--remux', action='store_true')
    parser.add_argument('--zip', action='store_true')
    args = parser.parse_args()

    if args.select:
        select_formats('tasks.txt')
    elif args.download:
        download_and_manifest()
    elif args.remux:
        remux_videos()
    elif args.zip:
        create_zips()
    else:
        print("Use one of: --select, --download, --remux, --zip")
