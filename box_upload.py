import os
import shutil
import time
from datetime import datetime

BOX_SYNC_DIR = os.path.expanduser(
    "~/Library/CloudStorage/Box-Box/KR_CSD_BPR/Carrier_POS_List/Carrier File"
)


def copy_to_box(src: str, dst: str, max_retries: int = 5):
    """Box Drive 충돌 대비 retry + /tmp 경유 복사"""
    for attempt in range(max_retries):
        try:
            tmp = f"/tmp/{os.path.basename(dst)}"
            shutil.copy2(src, tmp)
            shutil.copy2(tmp, dst)
            os.unlink(tmp)
            return
        except OSError as e:
            if attempt < max_retries - 1:
                print(f"    [재시도 {attempt+1}/{max_retries}] {e}")
                time.sleep(5)
            else:
                raise


def main():
    output_dir = "output"
    if not os.path.exists(output_dir):
        print("output 폴더 없음")
        return

    files = [f for f in os.listdir(output_dir) if f.endswith(".xlsx")]
    if not files:
        print("업로드할 파일 없음")
        return

    if not os.path.exists(BOX_SYNC_DIR):
        print(f"[ERROR] Box 동기화 폴더 없음: {BOX_SYNC_DIR}")
        return

    for filename in sorted(files):
        src = os.path.join(output_dir, filename)
        dst = os.path.join(BOX_SYNC_DIR, filename)
        print(f"  업로드 중: {filename}")
        copy_to_box(src, dst)
        print(f"  → Box 동기화 완료: {filename}")

    print(f"\n총 {len(files)}개 파일 Box 업로드 완료 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
