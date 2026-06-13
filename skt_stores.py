import os
import time
from datetime import datetime

import requests
import pandas as pd

BASE_URL  = "https://m.tworld.co.kr"
STORE_URL = f"{BASE_URL}/bypass/core-modification/v1/region-find-store-list"
FILE_NAME = "SKT_Stores.xlsx"

# 시도명으로 검색 (searchAddr 앞부분과 매칭)
SEARCH_TERMS = [
    '서울', '경기', '인천', '부산', '대구', '대전',
    '광주', '울산', '세종', '강원', '충북', '충남',
    '경북', '경남', '전북', '전남', '제주',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    'Referer': f'{BASE_URL}/customer/store/search?storeType=0&sortType=2',
    'x-referrer': f'{BASE_URL}/customer/store/search?storeType=0&sortType=2',
    'X-Requested-With': 'XMLHttpRequest',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Content-Type': 'application/json; charset=UTF-8',
}


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f'{BASE_URL}/customer/store/search?storeType=0&sortType=2', timeout=15)
    return s


def get_stores(session: requests.Session, search_text: str, page: int) -> list[dict]:
    params = {
        'currentPage': page,
        'storeType': '0',
        'sortType': '2',
        'searchText': search_text,
    }
    try:
        resp = session.get(STORE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get('result', {}).get('regionInfoList', [])
    except Exception as e:
        print(f"    [조회 실패] {search_text} p{page}: {e}")
        return []


def scrape_all() -> pd.DataFrame:
    session   = get_session()
    collected = {}  # locCode → store dict

    for term in SEARCH_TERMS:
        page      = 1
        new_count = 0
        while True:
            items = get_stores(session, term, page)
            if not items:
                break
            for item in items:
                loc_code = item.get('locCode', '')
                if not loc_code or loc_code in collected:
                    continue
                address = item.get('searchAddr', '')
                parts   = address.split()
                collected[loc_code] = {
                    'sido':    parts[0] if parts else '',
                    'gugun':   parts[1] if len(parts) > 1 else '',
                    'name':    item.get('storeName', ''),
                    'address': address,
                    'lat':     float(item['geoY']) if item.get('geoY') else None,
                    'lng':     float(item['geoX']) if item.get('geoX') else None,
                }
                new_count += 1
            page += 1
            time.sleep(0.3)

        print(f"  ✓ {term}: {new_count}개")
        time.sleep(0.5)

    print(f"  → 총 {len(collected)}개 SKT 매장 수집")
    return pd.DataFrame(list(collected.values()))


def main():
    df = scrape_all()
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", FILE_NAME)
    df.to_excel(path, index=False)
    print(f"  → Excel 저장: {path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
