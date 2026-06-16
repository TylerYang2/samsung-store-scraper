import os
from datetime import datetime

import requests
import pandas as pd

BASE_URL  = "https://www.ktmns.com"
STORE_URL = f"{BASE_URL}/user/liststore"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    'Referer': f'{BASE_URL}/about-store/store',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
}


def scrape_all() -> pd.DataFrame:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f'{BASE_URL}/about-store/store', timeout=15)

    resp = s.post(STORE_URL, json={}, timeout=30)
    resp.raise_for_status()

    items = resp.json().get('storeList', [])
    stores = []
    for item in items:
        if not item.get('active', True):
            continue
        try:
            lat = float(item['lat']) if item.get('lat') else None
            lng = float(item['lng']) if item.get('lng') else None
        except (ValueError, TypeError):
            lat, lng = None, None
        stores.append({
            'uid':     item.get('uid'),
            'type':    item.get('type', ''),
            'sido':    item.get('locationSido', ''),
            'gugun':   item.get('locationSigungu', ''),
            'name':    item.get('storeName', ''),
            'address': item.get('address', ''),
            'lat':     lat,
            'lng':     lng,
        })

    print(f"  → 총 {len(stores)}개 KT M&S 매장 수집")
    return pd.DataFrame(stores)


def main():
    df = scrape_all()

    if len(df) == 0:
        raise Exception("KT M&S 매장 수집 결과가 0개 — API 차단 또는 구조 변경 확인 필요")

    today     = datetime.now().strftime("%m-%d-%Y")
    file_name = f"KTMNS_Stores_{today}.xlsx"

    os.makedirs("output", exist_ok=True)
    local_path = os.path.join("output", file_name)
    df.to_excel(local_path, index=False)
    print(f"  → Excel 저장: {local_path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
