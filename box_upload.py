import base64
import json
import os
import sys

import requests
from nacl import encoding, public

BOX_FOLDER_ID     = "387707675849"
BOX_CLIENT_ID     = os.environ.get("BOX_CLIENT_ID", "")
BOX_CLIENT_SECRET = os.environ.get("BOX_CLIENT_SECRET", "")
BOX_REFRESH_TOKEN = os.environ.get("BOX_REFRESH_TOKEN", "")
BOX_ACCESS_TOKEN  = os.environ.get("BOX_ACCESS_TOKEN", "")
GH_PAT            = os.environ.get("GH_PAT", "")
GH_REPO           = os.environ.get("GITHUB_REPOSITORY", "")


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


def update_github_secret(name: str, value: str):
    if not GH_PAT or not GH_REPO:
        return
    headers = {"Authorization": f"token {GH_PAT}",
                "Accept": "application/vnd.github.v3+json"}
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/public-key",
        headers=headers, timeout=10)
    r.raise_for_status()
    key_data = r.json()
    pub_key  = public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
    encrypted = base64.b64encode(public.SealedBox(pub_key).encrypt(value.encode())).decode()
    resp = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/actions/secrets/{name}",
        headers=headers,
        json={"encrypted_value": encrypted, "key_id": key_data["key_id"]},
        timeout=10)
    if resp.status_code in (201, 204):
        print(f"  → GitHub Secret '{name}' 자동 갱신 완료")
    else:
        print(f"  → GitHub Secret '{name}' 갱신 실패 (status {resp.status_code})")


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
    if not BOX_CLIENT_ID:
        print("Box 자격증명 없음, 종료")
        sys.exit(1)

    token         = BOX_ACCESS_TOKEN
    refresh_token = BOX_REFRESH_TOKEN
    refreshed     = False

    if not token:
        token, refresh_token = box_refresh(refresh_token)
        refreshed = True

    output_dir = "output"
    files = [f for f in os.listdir(output_dir) if f.endswith(".xlsx")]
    if not files:
        print("업로드할 파일 없음")
        sys.exit(1)

    for filename in sorted(files):
        filepath = os.path.join(output_dir, filename)
        print(f"  업로드 중: {filename}")
        try:
            box_upload_file(token, BOX_FOLDER_ID, filename, filepath)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("  → access_token 만료, refresh 중...")
                token, refresh_token = box_refresh(refresh_token)
                refreshed = True
                box_upload_file(token, BOX_FOLDER_ID, filename, filepath)
            else:
                raise

    # 새 토큰을 GitHub Secret에 자동 저장
    if refreshed:
        update_github_secret("BOX_ACCESS_TOKEN", token)
        update_github_secret("BOX_REFRESH_TOKEN", refresh_token)

    print(f"\n총 {len(files)}개 파일 Box 업로드 완료")


if __name__ == "__main__":
    main()
