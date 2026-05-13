import os
import json
import sys
import base64
import tempfile
import time as _time
from datetime import datetime

import requests
import pandas as pd
from nacl import encoding, public
from playwright.sync_api import sync_playwright

# ── 설정 ──────────────────────────────────────────────
SAMSUNG_URL = "https://www.samsungstore.com/shop/selectFindShopMain.sesc?menu=w401"
BOX_FOLDER_ID = "381592399197"
BOX_FILE_NAME = "Samsung_Stores.xlsx"

BOX_CLIENT_ID     = os.environ["BOX_CLIENT_ID"]
BOX_CLIENT_SECRET = os.environ["BOX_CLIENT_SECRET"]
BOX_REFRESH_TOKEN = os.environ["BOX_REFRESH_TOKEN"]
BOX_ACCESS_TOKEN  = os.environ.get("BOX_ACCESS_TOKEN", "")
GH_PAT            = os.environ.get("GH_PAT", "")
GH_REPO           = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo


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

        # 시도 코드 목록 추출
        region_codes = []
        for data in sido_responses:
            if isinstance(data, list) and data and "CODE" in data[0]:
                region_codes = [item["CODE"] for item in data if "CODE" in item]
                break
        print(f"  [REGION] {len(region_codes)}개 시도 코드")

        # 각 시도별 매장 HTML 요청 (세션 쿠키 포함)
        seen = set()
        for i, code in enumerate(region_codes):
            try:
                html_text = page.evaluate("""async (code) => {
                    const resp = await fetch('/shop/selectMakeListAjax.sesc', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8',
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json, text/javascript, */*; q=0.01'
                        },
                        body: 'sType=gugun&keyword=' + code + '&pageGubun=shop'
                    });
                    return await resp.text();
                }""", code)

                if i == 0:
                    print(f"  [HTML 응답 샘플]:\n{html_text[:800]}")

                items = _parse_store_html(html_text)
                new_count = 0
                for item in items:
                    key = (item.get("name", ""), item.get("address", ""))
                    if key not in seen:
                        seen.add(key)
                        stores.append(item)
                        new_count += 1
                print(f"    {code} → {new_count}개")
            except Exception as e:
                print(f"    [WARN] {code}: {e}")

        browser.close()

    print(f"  → 총 {len(stores)}개 매장 수집")
    return stores


def _parse_store_html(html_text: str) -> list[dict]:
    """HTML 응답에서 매장 목록 파싱"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    stores = []
    selectors = [
        ("li", ".store-name, .shop-name, strong, h3, h4, .name"),
        ("li", "a"),
    ]
    # li 기반 파싱 시도
    lis = soup.find_all("li")
    for li in lis:
        name_el = li.find(class_=lambda c: c and any(x in c for x in ["name", "tit", "store"]))
        addr_el = li.find(class_=lambda c: c and any(x in c for x in ["addr", "address"]))
        tel_el = li.find(class_=lambda c: c and any(x in c for x in ["tel", "phone"]))
        name = name_el.get_text(strip=True) if name_el else li.get_text(strip=True)[:40]
        addr = addr_el.get_text(strip=True) if addr_el else ""
        tel = tel_el.get_text(strip=True) if tel_el else ""
        if name and len(name) > 2:
            stores.append({"name": name, "address": addr, "tel": tel})
    return stores


def geocode_df(df: pd.DataFrame) -> pd.DataFrame:
    """주소 컬럼으로 lat/lng 추가. Nominatim 사용."""
    lats, lngs = [], []
    for addr in df.get("address", []):
        lat, lng = _nominatim_geocode(addr)
        lats.append(lat)
        lngs.append(lng)
        _time.sleep(1.1)  # Nominatim rate limit
    df["lat"] = lats
    df["lng"] = lngs
    return df


def _nominatim_geocode(address: str):
    if not address or len(address) < 3:
        return None, None
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "kr"},
            headers={"User-Agent": "SamsungStoreScraper/1.0 (tyleryang@apple.com)"},
            timeout=10,
        )
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"    [geocode WARN] {address[:30]}: {e}")
    return None, None


# ── 2. Box 토큰 갱신 + 업로드 ─────────────────────────
def box_refresh_token(refresh_token: str) -> tuple[str, str]:
    resp = requests.post(
        "https://api.box.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": BOX_CLIENT_ID,
            "client_secret": BOX_CLIENT_SECRET,
        },
        timeout=15,
    )
    print(f"  [Box 토큰] status={resp.status_code} body={resp.text[:300]}")
    if not resp.ok:
        print("\n[ERROR] Box refresh_token 갱신 실패.")
        print("  원인: refresh_token이 만료되었거나 올바르지 않습니다.")
        print("  복구 방법: python box_oauth_setup.py 실행 → 출력된 토큰을")
        print("  BOX_ACCESS_TOKEN / BOX_REFRESH_TOKEN GitHub Secret에 붙여넣기")
        sys.exit(1)
    data = resp.json()
    return data["access_token"], data["refresh_token"]


def box_find_file(access_token: str, folder_id: str, filename: str) -> str | None:
    """폴더에서 동일 파일명의 file_id 반환, 없으면 None"""
    resp = requests.get(
        f"https://api.box.com/2.0/folders/{folder_id}/items",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"fields": "id,name,type", "limit": 1000},
        timeout=15,
    )
    resp.raise_for_status()
    for item in resp.json().get("entries", []):
        if item["type"] == "file" and item["name"] == filename:
            return item["id"]
    return None


def box_upload(access_token: str, folder_id: str, filename: str, file_path: str):
    file_id = box_find_file(access_token, folder_id, filename)
    attributes = json.dumps({"name": filename, "parent": {"id": folder_id}})

    with open(file_path, "rb") as f:
        files = {
            "attributes": (None, attributes, "application/json"),
            "file": (filename, f, "application/octet-stream"),
        }
        headers = {"Authorization": f"Bearer {access_token}"}

        if file_id:
            url = f"https://upload.box.com/api/2.0/files/{file_id}/content"
            resp = requests.post(url, headers=headers, files=files, timeout=60)
        else:
            url = "https://upload.box.com/api/2.0/files/content"
            resp = requests.post(url, headers=headers, files=files, timeout=60)

    resp.raise_for_status()
    action = "업데이트" if file_id else "신규 업로드"
    print(f"  → Box {action} 완료: {filename}")


# ── 3. GitHub Secret 갱신 ─────────────────────────────
def update_github_secret(secret_name: str, secret_value: str):
    if not GH_PAT or not GH_REPO:
        print("  → GH_PAT/GH_REPO 없음, GitHub secret 갱신 생략")
        return

    headers = {
        "Authorization": f"token {GH_PAT}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 레포 public key 조회
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    key_data = r.json()

    # libsodium으로 암호화
    pub_key = public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
    sealed = public.SealedBox(pub_key)
    encrypted = base64.b64encode(sealed.encrypt(secret_value.encode())).decode()

    # secret 업데이트
    resp = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{secret_name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
        timeout=10,
    )
    if resp.status_code in (201, 204):
        print(f"  → GitHub secret '{secret_name}' 갱신 완료")
    else:
        print(f"  → GitHub secret 갱신 실패 (status {resp.status_code}) — 수동 갱신 필요")


# ── 메인 ──────────────────────────────────────────────
def main():
    # 1. 스크래핑
    stores = scrape_stores()
    df = pd.DataFrame(stores)
    if len(df) > 0:
        df = geocode_df(df)
    print(f"  → 총 {len(df)}개 매장, 컬럼: {list(df.columns)}")

    # 2. Excel 저장
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, BOX_FILE_NAME)
        df.to_excel(path, index=False)
        print(f"  → Excel 저장: {BOX_FILE_NAME} ({len(df)}행)")

        # 3. Box 토큰 준비
        print("Box 토큰 준비 중...")
        refreshed = False
        if BOX_ACCESS_TOKEN:
            access_token = BOX_ACCESS_TOKEN
            new_refresh_token = BOX_REFRESH_TOKEN
            print("  → access_token 직접 사용")
        else:
            access_token, new_refresh_token = box_refresh_token(BOX_REFRESH_TOKEN)
            refreshed = True

        # 4. Box 업로드 (access_token 만료 시 자동 refresh 후 재시도)
        print("Box 업로드 중...")
        try:
            box_upload(access_token, BOX_FOLDER_ID, BOX_FILE_NAME, path)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("  → access_token 만료, refresh 중...")
                access_token, new_refresh_token = box_refresh_token(BOX_REFRESH_TOKEN)
                refreshed = True
                box_upload(access_token, BOX_FOLDER_ID, BOX_FILE_NAME, path)
            else:
                raise

    # 5. refresh가 발생한 경우 새 토큰을 GitHub secret에 저장
    print("GitHub secret 갱신 중...")
    if refreshed:
        update_github_secret("BOX_ACCESS_TOKEN", access_token)
    update_github_secret("BOX_REFRESH_TOKEN", new_refresh_token)

    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
