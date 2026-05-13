import os
import re
import json
import sys
import base64
import tempfile
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import pandas as pd
from nacl import encoding, public

# ── 설정 ──────────────────────────────────────────────
SAMSUNG_URL = "https://www.samsungstore.com/shop/selectFindShopMain.sesc?menu=w401"
BOX_FOLDER_ID = "381592399197"
BOX_FILE_NAME = "Samsung_Stores.xlsx"

BOX_CLIENT_ID     = os.environ["BOX_CLIENT_ID"]
BOX_CLIENT_SECRET = os.environ["BOX_CLIENT_SECRET"]
BOX_REFRESH_TOKEN = os.environ["BOX_REFRESH_TOKEN"]
GH_PAT            = os.environ.get("GH_PAT", "")
GH_REPO           = os.environ.get("GITHUB_REPOSITORY", "")  # owner/repo


# ── 1. 스크래핑 ───────────────────────────────────────
BASE_URL = "https://www.samsungstore.com"

# 한국 시도 코드 (사이트 공통 패턴)
SIDO_LIST = [
    "서울", "경기", "인천", "부산", "대구", "대전",
    "광주", "울산", "강원", "충북", "충남", "경북",
    "경남", "전북", "전남", "제주", "세종",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3.1 Safari/605.1.15"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": SAMSUNG_URL,
    "X-Requested-With": "XMLHttpRequest",
}


def find_ajax_endpoint(soup: BeautifulSoup, session: requests.Session) -> str | None:
    """인라인/외부 JS에서 매장 목록 AJAX 엔드포인트 탐색"""
    ajax_patterns = [
        r'["\']([^"\']*(?:shopList|storeList|findShop|shopSearch)[^"\']*\.sesc)["\']',
        r'url\s*:\s*["\']([^"\']+\.sesc)["\']',
        r'ajax\(["\']([^"\']+\.sesc)["\']',
    ]

    all_js = [s.string for s in soup.find_all("script") if s.string]

    # 외부 JS 파일도 다운로드해서 탐색
    for tag in soup.find_all("script", src=True):
        src = tag["src"]
        if "samsungstore.com" in src or src.startswith("/"):
            url = src if src.startswith("http") else BASE_URL + src
            try:
                r = session.get(url, timeout=10)
                all_js.append(r.text)
            except Exception:
                pass

    for js in all_js:
        for pat in ajax_patterns:
            m = re.search(pat, js)
            if m:
                path = m.group(1)
                endpoint = path if path.startswith("http") else BASE_URL + "/" + path.lstrip("/")
                print(f"  → AJAX 엔드포인트 발견: {endpoint}")
                return endpoint

    return None


def find_ajax_params(soup: BeautifulSoup, session: requests.Session, endpoint: str) -> dict:
    """JS에서 엔드포인트에 전달되는 파라미터 추출"""
    endpoint_path = endpoint.split("samsungstore.com")[-1].lstrip("/")
    all_js = [s.string for s in soup.find_all("script") if s.string]
    for tag in soup.find_all("script", src=True):
        src = tag["src"]
        if "samsungstore.com" in src or src.startswith("/"):
            url = src if src.startswith("http") else BASE_URL + src
            try:
                r = session.get(url, timeout=10)
                all_js.append(r.text)
            except Exception:
                pass

    for js in all_js:
        idx = js.find(endpoint_path)
        if idx == -1:
            idx = js.find("selectMakeListAjax")
        if idx != -1:
            ctx = js[max(0, idx-800):idx+400]
            print(f"\n[DEBUG] 엔드포인트 주변 JS:\n{ctx}\n")
            # data: { ... } 파턴 추출
            m = re.search(r'data\s*:\s*\{([^}]+)\}', ctx)
            if m:
                print(f"[DEBUG] data 파라미터: {m.group(1)}")
            break
    return {}


def fetch_stores_by_sido(session: requests.Session, endpoint: str, sido: str, debug: bool = False) -> list[dict]:
    """시도별 매장 목록 AJAX 호출"""
    payloads = [
        {"sidoCd": sido, "menu": "w401"},
        {"sido": sido, "menu": "w401"},
        {"areaCd": sido, "menu": "w401"},
        {"sidoNm": sido, "menu": "w401"},
        {"sido": sido, "gubun": "sido"},
        {"searchType": "sido", "searchWord": sido},
    ]
    for data in payloads:
        for method in ["post", "get"]:
            try:
                fn = session.post if method == "post" else session.get
                kwargs = {"data": data} if method == "post" else {"params": data}
                r = fn(endpoint, headers=HEADERS, timeout=15, **kwargs)
                if r.status_code == 200 and r.text.strip():
                    if debug:
                        print(f"  [DEBUG] {method.upper()} {data} → {r.text[:300]}")
                    try:
                        result = r.json()
                        items = result if isinstance(result, list) else (
                            result.get("list") or result.get("data") or
                            result.get("shopList") or result.get("storeList") or []
                        )
                        if items:
                            return [dict(item, sido=sido) for item in items]
                    except Exception:
                        pass
            except Exception:
                pass
    return []


def scrape_stores() -> list[dict]:
    session = requests.Session()

    print("Samsung Store 페이지 가져오는 중...")
    resp = session.get(SAMSUNG_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    print(f"  → {resp.status_code}, {len(resp.text):,} bytes")

    soup = BeautifulSoup(resp.text, "html.parser")

    stores = []

    # 방법 1: store-list 안의 li 항목 파싱
    store_list = soup.select("ul.store-list li, .store-list li, ul.shop-list li")
    if store_list:
        print(f"  → store-list li: {len(store_list)}개 발견")
        for li in store_list:
            name = (li.select_one(".store-name, .shop-name, h3, h4, .name, strong") or li).get_text(strip=True)
            addr = (li.select_one(".address, .addr, .store-addr") or li.find(string=re.compile(r"서울|경기|부산|대구|인천|광주|대전|울산|강원|충|경|전|제주|세종"))).strip() if li.find(string=re.compile(r"서울|경기|부산|대구|인천|광주|대전|울산|강원|충|경|전|제주|세종")) else ""
            tel = (li.select_one(".tel, .phone, .contact") or {}).get_text(strip=True) if li.select_one(".tel, .phone, .contact") else ""
            stores.append({"name": name, "address": addr, "tel": tel})
        return stores

    # 방법 2: JS 변수 내 HTML 문자열 파싱
    # 방법 3: data-* 속성으로 렌더된 항목
    for el in soup.find_all(attrs={"data-shopnm": True}):
        stores.append({k.replace("data-", ""): v for k, v in el.attrs.items()})
    if stores:
        print(f"  → data-shopnm 속성: {len(stores)}개")
        return stores

    # 방법 4: 텍스트에서 매장명 패턴 (삼성스토어 + 주소)
    for el in soup.find_all(string=re.compile(r"삼성스토어")):
        parent = el.parent
        text = parent.get_text(" ", strip=True)
        if len(text) > 5:
            stores.append({"raw": text})
    if stores:
        print(f"  → 텍스트 패턴: {len(stores)}개")
        return stores

    # 모두 실패 시 HTML 구조 출력
    print("\n[ERROR] 매장 데이터를 찾지 못했습니다.")
    print("[DEBUG] .store-list 존재 여부:", bool(soup.select(".store-list")))
    print("[DEBUG] 전체 class 목록 샘플:")
    for tag in soup.find_all(class_=True)[:30]:
        print(f"  <{tag.name} class='{' '.join(tag.get('class', []))}'> {tag.get_text(strip=True)[:50]}")
    sys.exit(1)


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
    resp.raise_for_status()
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
    resp.raise_for_status()
    print(f"  → GitHub secret '{secret_name}' 갱신 완료")


# ── 메인 ──────────────────────────────────────────────
def main():
    # 1. 스크래핑
    stores = scrape_stores()
    df = pd.DataFrame(stores)
    print(f"  → 총 {len(df)}개 매장, 컬럼: {list(df.columns)}")

    # 2. Excel 저장
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, BOX_FILE_NAME)
        df.to_excel(path, index=False)
        print(f"  → Excel 저장: {BOX_FILE_NAME} ({len(df)}행)")

        # 3. Box 토큰 갱신
        print("Box 토큰 갱신 중...")
        access_token, new_refresh_token = box_refresh_token(BOX_REFRESH_TOKEN)

        # 4. Box 업로드
        print("Box 업로드 중...")
        box_upload(access_token, BOX_FOLDER_ID, BOX_FILE_NAME, path)

    # 5. 새 refresh_token을 GitHub secret에 저장
    print("GitHub secret 갱신 중...")
    update_github_secret("BOX_REFRESH_TOKEN", new_refresh_token)

    print(f"\n완료! ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
