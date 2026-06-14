import os
import re
import time as _time
import urllib.parse
from datetime import datetime

import requests
import pandas as pd
from playwright.sync_api import sync_playwright

# ── 설정 ──────────────────────────────────────────────
SAMSUNG_URL = "https://www.samsungstore.com/shop/selectFindShopMain.sesc?menu=w401"
BOX_FILE_NAME = "Samsung_Stores.xlsx"
KAKAO_API_KEY = os.environ.get("KAKAO_API_KEY", "")


# ── 1. 스크래핑 ───────────────────────────────────────
BASE_URL = "https://www.samsungstore.com"


def scrape_stores() -> list[dict]:
    stores = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ko-KR",
        )
        page = context.new_page()

        sido_responses = []

        def handle_response(response):
            try:
                if response.status == 200 and "selectMakeListAjax" in response.url:
                    sido_responses.append(response.json())
            except Exception:
                pass

        page.on("response", handle_response)
        page.goto(SAMSUNG_URL, wait_until="networkidle", timeout=30000)

        # 시도 코드 추출 (SI_DO_ORDERNUM 키로 구분)
        sido_codes = []
        for data in sido_responses:
            if isinstance(data, list) and data and "SI_DO_ORDERNUM" in data[0]:
                sido_codes = [item["CODE"] for item in data]
                break
        print(f"  [SIDO] {len(sido_codes)}개 시도 코드 확보")
        if not sido_codes:
            raise Exception("시도 코드 추출 실패 — Samsung 페이지 로드 또는 API 구조 변경 확인 필요")

        seen = set()
        first_response = True

        for sido_code in sido_codes:
            sido_name = urllib.parse.unquote(sido_code)

            # 구군 목록
            gugun_raw = page.evaluate("""async (code) => {
                const resp = await fetch('/shop/selectMakeListAjax.sesc', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json, text/javascript, */*; q=0.01'
                    },
                    body: 'sType=gugun&keyword=' + code + '&pageGubun=shop'
                });
                const t = await resp.text();
                try { return JSON.parse(t); } catch { return null; }
            }""", sido_code)

            if isinstance(gugun_raw, list) and gugun_raw and "CODE" in gugun_raw[0]:
                gugun_list = [(urllib.parse.unquote(g["CODE"]), int(g.get("CNT", 0)))
                              for g in gugun_raw]
            else:
                gugun_list = [(sido_name, 0)]

            sido_count = 0
            for gugun_name, cnt in gugun_list:
                select_text = f"{sido_name} {gugun_name}"
                page_no = 1
                while True:
                    store_raw = page.evaluate("""async ([text, pageNo]) => {
                        const enc = encodeURIComponent(text);
                        const body = [
                            'pageNo=' + pageNo,
                            'searchText=', 'strDpsType=',
                            'neLat=', 'neLng=', 'swLat=', 'swLng=',
                            'selectType=0',
                            'selectText=' + enc,
                            'nearPost=' + enc,
                            'nearYn=N', 'distPlaceCd='
                        ].join('&');
                        const resp = await fetch('/shop/selectSearchMapListAjax.sesc', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
                                'X-Requested-With': 'XMLHttpRequest',
                                'Accept': 'application/json, text/javascript, */*; q=0.01'
                            },
                            body: body
                        });
                        const t = await resp.text();
                        try { return JSON.parse(t); } catch { return {'_raw': t.slice(0, 300)}; }
                    }""", [select_text, page_no])

                    if first_response:
                        print(f"  [STORE 응답 구조] {str(store_raw)[:600]}")
                        first_response = False

                    items = _extract_items_from_json(store_raw)
                    if not items:
                        break
                    new_items = 0
                    for item in items:
                        key = (item.get("name", ""), item.get("address", ""))
                        if key not in seen:
                            seen.add(key)
                            item["sido"] = sido_name
                            item["gugun"] = gugun_name
                            stores.append(item)
                            new_items += 1
                            sido_count += 1
                    if new_items == 0:
                        break
                    page_no += 1

            print(f"  ✓ {sido_name}: {sido_count}개")

        browser.close()

    print(f"  → 총 {len(stores)}개 매장 수집")
    return stores


def _extract_items_from_json(data) -> list[dict]:
    if isinstance(data, dict) and "_raw" in data:
        return []
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("list", "data", "shopList", "storeList", "result",
                    "shopInfoList", "resultList", "rows"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("dist_place_nm") or item.get("shopNm") or item.get("SHOP_NM") or
                item.get("storeName") or item.get("name") or item.get("shopName") or "")
        addr = (item.get("addr") or item.get("ADDR") or item.get("address") or
                item.get("shopAddr") or item.get("roadAddr") or item.get("ROAD_ADDR") or "")
        tel = (item.get("tel") or item.get("tel_no") or item.get("TEL") or
               item.get("telNo") or item.get("TEL_NO") or item.get("phone") or "")
        if name:
            result.append({"name": name, "address": addr, "tel": tel})
    return result


# 주소 기반 사전 좌표 테이블 (API 지오코딩 실패 대비)
_KNOWN_COORDS: dict[str, tuple[float, float]] = {
    '서울 강동구 상일로6길 26 내':                                       (37.5462, 127.1658),
    '서울 강서구 하늘길 38 5F 삼성전자':                                  (37.5685, 126.8002),
    '서울 광진구 아차산로 272 이마트 지하1층 삼성모바일':                  (37.5394, 127.0915),
    '서울 노원구 마들로3길 15 (월계동, 일렉트로마트) 2층':                 (37.6168, 127.0614),
    '서울 동대문구 왕산로 168(용두동, 삼성화재청량리사옥) 7층':            (37.5750, 127.0456),
    '서울 서초구 성촌길 34 (우면동, (주)삼성전자서울R&D캠퍼스) F타워 B1F': (37.4765, 127.0349),
    '서울 성동구 왕십리광장로 17 (행당동) 이마트 3F':                     (37.5613, 127.0379),
    '서울 송파구 올림픽로 240 10F 삼성전자':                              (37.5133, 127.1000),
    '서울 송파구 올림픽로35길 125 삼성SDS 타워서관 B1F':                  (37.5147, 127.1038),
    '서울 영등포구 영중로 15 지하층 B1 이마트  영등포점':                  (37.5165, 126.9024),
    '서울 영등포구 영중로 15 타임스퀘어 2층 교보문고 내 삼성스토어 모바일': (37.5165, 126.9024),
    '서울 중구 을지로 51, 5F':                                           (37.5660, 126.9804),
    '경기 고양시 고양대로 1955 스타필드고양 2F':                          (37.6557, 126.8308),
    '경기 고양시 일산서구 킨텍스로 171 B1층 이마트킨텍스':                (37.6634, 126.8126),
    '경기 광명시 서면로 79':                                              (37.4542, 126.8617),
    '경기 부천시 석천로 188(중동) 일렉트로마트 1F':                       (37.5031, 126.7657),
    '경기 부천시 원미구 길주로 180 7F 삼성전자':                          (37.5055, 126.7645),
    '경기 성남시 분당구 성남대로925번길 16(성남(분당)여객자동차터미널)':    (37.3988, 127.1264),
    '경기 수원시 권선구 수인로 291 3층':                                  (37.2622, 126.9944),
    '경기 수원시 영통구 삼성로 129 (매탄동, 삼성전자) 수원디지털시티 중앙광장 B1F': (37.3249, 127.1085),
    '경기 수원시 영통구 삼성로130 (매탄동) 컨벤션동(소재연구단지본관) 2층': (37.3255, 127.1092),
    '경기 수원시 팔달구 덕영대로 924 5F 삼성전자':                        (37.2682, 127.0057),
    '경기 시흥시 서해안로 699(정왕동) 신세계프리미엄아울렛 시흥점 2F.':   (37.3511, 126.7330),
    '경기 안산시 단원구 원포공원 1로 46, 3F':                            (37.3216, 126.8360),
    '경기 용인시 기흥구 삼성로 1(삼성전자(주)기흥캠퍼스)':               (37.2790, 127.0431),
    '경기 용인시 수지구 포은대로 536((주)신세계백화점경기점)':             (37.3136, 127.1009),
    '경기 평택시 고덕면 삼성로 114, 삼성전자 평택사업장 복지1동 1F 삼성스토어 모바일': (37.0347, 127.0800),
    '경기 화성시 삼성전자로 1-1 삼성전자DSR타워 1층 삼성스토어 모바일':   (37.1963, 126.9780),
    '부산 강서구 녹산산업중로 333 지하1층':                               (35.1082, 128.8524),
    '부산 강서구 르노삼성대로 61 복합복지동1층 삼성모바일':               (35.0979, 128.8472),
    '부산 금정구 중앙대로1841번길 24((주)이마트금정점)':                  (35.2509, 129.0797),
    '부산 북구 낙동대로 1783(삼성전자판매(주)덕천점)':                    (35.2195, 128.9990),
    '대전 동구 동서대로 1689 4층':                                        (36.3535, 127.4180),
    '울산 남구 삼산로 261 별관2F 삼성딜라이트샵':                         (35.5395, 129.3319),
    '울산 남구 삼산로 288 B1F 삼성전자':                                  (35.5418, 129.3300),
    '울산 북구 염포로 599 현대차문화회관 지하1층':                        (35.5859, 129.3697),
    '광주 북구 앰코로 100 복지관 1F':                                     (35.2282, 126.8441),
    '강원 원주시 무실밤골길 29':                                          (37.3513, 127.9605),
    '충남 아산시 탕정면 삼성로 181 비전홀3층 삼성 모바일 스토어':         (36.8138, 127.1052),
    '충남 아산시 탕정면 탕정로 380-2 OLEX동 3층 모바일샵':               (36.8155, 127.1068),
    '충남 천안시 동남구 만남로 43(신세계백화점) A관 4F':                  (36.7996, 127.1155),
    '충남 천안시 동남구 만남로 43(신세계백화점) B관 M3F':                 (36.7996, 127.1155),
    '충남 천안시 서북구 업성2길 89':                                      (36.8438, 127.1291),
    '경북 구미시 구미대로 256(광평동) 이마트2F':                          (36.1277, 128.3371),
    '경북 구미시 3공단3로 302 한마음프라자 1층 삼성스토어 모바일':        (36.0787, 128.4092),
    '경북 상주시 상서문2길 110':                                          (36.4148, 128.1612),
    '경남 창원시 성산구 두산볼보로 22 두산중공업 별관 1층':               (35.2205, 128.6808),
    '전북 완주군 봉동읍 봉동로 466-19 (현대사원@문화관1층) 전주현대자동차점': (35.8622, 127.0818),
    '전남 순천시 팔마로 191((주)이마트)':                                 (34.9454, 127.4875),
    '세종특별자치시 연동면 삼성길 25':                                    (36.5558, 127.2182),
}


def geocode_df(df: pd.DataFrame) -> pd.DataFrame:
    """주소 컬럼으로 lat/lng 추가. 사전 테이블 → Kakao → Nominatim 순서로 시도."""
    lats, lngs = [], []
    for addr in df.get("address", []):
        addr_str = str(addr).replace('&amp;', '&').strip() if addr and str(addr) != 'nan' else ''
        # 1) 사전 좌표 테이블
        if addr_str in _KNOWN_COORDS:
            lat, lng = _KNOWN_COORDS[addr_str]
            lats.append(lat)
            lngs.append(lng)
            continue
        # 2) Kakao API
        lat, lng = _kakao_geocode(addr_str) if KAKAO_API_KEY and addr_str else (None, None)
        # 3) Nominatim fallback
        if lat is None and addr_str:
            lat, lng = _nominatim_geocode(addr_str)
            if lat is not None:
                print(f"    [Nominatim fallback] {addr_str[:40]}")
            _time.sleep(1.1)
        lats.append(lat)
        lngs.append(lng)
    df["lat"] = lats
    df["lng"] = lngs
    return df


def _kakao_geocode(address: str):
    if not address or len(address) < 3:
        return None, None
    try:
        resp = requests.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
            params={"query": address, "size": 1},
            timeout=10,
        )
        docs = resp.json().get("documents", [])
        if docs:
            return float(docs[0]["y"]), float(docs[0]["x"])
    except Exception as e:
        print(f"    [Kakao WARN] {address[:30]}: {e}")
    return None, None


def _nominatim_geocode(address: str):
    if not address or len(address) < 3:
        return None, None
    # 괄호 제거
    clean = re.sub(r'\(.*?\)', '', address).strip()
    # 도로명+번지만 추출 (번지 이후 층/건물명 제거)
    m = re.search(r'^(.+?(?:로|길|대로)\s+\d+(?:-\d+)?)', clean)
    short = m.group(1).strip() if m else clean
    # 순서대로 시도: 짧은주소 → 괄호제거 → 원본
    queries = list(dict.fromkeys([short, clean, address]))
    for query in queries:
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "kr"},
                headers={"User-Agent": "SamsungStoreScraper/1.0 (tyleryang@apple.com)"},
                timeout=10,
            )
            results = resp.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
        except Exception as e:
            print(f"    [geocode WARN] {address[:30]}: {e}")
        _time.sleep(1.1)
    return None, None


# ── 메인 ──────────────────────────────────────────────
def main():
    # 1. 스크래핑
    stores = scrape_stores()
    df = pd.DataFrame(stores)
    if len(df) > 0:
        cols = ["sido", "gugun", "name", "address"]
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
        df = geocode_df(df)
    print(f"  → 총 {len(df)}개 매장, 컬럼: {list(df.columns)}")

    # 2. Excel 저장 (output/ 폴더 — Actions artifact로 다운로드)
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", BOX_FILE_NAME)
    df.to_excel(path, index=False)
    print(f"  → Excel 저장: {path} ({len(df)}행)")

    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
