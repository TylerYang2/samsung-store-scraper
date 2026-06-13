import json
import os
import sys
import time
from datetime import datetime

import requests
import pandas as pd

BASE_URL      = "https://m.tworld.co.kr"
STORE_URL     = f"{BASE_URL}/bypass/core-modification/v1/region-find-store-list"
BOX_FOLDER_ID = "387707675849"

BOX_CLIENT_ID     = os.environ.get("BOX_CLIENT_ID", "")
BOX_CLIENT_SECRET = os.environ.get("BOX_CLIENT_SECRET", "")
BOX_REFRESH_TOKEN = os.environ.get("BOX_REFRESH_TOKEN", "")
BOX_ACCESS_TOKEN  = os.environ.get("BOX_ACCESS_TOKEN", "")

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
            collected[loc_code] = {
                'sido':    parts[0] if parts else '',
                'gugun':   parts[1] if len(parts) > 1 else '',
                'name':    item.get('storeName', ''),
                'address': address,
                'lat':     float(item['geoY']) if item.get('geoY') else None,
                'lng':     float(item['geoX']) if item.get('geoX') else None,
            }
        print(f"    p{page}: {len(items)}개 → 누계 {len(collected)}개")
        if len(items) == 0:
            break
        page += 1
        time.sleep(0.5)

    print(f"  → 총 {len(collected)}개 SKT 매장 수집")
    return pd.DataFrame(list(collected.values()))


def box_refresh(refresh_token: str) -> tuple[str, str]:
    resp = requests.post(
        "https://api.box.com/oauth2/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token,
              "client_id": BOX_CLIENT_ID, "client_secret": BOX_CLIENT_SECRET},
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


def box_upload_file(token: str, folder_id: str, filename: str, filepath: str):
    file_id    = box_find_file(token, folder_id, filename)
    attributes = json.dumps({"name": filename, "parent": {"id": folder_id}})
    with open(filepath, "rb") as f:
        files = {"attributes": (None, attributes, "application/json"),
                 "file": (filename, f, "application/octet-stream")}
        headers = {"Authorization": f"Bearer {token}"}
        url = (f"https://upload.box.com/api/2.0/files/{file_id}/content"
               if file_id else "https://upload.box.com/api/2.0/files/content")
        resp = requests.post(url, headers=headers, files=files, timeout=60)
    resp.raise_for_status()
    print(f"  → Box {'업데이트' if file_id else '신규 업로드'} 완료: {filename}")


def main():
    df = scrape_all()

    today     = datetime.now().strftime("%m-%d-%Y")
    file_name = f"SKT_Stores_{today}.xlsx"

    os.makedirs("output", exist_ok=True)
    local_path = os.path.join("output", file_name)
    df.to_excel(local_path, index=False)
    print(f"  → Excel 저장: {local_path} ({len(df)}행)")

    if BOX_CLIENT_ID:
        print("Box 업로드 중...")
        token         = BOX_ACCESS_TOKEN
        refresh_token = BOX_REFRESH_TOKEN
        if not token:
            token, refresh_token = box_refresh(refresh_token)
        try:
            box_upload_file(token, BOX_FOLDER_ID, file_name, local_path)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                token, refresh_token = box_refresh(refresh_token)
                box_upload_file(token, BOX_FOLDER_ID, file_name, local_path)
            else:
                raise

    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
