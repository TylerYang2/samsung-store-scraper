import os
import shutil
from datetime import datetime

BOX_SYNC_DIR = os.path.expanduser(
    "~/Library/CloudStorage/Box-Box/KR_CSD_BPR/Carrier_POS_List/Carrier File"
)


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
        shutil.copy2(src, dst)
        print(f"  → Box 동기화 완료: {filename}")

    print(f"\n총 {len(files)}개 파일 Box 업로드 완료 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
