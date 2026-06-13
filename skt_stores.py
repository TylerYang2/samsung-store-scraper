import os
import time
from datetime import datetime

import requests
import pandas as pd

BASE_URL  = "https://m.tworld.co.kr"
STORE_URL = f"{BASE_URL}/bypass/core-modification/v1/region-find-store-list"
FILE_NAME = "SKT_Stores.xlsx"

# 전국 시/군/구명 검색 (searchAddr 기준 매칭)
SEARCH_TERMS = [
    # 서울
    '강남구','강동구','강북구','강서구','관악구','광진구','구로구','금천구',
    '노원구','도봉구','동대문구','동작구','마포구','서대문구','서초구',
    '성동구','성북구','송파구','양천구','영등포구','용산구','은평구',
    '종로구','중구','중랑구',
    # 경기
    '수원시','성남시','의정부시','안양시','부천시','광명시','동두천시',
    '안산시','고양시','과천시','구리시','남양주시','오산시','시흥시',
    '군포시','의왕시','하남시','용인시','파주시','이천시','안성시',
    '김포시','화성시','광주시','양주시','포천시','여주시','연천군',
    '가평군','양평군',
    # 인천
    '계양구','미추홀구','남동구','동구','부평구','서구','연수구','중구',
    '강화군','옹진군',
    # 부산
    '강서구','금정구','기장군','남구','동구','동래구','부산진구','북구',
    '사상구','사하구','서구','수영구','연제구','영도구','해운대구',
    # 대구
    '군위군','남구','달서구','달성군','동구','북구','서구','수성구','중구',
    # 대전
    '대덕구','동구','서구','유성구','중구',
    # 광주
    '광산구','남구','동구','북구','서구',
    # 울산
    '남구','동구','북구','울주군','중구',
    # 세종
    '세종시',
    # 강원
    '강릉시','고성군','동해시','삼척시','속초시','양구군','양양군',
    '영월군','원주시','인제군','정선군','철원군','춘천시','태백시',
    '평창군','홍천군','화천군','횡성군',
    # 충북
    '괴산군','단양군','보은군','영동군','옥천군','음성군','제천시',
    '증평군','진천군','청주시','충주시',
    # 충남
    '계룡시','공주시','금산군','논산시','당진시','보령시','부여군',
    '서산시','서천군','아산시','예산군','천안시','청양군','태안군','홍성군',
    # 경북
    '경산시','경주시','고령군','구미시','군위군','김천시','문경시',
    '봉화군','상주시','성주군','안동시','영덕군','영양군','영주시',
    '영천시','예천군','울릉군','울진군','의성군','청도군','청송군',
    '칠곡군','포항시',
    # 경남
    '거제시','거창군','고성군','김해시','남해군','밀양시','사천시',
    '산청군','양산시','의령군','진주시','창녕군','창원시','통영시',
    '하동군','함안군','함양군','합천군',
    # 전북
    '고창군','군산시','김제시','남원시','무주군','부안군','순창군',
    '완주군','익산시','임실군','장수군','전주시','정읍시','진안군',
    # 전남
    '강진군','고흥군','곡성군','광양시','구례군','나주시','담양군',
    '목포시','무안군','보성군','순천시','신안군','여수시','영광군',
    '영암군','완도군','장성군','장흥군','진도군','함평군','해남군','화순군',
    # 제주
    '제주시','서귀포시',
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
