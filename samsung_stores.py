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
def scrape_stores() -> list[dict]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3.1 Safari/605.1.15"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://www.samsungstore.com/main/main.sesc",
    }

    print("Samsung Store 페이지 가져오는 중...")
    resp = requests.get(SAMSUNG_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    print(f"  → {resp.status_code}, {len(resp.text):,} bytes")

    soup = BeautifulSoup(resp.text, "html.parser")

    # JS 변수에서 배열 추출 (흔한 패턴 순서대로 시도)
    patterns = [
        r'var\s+shopList\s*=\s*(\[[\s\S]*?\])\s*;',
        r'var\s+storeList\s*=\s*(\[[\s\S]*?\])\s*;',
        r'shopList\s*:\s*(\[[\s\S]*?\])',
        r'storeList\s*:\s*(\[[\s\S]*?\])',
        r'JSON\.parse\([\'"](\[[\s\S]*?\])[\'"]\)',
    ]

    for script in soup.find_all("script"):
        if not script.string:
            continue
        text = script.string
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1)
                # JSON.parse 패턴이면 이스케이프 해제
                if "JSON.parse" in pat:
                    raw = raw.encode().decode("unicode_escape")
                try:
                    data = json.loads(raw)
                    if data and isinstance(data[0], dict):
                        print(f"  → JS 변수 발견: {len(data)}개 매장")
                        return data
                except Exception:
                    pass

    # HTML fallback: data-* 속성 또는 li 태그
    stores = []
    for el in soup.find_all(attrs={"data-shopnm": True}):
        stores.append({k.replace("data-", ""): v for k, v in el.attrs.items()})
    if stores:
        print(f"  → HTML data 속성에서 {len(stores)}개 매장 발견")
        return stores

    # 디버그 출력 후 종료
    print("\n[ERROR] 매장 데이터를 찾지 못했습니다. JS 블록 일부:")
    for script in soup.find_all("script"):
        if script.string and len(script.string) > 300:
            print(script.string[:600])
            print("---")
            break
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
