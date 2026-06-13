import os
import time
from datetime import datetime

import requests
import pandas as pd

BASE_URL  = "https://www.lguplus.com"
STORE_URL = f"{BASE_URL}/uhdc/fo/cusp/svug/shopinfo/v1/ccw-shop-nm"
FILE_NAME = "LGU_Stores.xlsx"

SIDO_LIST = [
    '서울특별시', '경기도', '인천광역시', '부산광역시', '대구광역시',
    '대전광역시', '광주광역시', '울산광역시', '세종특별자치시',
    '강원특별자치도', '충청북도', '충청남도', '경상북도', '경상남도',
    '전북특별자치도', '전라남도', '제주특별자치도',
]

# 빈 sigungu로 조회 시 0개 반환되는 지역 — 구/군별 직접 조회
DISTRICT_FALLBACK = {
    '충청남도': ['천안시', '공주시', '보령시', '아산시', '서산시', '논산시', '계룡시', '당진시',
               '금산군', '부여군', '서천군', '청양군', '홍성군', '예산군', '태안군'],
    '경상남도': ['창원시', '진주시', '통영시', '사천시', '김해시', '밀양시', '거제시', '양산시',
               '의령군', '함안군', '창녕군', '고성군', '남해군', '하동군', '산청군', '함양군',
               '거창군', '합천군'],
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    'Referer': f'{BASE_URL}/support/store-address',
    'X-MENU-URL': '/support/store-address',
    'X-USER-AGENT-TYPE': 'PC',
    'Accept': 'application/json, text/plain, */*',
}


def get_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f'{BASE_URL}/support/store-address', timeout=15)
    return s


def get_stores(session: requests.Session, sido: str, sigungu: str = '') -> list[dict]:
    params = {
        '_paging': 'true',
        'sido': sido, 'sigungu': sigungu, 'searchWord': '',
        'callDtlInsptPsblYn': 'N', 'rnphnJobPsblYn': 'N',
        'nameEmbzPsblYn': 'N', 'o2oShopYn': 'N',
        'ptcrEntrPsblYn': 'N', 'smhPsblYn': 'N',
        'eprnShopYn': 'N', 'apleAsYn': 'N',
        'frgrRspoYn': 'N', 'parkPsblYn': 'N',
        'shopVsitPsblYn': 'N', 'vsitDlvPsblYn': 'N',
        'thdyDlvPsblYn': 'N',
        'pageNo': '1', 'rowSize': '9999',
    }
    try:
        resp = session.get(STORE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            if sido in ('충청남도', '경상남도') and len(data) == 0:
                print(f"    [DEBUG 0개] sido={sido} sigungu={sigungu} | status={resp.status_code} | raw={resp.text[:150]}")
            return data
        if isinstance(data, dict):
            for key in ('data', 'list', 'result', 'shopList'):
                if isinstance(data.get(key), list):
                    return data[key]
            if sido in ('충청남도', '경상남도'):
                print(f"    [DEBUG dict] sido={sido} sigungu={sigungu} | keys={list(data.keys())} | raw={resp.text[:150]}")
        return []
    except Exception as e:
        print(f"    [매장 조회 실패] {sido} {sigungu}: {e}")
        return []


def scrape_all() -> pd.DataFrame:
    session    = get_session()
    all_stores, seen = [], set()

    for sido in SIDO_LIST:
        districts  = DISTRICT_FALLBACK.get(sido, [''])
        sido_count = 0

        for sigungu in districts:
            items = get_stores(session, sido, sigungu)
            for item in items:
                key = item.get('posCd') or (item.get('posNm', ''), item.get('roadAddr', ''))
                if key in seen:
                    continue
                seen.add(key)
                address = item.get('roadAddr') or item.get('jibunAddr') or ''
                parts   = address.split()
                gugun   = sigungu or (parts[2] if len(parts) > 2 else '')
                x = item.get('posXcrdVlue', '')
                y = item.get('posYcrdVlue', '')
                all_stores.append({
                    'sido':    sido,
                    'gugun':   gugun,
                    'name':    item.get('posNm', ''),
                    'address': address,
                    'lat':     float(y) if y else None,
                    'lng':     float(x) if x else None,
                })
                sido_count += 1
            time.sleep(0.3)

        print(f"  ✓ {sido}: {sido_count}개")
        time.sleep(0.5)

    print(f"  → 총 {len(all_stores)}개 LGU+ 매장 수집")
    return pd.DataFrame(all_stores)


def main():
    df = scrape_all()

    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", FILE_NAME)
    df.to_excel(path, index=False)
    print(f"  → Excel 저장: {path} ({len(df)}행)")
    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
