import json
import os
import sys
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import pandas as pd

BASE_URL   = "https://help.kt.com"
SEARCH_URL = f"{BASE_URL}/store/KtStoreSearchHtml.do"
BOX_FOLDER_ID = "387707675849"

BOX_CLIENT_ID     = os.environ["BOX_CLIENT_ID"]
BOX_CLIENT_SECRET = os.environ["BOX_CLIENT_SECRET"]
BOX_REFRESH_TOKEN = os.environ["BOX_REFRESH_TOKEN"]
BOX_ACCESS_TOKEN  = os.environ.get("BOX_ACCESS_TOKEN", "")

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
    s.get(f'{BASE_URL}/store/KtStoreSearch.do', timeout=15)
    return s


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
    resp = session.post(SEARCH_URL, data=data, timeout=30)
    resp.raise_for_status()
    return resp.text


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
        gugun = parts[2] if len(parts) > 2 else ''
        stores.append({
            'sido': region, 'gugun': gugun,
            'name': name,  'address': address,
            'lat':  float(y) if y else None,
            'lng':  float(x) if x else None,
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


# ── Box 업로드 ────────────────────────────────────────
def box_refresh(refresh_token: str) -> tuple[str, str]:
    resp = requests.post(
        "https://api.box.com/oauth2/token",
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "client_id":     BOX_CLIENT_ID,
            "client_secret": BOX_CLIENT_SECRET,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"[ERROR] Box 토큰 갱신 실패: {resp.text[:200]}")
        sys.exit(1)
    data = resp.json()
    return data["access_token"], data["refresh_token"]


def box_find_file(token: str, folder_id: str, filename: str) -> str | None:
    resp = requests.get(
        f"https://api.box.com/2.0/folders/{folder_id}/items",
        headers={"Authorization": f"Bearer {token}"},
        params={"fields": "id,name,type", "limit": 1000},
        timeout=15,
    )
    resp.raise_for_status()
    for item in resp.json().get("entries", []):
        if item["type"] == "file" and item["name"] == filename:
            return item["id"]
    return None


def box_upload(token: str, folder_id: str, filename: str, filepath: str):
    file_id    = box_find_file(token, folder_id, filename)
    attributes = json.dumps({"name": filename, "parent": {"id": folder_id}})
    with open(filepath, "rb") as f:
        files = {
            "attributes": (None, attributes, "application/json"),
            "file":       (filename, f, "application/octet-stream"),
        }
        headers = {"Authorization": f"Bearer {token}"}
        url = (f"https://upload.box.com/api/2.0/files/{file_id}/content"
               if file_id else "https://upload.box.com/api/2.0/files/content")
        resp = requests.post(url, headers=headers, files=files, timeout=60)
    resp.raise_for_status()
    print(f"  → Box {'업데이트' if file_id else '신규 업로드'} 완료: {filename}")


# ── 메인 ─────────────────────────────────────────────
def main():
    df = scrape_all()

    today     = datetime.now().strftime("%m-%d-%Y")
    file_name = f"KT_Stores_{today}.xlsx"

    os.makedirs("output", exist_ok=True)
    local_path = os.path.join("output", file_name)
    df.to_excel(local_path, index=False)
    print(f"  → Excel 저장: {local_path} ({len(df)}행)")

    # Box 업로드
    print("Box 업로드 중...")
    token         = BOX_ACCESS_TOKEN
    refresh_token = BOX_REFRESH_TOKEN
    refreshed     = False

    if not token:
        token, refresh_token = box_refresh(refresh_token)
        refreshed = True

    try:
        box_upload(token, BOX_FOLDER_ID, file_name, local_path)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            print("  → access_token 만료, refresh 중...")
            token, refresh_token = box_refresh(refresh_token)
            refreshed = True
            box_upload(token, BOX_FOLDER_ID, file_name, local_path)
        else:
            raise

    if refreshed:
        print(f"  → 새 토큰 발급됨 (GitHub Secret 수동 갱신 필요)")
        print(f"  BOX_ACCESS_TOKEN={token}")
        print(f"  BOX_REFRESH_TOKEN={refresh_token}")

    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
