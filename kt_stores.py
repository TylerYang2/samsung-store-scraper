import os
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import pandas as pd

FILE_NAME = "KT_Stores.xlsx"
BASE_URL  = "https://help.kt.com"
SEARCH_URL = f"{BASE_URL}/store/KtStoreSearchHtml.do"

REGIONS = [
    '서울', '경기', '인천', '부산', '대구', '대전',
    '광주', '울산', '세종', '강원', '충북', '충남',
    '경북', '경남', '전북', '전남', '제주',
]


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
        'Referer': f'{BASE_URL}/store/KtStoreSearch.do',
        'X-Requested-With': 'XMLHttpRequest',
    })
    s.get(f'{BASE_URL}/store/KtStoreSearch.do', timeout=15)
    return s


def _post(session: requests.Session, search_string: str, page_no: int) -> str:
    data = {
        'defaultFlag': '', 'searchSeq': '', 'listType': '',
        'searchType': '1',
        'searchString': search_string,
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
        'searchFlagUse': 'Y',
        'pageNo': str(page_no),
    }
    resp = session.post(SEARCH_URL, data=data, timeout=30)
    resp.raise_for_status()
    return resp.text


def _parse(html: str, region: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    stores = []
    for branch in soup.find_all('div', class_='branch', attrs={'name': 'listRow'}):
        def hv(name):
            el = branch.find('input', {'name': name})
            return el['value'].strip() if el and el.get('value') else ''

        name    = hv('selectShopName')
        address = hv('selectShopAddress')
        x       = hv('selectShopX')   # 경도 (lng)
        y       = hv('selectShopY')   # 위도 (lat)

        if not name:
            continue

        # 주소에서 구군 추출 (예: "서울특별시 서초구 ..." → "서초구")
        parts = address.split()
        gugun = parts[2] if len(parts) > 2 else ''

        stores.append({
            'sido':    region,
            'gugun':   gugun,
            'name':    name,
            'address': address,
            'lat':     float(y) if y else None,
            'lng':     float(x) if x else None,
        })
    return stores


def scrape_region(session: requests.Session, region: str) -> list[dict]:
    stores, page = [], 1
    while True:
        html  = _post(session, region, page)
        items = _parse(html, region)
        if not items:
            break
        stores.extend(items)
        page += 1
        time.sleep(0.5)
    return stores


def main():
    session    = get_session()
    all_stores = []
    seen       = set()

    for region in REGIONS:
        items = scrape_region(session, region)
        new   = 0
        for s in items:
            key = (s['name'], s['address'])
            if key not in seen:
                seen.add(key)
                all_stores.append(s)
                new += 1
        print(f"  ✓ {region}: {new}개")
        time.sleep(0.8)

    df = pd.DataFrame(all_stores)
    print(f"  → 총 {len(df)}개 KT 매장 수집")

    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", FILE_NAME)
    df.to_excel(path, index=False)
    print(f"  → Excel 저장: {path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
