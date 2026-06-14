import os
import sys
from datetime import datetime

import requests

BOX_FOLDER_ID = "387707675849"


def get_box_token() -> str:
    """gbiio로 신선한 Box access_token 발급"""
    try:
        import gbiio
        box_conn = gbiio.connect(store='box')
        return box_conn._oauth._access_token
    except Exception as e:
        print(f"  [WARN] gbiio 토큰 발급 실패: {e}")
        # fallback: 환경변수
        token = os.environ.get("BOX_ACCESS_TOKEN", "")
        if not token:
            print("  [ERROR] Box 토큰 없음")
            sys.exit(1)
        return token


def box_find_file(token: str, folder_id: str, filename: str):
    import json
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
    import json
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
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("output 폴더 없음")
        sys.exit(1)

    files = [f for f in os.listdir(output_dir) if f.endswith(".xlsx")]
    if not files:
        print("업로드할 파일 없음")
        sys.exit(1)

    print("Box 토큰 발급 중...")
    token = get_box_token()

    for filename in sorted(files):
        filepath = os.path.join(output_dir, filename)
        print(f"  업로드 중: {filename}")
        try:
            box_upload_file(token, BOX_FOLDER_ID, filename, filepath)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                print("  → 토큰 만료, 재발급 중...")
                token = get_box_token()
                box_upload_file(token, BOX_FOLDER_ID, filename, filepath)
            else:
                raise

    print(f"\n총 {len(files)}개 파일 Box 업로드 완료")


if __name__ == "__main__":
    main()
