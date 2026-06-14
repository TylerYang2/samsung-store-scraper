import os
import shutil
import tempfile
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
        # 임시 파일로 먼저 쓴 뒤 이동 (Box Drive 충돌 방지)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=BOX_SYNC_DIR, suffix='.tmp')
        try:
            os.close(tmp_fd)
            shutil.copy2(src, tmp_path)
            os.replace(tmp_path, dst)
            print(f"  → Box 동기화 완료: {filename}")
        except Exception as e:
            os.unlink(tmp_path)
            raise e

    print(f"\n총 {len(files)}개 파일 Box 업로드 완료 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")


if __name__ == "__main__":
    main()
