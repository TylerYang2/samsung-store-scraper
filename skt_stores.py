import os
import time
from datetime import datetime

import requests
import pandas as pd

BASE_URL      = "https://m.tworld.co.kr"
STORE_URL     = f"{BASE_URL}/bypass/core-modification/v1/region-find-store-list"

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


def get_stores_page(session: requests.Session, page: int, search_text: str = '') -> list[dict]:
    params = {'currentPage': page, 'storeType': '0', 'sortType': '2'}
    if search_text:
        params['searchText'] = search_text
    for attempt in range(3):
        try:
            resp = session.get(STORE_URL, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            items = data.get('result', {}).get('regionInfoList', [])
            if page == 1 and not search_text:
                print(f"    [샘플] code={data.get('code')} items={len(items)} "
                      f"first={items[0].get('storeName','') if items else '없음'}")
            return items
        except Exception as e:
            print(f"    [재시도 {attempt+1}/3] p{page}: {e}")
            time.sleep(5)
    return []


def scrape_all() -> pd.DataFrame:
    session   = get_session()
    collected = {}

    # 1단계: searchText 없이 전체 조회
    print("  전체 매장 조회 시도 (searchText 없음)...")
    page = 1
    while True:
        items = get_stores_page(session, page)
        if not items:
            print(f"    p{page}: 0개 → 종료")
            break
        for item in items:
            loc_code = item.get('locCode', '')
            if not loc_code or loc_code in collected:
                continue
            address = item.get('searchAddr', '')
            parts   = address.split()
            try:
                lat = float(item.get('geoY')) if item.get('geoY') else None
                lng = float(item.get('geoX')) if item.get('geoX') else None
            except (ValueError, TypeError):
                lat, lng = None, None
            collected[loc_code] = {
                'locCode': loc_code,
                'sido':    parts[0] if parts else '',
                'gugun':   parts[1] if len(parts) > 1 else '',
                'name':    item.get('storeName', ''),
                'address': address,
                'lat':     lat,
                'lng':     lng,
            }
        print(f"    p{page}: {len(items)}개 → 누계 {len(collected)}개")
        page += 1
        time.sleep(0.5)

    print(f"  → 총 {len(collected)}개 SKT 매장 수집")
    return pd.DataFrame(list(collected.values()))


def main():
    df = scrape_all()

    if len(df) == 0:
        raise Exception("SKT 매장 수집 결과가 0개 — API 차단 또는 구조 변경 확인 필요")

    today     = datetime.now().strftime("%m-%d-%Y")
    file_name = f"SKT_Stores_{today}.xlsx"

    os.makedirs("output", exist_ok=True)
    local_path = os.path.join("output", file_name)
    df.to_excel(local_path, index=False)
    print(f"  → Excel 저장: {local_path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
