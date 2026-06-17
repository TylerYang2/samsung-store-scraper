import os
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_URL   = "https://help.kt.com"
SEARCH_URL = f"{BASE_URL}/store/KtStoreSearchHtml.do"

REGIONS = [
    '서울', '경기', '인천', '부산', '대구', '대전',
    '광주', '울산', '세종', '강원', '충북', '충남',
    '경북', '경남', '전북', '전남', '제주',
]


# ── KT 스크래핑 ───────────────────────────────────────
def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
        'Referer': f'{BASE_URL}/store/KtStoreSearch.do',
        'X-Requested-With': 'XMLHttpRequest',
    })
    for attempt in range(5):
        try:
            s.get(f'{BASE_URL}/store/KtStoreSearch.do', timeout=30)
            return s
        except Exception as e:
            print(f"  [세션 재시도 {attempt+1}/5] {e}")
            time.sleep(10)
    return s  # 세션 쿠키 없이 진행


def _post(session: requests.Session, search_string: str, page_no: int) -> str:
    data = {
        'defaultFlag': '', 'searchSeq': '', 'listType': '',
        'searchType': '1', 'searchString': search_string,
        'searchLocation1': '', 'searchLocation2': '',
        'searchLocation3': '', 'searchLocation4': '',
        'searchX': '', 'searchY': '',
        'searchSubwayLocation1': '', 'searchSubwayLocation2': '',
        'pageNum': '', 'leasePhoneOper': '',
        'searchFlag1': 'N', 'searchFlag2': 'N', 'searchFlag3': 'N',
        'searchFlag4': 'N', 'searchFlag5': 'N', 'searchFlag6': 'N',
        'searchFlag7': '', 'searchFlag8': '',
        'searchFlag9': 'N', 'searchFlag10': 'N',
        'searchFlag11': '', 'searchFlag12': '',
        'wrTrns': 'N', 'chrgPmnt': 'N', 'overTimeShopSearchYn': '',
        'searchFlagUse': 'Y', 'pageNo': str(page_no),
    }
    for attempt in range(5):
        try:
            resp = session.post(SEARCH_URL, data=data, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"    [POST 재시도 {attempt+1}/5] {e}")
            time.sleep(10)
    return ''


def _parse(html: str, region: str) -> list[dict]:
    soup   = BeautifulSoup(html, 'html.parser')
    stores = []
    for branch in soup.find_all('div', class_='branch', attrs={'name': 'listRow'}):
        def hv(n):
            el = branch.find('input', {'name': n})
            return el['value'].strip() if el and el.get('value') else ''
        name    = hv('selectShopName')
        address = hv('selectShopAddress')
        x       = hv('selectShopX')
        y       = hv('selectShopY')
        if not name:
            continue
        parts = address.split()
        gugun = parts[1] if len(parts) > 1 else ''
        shop_code = hv('selectShopCode')
        tel = hv('selectShopTel')
        old_address = hv('selectShopOldAddress')
        try:
            lat = float(y) if y else None
            lng = float(x) if x else None
        except (ValueError, TypeError):
            lat, lng = None, None
        week_el = branch.find('span', class_='week')
        more_el = branch.find('span', class_='more')
        hours = ' '.join(filter(None, [
            week_el.get_text(strip=True) if week_el else '',
            more_el.get_text(separator=' ', strip=True) if more_el else '',
        ])).strip()
        services = ','.join(el.get_text(strip=True) for el in branch.find_all('span', class_='icon'))
        stores.append({
            'shopCode': shop_code,
            'sido': region, 'gugun': gugun,
            'name': name,  'address': address,
            'lat':  lat,
            'lng':  lng,
            'tel':        tel,
            'oldAddress': old_address,
            'hours':      hours,
            'services':   services,
        })
    return stores


def scrape_all() -> pd.DataFrame:
    session    = get_session()
    all_stores, seen = [], set()
    for region in REGIONS:
        page = 1
        while True:
            items = _parse(_post(session, region, page), region)
            if not items:
                break
            for s in items:
                key = (s['name'], s['address'])
                if key not in seen:
                    seen.add(key)
                    all_stores.append(s)
            page += 1
            time.sleep(0.5)
        print(f"  ✓ {region}: {sum(1 for s in all_stores if s['sido'] == region)}개")
        time.sleep(0.8)
    print(f"  → 총 {len(all_stores)}개 KT 매장 수집")
    return pd.DataFrame(all_stores)


# ── 메인 ─────────────────────────────────────────────
def main():
    df = scrape_all()

    if len(df) == 0:
        raise Exception("KT 매장 수집 결과가 0개 — API 차단 또는 구조 변경 확인 필요")

    today     = datetime.now().strftime("%m-%d-%Y")
    file_name = f"KT_Stores_{today}.xlsx"

    os.makedirs("output", exist_ok=True)
    local_path = os.path.join("output", file_name)
    df.to_excel(local_path, index=False)
    print(f"  → Excel 저장: {local_path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
