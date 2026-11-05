#!/usr/bin/env python3
"""重抓萊爾富門市並補上官方店名和電話，寫回 stores.js（格式：[名稱, 緯度, 經度, 電話?]）。用法：python3 name_hilife.py

1. 萊爾富官網門市查詢的公開清單：每家店的官方店名＋地址（沒有座標）
2. OpenStreetMap 的萊爾富點位：有座標，但約四分之一沒有店名
3. 配對（只收唯一、明確的）：完整地址 > 同區同路只有一家 > 店名相同 >
   沒地址的點反查所在「區＋路」再找同區同路唯一的官方店 > 都不行就標「（區＋路）」
反查遵守 Nominatim 規範（每秒 1 次），結果快取在 .hilife_reverse.json，重跑只查新點。
"""
import json, os, re, subprocess, time

UA = 'tw-food-map/1.0 (personal project)'
API = 'https://www.hilife.com.tw/webapi/api'
FW = str.maketrans('０１２３４５６７８９－', '0123456789-')
CN = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6', '七': '7', '八': '8', '九': '9', '十': '10'}
ADDR = re.compile(r'(?P<dist>[^市縣]{1,4}?[區鄉鎮市])(?P<road>[^區鄉鎮]+?(?:路|街|大道|道)(?:\d+段)?)(?P<lane>(?:\d+巷)?(?:\d+弄)?)(?P<no>\d+(?:之\d+)?)號')


def curl(*args, data=None):
    r = subprocess.run(['curl', '-sSfL', '-m', '200', '-A', UA, *args], input=data, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def norm(s):
    s = (s or '').translate(FW).replace('臺', '台').replace(' ', '')
    s = re.sub(r'^\d{3,6}', '', s)
    s = re.sub(r'([一二三四五六七八九十])段', lambda m: CN[m.group(1)] + '段', s)
    return re.sub(r'[（(].*?[)）]', '', s)


def parse(s):
    s = re.sub(r'^(台北市|新北市|桃園市|台中市|台南市|高雄市|基隆市|新竹市|嘉義市|[^市縣]{2}縣)', '', norm(s))
    m = ADDR.search(s)
    return (m['dist'], m['road'], m['lane'], m['no']) if m else None


def name_key(s):
    s = re.sub(r'萊爾富|hi-?life|便利商店|超商', '', norm(s), flags=re.I).strip()
    return s if s.endswith('店') else s + '店' if s else ''


def official_list():
    jar = '.hilife_cookies'
    token = json.loads(subprocess.run(['curl', '-sS', '-m', '30', '-c', jar, f'{API}/AntiForgery/GetAntiForgeryToken'],
                                      capture_output=True, text=True, check=True).stdout)['token']
    hdr = ['-b', jar, '-H', f'X-XSRF-TOKEN: {token}', '-H', 'Content-Type: application/json']
    shops = []
    for c in curl(*hdr, '-d', '{}', f'{API}/DistrictList/GetDistrictList')['Entries']:
        body = json.dumps({'City_Id': c['city_id'], 'Town_Id': '', 'Shop_Id': '', 'Services': [], 'Shop_Name': ''})
        shops += [{'id': e['shop_id'], 'name': e['shop_name'], 'adr': e['shop_adr'], 'tel': (e.get('shop_tel') or '').strip()}
                  for e in curl(*hdr, '-d', body, f'{API}/ShopServices/GetShopServices')['Entries']]
        time.sleep(0.5)
    os.remove(jar)
    return shops


def osm_points():
    q = '''[out:json][timeout:180];area["ISO3166-1"="TW"][admin_level=2]->.tw;
(nwr["shop"="convenience"]["brand"~"萊爾富|hi-life",i](area.tw);nwr["shop"="convenience"]["name"~"萊爾富|hi-life",i](area.tw););out center tags;'''
    for i in range(5):
        try:
            return curl('--data-urlencode', 'data@-', 'https://overpass-api.de/api/interpreter', data=q)['elements']
        except subprocess.CalledProcessError:
            time.sleep(20 * 2 ** i)
    raise SystemExit('Overpass 一直失敗，晚點再跑')


def reverse(lat, lon, cache):
    key = f'{lat},{lon}'
    if key not in cache:
        a = curl(f'https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=jsonv2&zoom=18&accept-language=zh-TW').get('address', {})
        cache[key] = {'dist': a.get('suburb') or a.get('city_district') or a.get('town') or '', 'road': a.get('road', '')}
        time.sleep(1.1)
    return cache[key]


def main():
    official = official_list()
    by_addr, by_road, by_name = {}, {}, {}
    for o in official:
        k = parse(o['adr'])
        if k:
            by_addr.setdefault(k, []).append(o)
            by_road.setdefault(k[:2], []).append(o)
        by_name.setdefault(name_key(o['name']), []).append(o)

    used, out = set(), []
    for e in osm_points():
        t, c = e.get('tags', {}), e.get('center', e)
        addr = t.get('addr:full') or ''.join(t.get(k, '') for k in ('addr:district', 'addr:street', 'addr:housenumber'))
        if addr and re.search(r'\d$', addr):
            addr += '號'
        k = parse(addr) if addr else None
        nk = name_key(t.get('branch') or t.get('name', ''))
        hit = next((c2[0] for c2 in (by_addr.get(k, []) if k else [], by_road.get(k[:2], []) if k else [], by_name.get(nk, []) if nk else [])
                    if len(c2) == 1 and c2[0]['id'] not in used), None)
        if hit:
            used.add(hit['id'])
        name = hit['name'] if hit else t.get('branch') or re.sub(r'萊爾富|hi-?life', '', t.get('name', ''), flags=re.I).strip()
        tel = hit['tel'] if hit else re.sub(r'^\+886[\s-]*', '0', (t.get('phone') or t.get('contact:phone') or '').split(';')[0]).strip()
        out.append([name, round(c['lat'], 5), round(c['lon'], 5)] + ([tel] if tel else []))

    cache_path = '.hilife_reverse.json'
    cache = json.load(open(cache_path, encoding='utf-8')) if os.path.exists(cache_path) else {}
    for p in out:
        if p[0]:
            continue
        r = reverse(p[1], p[2], cache)
        dist, road = norm(r['dist']), norm(r['road'])
        cands = [o for o in by_road.get((dist, road), []) if o['id'] not in used]
        if len(cands) == 1:
            used.add(cands[0]['id']); p[0] = cands[0]['name']
            if cands[0]['tel']:
                p[3:] = [cands[0]['tel']]
        elif road:
            p[0] = f'（{dist}{road}）'
    json.dump(cache, open(cache_path, 'w', encoding='utf-8'), ensure_ascii=False)

    s = open('stores.js', encoding='utf-8').read()
    stores = json.loads(s[s.index('{'):s.rindex('}') + 1])
    stores['萊爾富'] = out
    head = s[:s.index('const STORES')]
    with open('stores.js', 'w', encoding='utf-8') as f:
        f.write(head + 'const STORES = ' + json.dumps(stores, ensure_ascii=False, separators=(',', ':')) + ';\n')
    print('萊爾富', len(out), '家｜配到官方店名', len(used), '｜仍無名', sum(1 for n, *_ in out if not n))


assert parse('114台北市內湖區新湖三路255號1樓') == ('內湖區', '新湖三路', '', '255')
assert parse('台中市沙鹿區臺灣大道七段200號') == ('沙鹿區', '台灣大道7段', '', '200')
if __name__ == '__main__':
    main()
