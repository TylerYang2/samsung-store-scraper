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
        page = browser.new_page()

        # 네트워크 응답 인터셉트
        ajax_responses = []

        def handle_response(response):
            if "selectMakeListAjax" in response.url or "shopList" in response.url or "storeList" in response.url:
                try:
                    data = response.json()
                    ajax_responses.append(data)
                except Exception:
                    pass

        page.on("response", handle_response)

        page.goto(SAMSUNG_URL, wait_until="networkidle", timeout=30000)

        # 시도 선택 UI 찾기 - 여러 셀렉터 시도
        sido_selectors = [
            "ul.sido-list li a", "ul.area-list li a", ".sido-wrap li a",
            "ul.tab-list li a", ".region-list li a", "a[data-sido]",
            "ul.shop-tab li a", ".sido li", ".area li a",
        ]

        sido_elements = []
        for sel in sido_selectors:
            els = page.query_selector_all(sel)
            if els:
                print(f"  → 시도 UI 발견: {sel} ({len(els)}개)")
                sido_elements = els
                break

        if sido_elements:
            # 각 시도 클릭하며 데이터 수집
            for el in sido_elements:
                try:
                    text = el.inner_text().strip()
                    print(f"  → 클릭: {text}")
                    ajax_responses.clear()
                    el.click()
                    page.wait_for_timeout(2000)

                    # AJAX 응답이 있으면 파싱
                    for resp_data in ajax_responses:
                        items = _extract_items_from_json(resp_data)
                        stores.extend(items)

                    # AJAX 없으면 DOM 파싱
                    if not ajax_responses:
                        items = _parse_store_dom(page)
                        stores.extend(items)
                except Exception as e:
                    print(f"    [WARN] {e}")
        else:
            # 시도 UI를 못 찾으면 페이지 전체 DOM 파싱 + 디버그 출력
            print("  [WARN] 시도 UI를 찾지 못함, DOM 덤프:")
            for tag in page.query_selector_all("[class]")[:20]:
                cls = tag.get_attribute("class") or ""
                txt = tag.inner_text()[:40].replace("\n", " ")
                print(f"    class='{cls}' text='{txt}'")

            # AJAX 응답으로 시도
            for resp_data in ajax_responses:
                items = _extract_items_from_json(resp_data)
                stores.extend(items)

            if not stores:
                items = _parse_store_dom(page)
                stores.extend(items)

        browser.close()

    print(f"  → 총 {len(stores)}개 매장 수집")
    return stores


def _extract_items_from_json(data) -> list[dict]:
    """JSON 응답에서 매장 목록 추출"""
    items = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("list", "data", "shopList", "storeList", "result"):
            if isinstance(data.get(key), list):
                items = data[key]
                break

    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        store = {
            "name": item.get("shopNm") or item.get("storeName") or item.get("name") or item.get("shopName") or "",
            "address": item.get("addr") or item.get("address") or item.get("shopAddr") or "",
            "tel": item.get("tel") or item.get("phone") or item.get("telNo") or "",
        }
        if store["name"]:
            result.append(store)
    return result


def _parse_store_dom(page) -> list[dict]:
    """DOM에서 직접 매장 정보 파싱"""
    stores = []
    selectors = [
        "ul.store-list li", ".store-list li", "ul.shop-list li",
        ".shop-list li", ".store-item", ".shop-item",
    ]
    for sel in selectors:
        els = page.query_selector_all(sel)
        if els:
            for el in els:
                name_el = el.query_selector(".store-name, .shop-name, strong, h3, h4, .name")
                addr_el = el.query_selector(".address, .addr, .store-addr")
                tel_el = el.query_selector(".tel, .phone, .contact")
                name = name_el.inner_text().strip() if name_el else el.inner_text()[:30].strip()
                addr = addr_el.inner_text().strip() if addr_el else ""
                tel = tel_el.inner_text().strip() if tel_el else ""
                if name:
                    stores.append({"name": name, "address": addr, "tel": tel})
            break
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
