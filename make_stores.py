#!/usr/bin/env python3
"""重抓門市座標，輸出 stores.js 給 index.html 用。用法：python3 make_stores.py

7-11、全聯：All The Places（整理自官方門市查詢，CC0）
萊爾富、OK：官方沒給座標，改用 OpenStreetMap（有漏店）
全家不用：index.html 直接從全家的即時 API 拿門市和庫存
"""
import json, re, subprocess, time

UA = 'tw-food-map/1.0 (personal project)'  # Overpass 會擋預設的 Python-urllib / curl 名稱


def get(url, data=None):
    # 用 curl：macOS 內建 Python 3.9 的 LibreSSL 太舊，連 overpass-api.de 會 SSL 握手失敗
    cmd = ['curl', '-sSfL', '-m', '200', '-A', UA, url] + (['--data-urlencode', 'data@-'] if data else [])
    return json.loads(subprocess.run(cmd, input=data, capture_output=True, text=True, check=True).stdout)


def atp(run, spider):
    feats = get(f'https://alltheplaces-data.openaddresses.io/runs/{run}/output/{spider}.geojson')['features']
    return [[f['properties'].get('branch') or f['properties'].get('name', ''),
             round(f['geometry']['coordinates'][1], 5), round(f['geometry']['coordinates'][0], 5)]
            for f in feats if f.get('geometry')]


def osm():
    q = '''[out:json][timeout:180];area["ISO3166-1"="TW"][admin_level=2]->.tw;
(nwr["shop"="convenience"]["brand"~"萊爾富|hi-life|ok ?超商|ok ?mart",i](area.tw);
 nwr["shop"="convenience"]["name"~"萊爾富|hi-life|ok ?超商|ok ?mart",i](area.tw););out center tags;'''
    for i in range(5):  # 公用 Overpass 常滿載：退避重試
        try:
            return get('https://overpass-api.de/api/interpreter', q)['elements']
        except subprocess.CalledProcessError as e:
            print(f'Overpass 失敗（{e.stderr.strip()}），{20 * 2 ** i} 秒後重試', flush=True)
            time.sleep(20 * 2 ** i)
    print('Overpass 一直失敗：這次先不含萊爾富、OK，晚點再跑一次')
    return []


def save(stores):
    with open('stores.js', 'w', encoding='utf-8') as f:
        f.write(f'// 由 make_stores.py 產生（All The Places {run} + OpenStreetMap），格式：品牌 → [名稱, 緯度, 經度]\n')
        f.write('const STORES = ' + json.dumps(stores, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('已寫入 stores.js', {b: len(v) for b, v in stores.items()}, flush=True)


run = get('https://data.alltheplaces.xyz/runs/latest.json')['run_id']
stores = {'7-11': atp(run, 'seven_eleven_tw'), '全聯': atp(run, 'pxmart_tw') + atp(run, 'mega_pxmart_tw'), '萊爾富': [], 'OK': []}
save(stores)  # 先存一份，Overpass 再慢也不會白跑
for e in osm():
    t = e.get('tags', {})
    b = '萊爾富' if re.search('萊爾富|hi-life', t.get('brand', '') + t.get('name', ''), re.I) else 'OK'
    c = e.get('center', e)
    name = t.get('branch') or re.sub('萊爾富|hi-life|ok ?超商|ok ?mart', '', t.get('name', ''), flags=re.I).strip()
    stores[b].append([name, round(c['lat'], 5), round(c['lon'], 5)])
if stores['萊爾富'] or stores['OK']:
    save(stores)
