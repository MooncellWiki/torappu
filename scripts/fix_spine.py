import json

from torappu.consts import STORAGE_DIR

BASE_DIR = STORAGE_DIR / "asset" / "raw" / "char_spine"


def check(file_path: str):
    skel_path = (dir / file_path).with_suffix(".skel")
    if not skel_path.is_file():
        print(f"Missing file: {skel_path}")
    atlas_path = (dir / file_path).with_suffix(".atlas")
    if atlas_path.is_file():
        try:
            with open(atlas_path, encoding="utf-8") as atlas_file:
                lines = atlas_file.readlines()
                if len(lines) >= 2:
                    img_path = (dir / file_path).parent / lines[1].strip()
                    if not img_path.is_file():
                        print(f"Missing image file: {img_path}")
                else:
                    print(f"Atlas file has fewer than 2 lines: {atlas_path}")
        except Exception as e:
            print(f"Error reading atlas file {atlas_path}: {e}")
    else:
        print(f"Missing file: {atlas_path}")


for dir in BASE_DIR.iterdir():
    if dir.is_dir():
        meta_path = dir / "meta.json"
        if not meta_path.is_file():
            print(f"Missing file: {meta_path}")
            continue
        with open(meta_path) as file:
            meta = json.loads(file.read())
            # Iterate through skin types (e.g., "默认", "拭刀")
            for skin_name, skin_poses in meta.get("skin", {}).items():
                # Iterate through pose types (e.g., "正面", "背面", "基建")
                for pose_name, pose_data in skin_poses.items():
                    file_path: str = pose_data.get("file", "")
                    check(file_path)
