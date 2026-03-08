import json
import re
from pathlib import Path
from typing import Any, ClassVar

import UnityPy
from UnityPy.classes import GameObject, MonoBehaviour, RectTransform, Sprite, Texture2D

from torappu.consts import STORAGE_DIR
from torappu.core.tasks.utils import build_container_path, merge_alpha, read_obj
from torappu.models import Diff

from .base import BaseTask

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "avg")
CHAR_NAME_REGEX = re.compile(r"^(\d+(?:\$\d+)?)(?:\.png)?$", re.IGNORECASE)
CHAR_CONTAINER_PREFIX = "dyn/avg/characters/"
BG_CONTAINER_PREFIX = "dyn/avg/backgrounds/"
IMAGE_CONTAINER_PREFIX = "dyn/avg/images/"
ITEM_CONTAINER_PREFIX = "dyn/avg/items/"


class Task(BaseTask):
    priority: ClassVar[int] = 4
    name = "Avg"

    @staticmethod
    def _pick(data: dict[str, Any], *keys: str):
        for key in keys:
            if key in data:
                return data[key]
        return None

    @staticmethod
    def _container_filename(container_path: str) -> str:
        return Path(container_path).stem

    @staticmethod
    def _normalize_sprite_name(sprite_name: str) -> str:
        if sprite_name.lower().endswith(".png"):
            return sprite_name[: -len(".png")]
        return sprite_name

    @classmethod
    def _build_character_image_key(cls, key: str, sprite_name: str) -> str:
        return f"{key}/{cls._normalize_sprite_name(sprite_name)}"

    @classmethod
    def _build_character_image_filename(cls, sprite_name: str) -> str:
        normalized = cls._normalize_sprite_name(sprite_name)
        return f"{normalized}.png"

    @staticmethod
    def _to_float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _vector2(cls, source: Any) -> dict[str, float]:
        if not isinstance(source, dict):
            return {"x": 0.0, "y": 0.0}
        return {
            "x": cls._to_float(source.get("x", 0.0)),
            "y": cls._to_float(source.get("y", 0.0)),
        }

    @staticmethod
    def _get_face_rect(group: dict[str, Any]) -> tuple[int, int, int, int]:
        face_pos = Task._pick(group, "facePos", "FacePos")
        face_size = Task._pick(group, "faceSize", "FaceSize")
        if not isinstance(face_pos, dict) or not isinstance(face_size, dict):
            return (0, 0, 0, 0)
        x = int(float(face_pos.get("x", 0)))
        y = int(float(face_pos.get("y", 0)))
        w = int(float(face_size.get("x", 0)))
        h = int(float(face_size.get("y", 0)))
        return (x, y, w, h)

    def _read_texture(
        self, object_map: dict[int, Any], texture_path_id: int
    ) -> Texture2D | None:
        if texture_path_id == 0:
            return None
        if (obj := object_map.get(texture_path_id)) is None:
            return None
        return read_obj(Texture2D, obj)

    def _extract_character_sprite(
        self,
        key: str,
        sprite_path_id: int,
        alpha_path_id: int,
        object_map: dict[int, Any],
        output_dir: Path,
        exported_images: set[str],
    ) -> tuple[str, str]:
        obj = object_map.get(sprite_path_id)
        if obj is None:
            raise ValueError(f"Sprite object `{sprite_path_id}` not found for `{key}`")
        sprite = read_obj(Sprite, obj)
        if sprite is None:
            raise ValueError(
                f"Sprite object `{sprite_path_id}` has unexpected class for `{key}`"
            )

        rgb_texture = sprite.m_RD.texture.read()
        alpha_texture = self._read_texture(object_map, alpha_path_id)
        out_image, _ = merge_alpha(alpha_texture, rgb_texture)  # type: ignore

        sprite_name = sprite.m_Name
        image_name = self._build_character_image_key(key, sprite_name)
        if image_name not in exported_images:
            output_path = output_dir.joinpath(
                key, self._build_character_image_filename(sprite_name)
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out_image.save(output_path)
            exported_images.add(image_name)

        return image_name, sprite_name

    def _extract_character_group(
        self,
        key: str,
        group: dict[str, Any],
        object_map: dict[int, Any],
        output_dir: Path,
        exported_images: set[str],
    ) -> list[dict[str, Any]]:
        sprites = self._pick(group, "sprites", "Sprites")
        if not isinstance(sprites, list):
            raise ValueError(f"Invalid sprites data for character `{key}`")
        if len(sprites) == 0:
            return []

        face_x, face_y, face_w, face_h = self._get_face_rect(group)
        is_face = face_w > 0 and face_h > 0 and len(sprites) > 1

        last_sprite = sprites[-1]
        if not isinstance(last_sprite, dict) or not isinstance(
            last_sprite.get("sprite"), dict
        ):
            raise ValueError(f"Invalid base sprite data for character `{key}`")

        base_sprite_path_id = int(last_sprite["sprite"].get("m_PathID", 0))
        base_alpha_path_id = int(last_sprite.get("alphaTex", {}).get("m_PathID", 0))
        base_image_name: str | None = None
        if is_face and base_sprite_path_id != 0:
            base_image_name, _ = self._extract_character_sprite(
                key,
                base_sprite_path_id,
                base_alpha_path_id,
                object_map,
                output_dir,
                exported_images,
            )
        elif is_face:
            # Some entries contain placeholder rows with m_PathID=0.
            is_face = False

        output: list[dict[str, Any]] = []
        for item in sprites:
            if not isinstance(item, dict) or not isinstance(item.get("sprite"), dict):
                raise ValueError(f"Invalid sprite item data for character `{key}`")
            sprite_path_id = int(item["sprite"].get("m_PathID", 0))
            alpha_path_id = int(item.get("alphaTex", {}).get("m_PathID", 0))
            if sprite_path_id == 0:
                continue

            if is_face and (
                sprite_path_id == base_sprite_path_id
                and alpha_path_id == base_alpha_path_id
            ):
                continue

            image_name, sprite_name = self._extract_character_sprite(
                key,
                sprite_path_id,
                alpha_path_id,
                object_map,
                output_dir,
                exported_images,
            )
            link_item: dict[str, Any] = {
                "name": self._normalize_sprite_name(sprite_name),
                "alias": str(item.get("alias", "")),
            }

            is_whole_body = int(item.get("isWholeBody", 0)) == 1
            if (
                is_face
                and CHAR_NAME_REGEX.match(sprite_name)
                and base_image_name is not None
                and not is_whole_body
            ):
                link_item["render"] = {
                    "mode": "face_overlay",
                    "base": base_image_name,
                    "face": image_name,
                    "faceRect": {
                        "x": face_x,
                        "y": face_y,
                        "w": face_w,
                        "h": face_h,
                    },
                }
            else:
                link_item["render"] = {"mode": "single", "base": image_name}

            output.append(link_item)
        return output

    def _resolve_character_game_object(
        self,
        data: dict[str, Any],
        container_path: str,
        object_map: dict[int, Any],
    ) -> tuple[str, GameObject | None]:
        game_object_name = self._container_filename(container_path)
        game_object: GameObject | None = None

        game_object_ptr = data.get("m_GameObject")
        if isinstance(game_object_ptr, dict):
            game_object_path_id = int(game_object_ptr.get("m_PathID", 0))
            if game_object_path_id != 0:
                if (go_obj := object_map.get(game_object_path_id)) is not None:
                    game_object = read_obj(GameObject, go_obj)
                    if game_object is not None and game_object.m_Name:
                        game_object_name = game_object.m_Name

        return game_object_name, game_object

    def _build_character_rect_link(
        self,
        key: str,
        game_object: GameObject | None,
        object_map: dict[int, Any],
    ) -> tuple[dict[str, float], dict[str, float]]:
        pos = {"x": 0.0, "y": 0.0}
        size = {"x": 0.0, "y": 0.0}
        if game_object is None or len(game_object.m_Components) == 0:
            return pos, size

        rect_path_id = int(game_object.m_Components[0].m_PathID)
        if rect_path_id == 0:
            return pos, size

        rect_obj = object_map.get(rect_path_id)
        if rect_obj is None:
            return pos, size
        if read_obj(RectTransform, rect_obj) is None:
            return pos, size

        rect_data = rect_obj.read_typetree()
        if not isinstance(rect_data, dict):
            raise ValueError(f"Invalid RectTransform typetree for character `{key}`")

        rect_pos = self._vector2(rect_data.get("m_AnchoredPosition"))
        if rect_pos["x"] != 0.0 or rect_pos["y"] != 0.0:
            pos = rect_pos

        rect_size = self._vector2(rect_data.get("m_SizeDelta"))
        if rect_size["x"] != 0.0 or rect_size["y"] != 0.0:
            size = rect_size

        return pos, size

    def _extract_character_mono(
        self,
        mono_obj: Any,
        container_path: str,
        object_map: dict[int, Any],
        character_links: dict[str, dict[str, Any]],
    ):
        if read_obj(MonoBehaviour, mono_obj) is None:
            return
        data = mono_obj.read_typetree()
        if not isinstance(data, dict):
            return

        groups = self._pick(data, "spriteGroups", "SpriteGroups")
        if groups is None:
            sprites = data.get("sprites")
            if not isinstance(sprites, list):
                return
            groups = [
                {
                    "sprites": sprites,
                    "faceSize": self._pick(data, "faceSize", "FaceSize"),
                    "facePos": self._pick(data, "facePos", "FacePos"),
                }
            ]
        if not isinstance(groups, list):
            return

        game_object_name, game_object = self._resolve_character_game_object(
            data, container_path, object_map
        )
        if game_object_name in character_links:
            raise ValueError(f"Duplicate character key `{game_object_name}`")

        pos, size = self._build_character_rect_link(
            game_object_name, game_object, object_map
        )
        char_link = {"pos": pos, "size": size, "array": []}

        output_dir = BASE_DIR.joinpath("characters")
        exported_images: set[str] = set()
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(
                    f"Invalid sprite group type for character `{game_object_name}`"
                )
            char_link["array"].extend(
                self._extract_character_group(
                    game_object_name, group, object_map, output_dir, exported_images
                )
            )

        self._compact_character_links(game_object_name, char_link)
        character_links[game_object_name] = char_link

    def _extract_sprite(self, sprite: Sprite, subdir: str, container_path: str):
        file_name = Path(container_path).name
        if file_name == "":
            raise ValueError("Empty container path when extracting avg sprite")
        if not file_name.lower().endswith(".png"):
            file_name = f"{file_name}.png"
        output_path = BASE_DIR.joinpath(subdir, file_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sprite.image.save(output_path)

    @classmethod
    def _compact_character_links(cls, key: str, character_data: dict[str, Any]):
        array_data = character_data.get("array")
        if not isinstance(array_data, list):
            raise ValueError(
                f"Unexpected character array type for `{key}` in character.json"
            )

        groups: list[dict[str, Any]] = []
        group_index_map: dict[str, int] = {}
        compact_array: list[dict[str, Any]] = []

        for index, item in enumerate(array_data):
            if not isinstance(item, dict):
                raise ValueError(
                    "Unexpected character array item type for "
                    f"`{key}` at index `{index}`"
                )
            name = item.get("name")
            if not isinstance(name, str):
                raise ValueError(
                    f"Unexpected character name for `{key}` at index `{index}`"
                )
            alias = str(item.get("alias", ""))

            render = item.get("render")
            if not isinstance(render, dict):
                render = {"mode": "single", "base": name}

            mode = str(render.get("mode", "single"))
            if mode == "face_overlay":
                base = render.get("base")
                face = render.get("face")
                face_rect = render.get("faceRect")
                if not isinstance(base, str):
                    raise ValueError(
                        f"Unexpected face overlay base for `{key}` at index `{index}`"
                    )
                if not isinstance(face, str):
                    raise ValueError(
                        f"Unexpected face overlay face for `{key}` at index `{index}`"
                    )
                if not isinstance(face_rect, dict):
                    raise ValueError(
                        f"Unexpected faceRect for `{key}` at index `{index}`"
                    )
                normalized_face_rect = {
                    "x": int(cls._to_float(face_rect.get("x", 0))),
                    "y": int(cls._to_float(face_rect.get("y", 0))),
                    "w": int(cls._to_float(face_rect.get("w", 0))),
                    "h": int(cls._to_float(face_rect.get("h", 0))),
                }
                group_data = {
                    "mode": "face_overlay",
                    "base": base,
                    "faceRect": normalized_face_rect,
                }
                group_key = json.dumps(group_data, ensure_ascii=False, sort_keys=True)
                group_index = group_index_map.get(group_key)
                if group_index is None:
                    group_index = len(groups)
                    groups.append(group_data)
                    group_index_map[group_key] = group_index

                compact_array.append(
                    {
                        "name": name,
                        "alias": alias,
                        "group": group_index,
                        "face": face,
                    }
                )
            elif mode == "single":
                base = render.get("base")
                if not isinstance(base, str):
                    base = name
                compact_array.append(
                    {
                        "name": name,
                        "alias": alias,
                        "group": -1,
                        "image": base,
                    }
                )
            else:
                raise ValueError(
                    f"Unexpected render mode `{mode}` for `{key}` at index `{index}`"
                )

        character_data["groups"] = groups
        character_data["array"] = compact_array

    async def unpack(self, env) -> dict[str, dict[str, Any]]:
        container_map = build_container_path(env)
        object_map = {obj.path_id: obj for obj in env.objects}
        character_links: dict[str, dict[str, Any]] = {}

        for obj in env.objects:
            container_path = container_map.get(obj.path_id)
            if container_path is None:
                continue

            if container_path.startswith(CHAR_CONTAINER_PREFIX):
                if obj.type.name == "MonoBehaviour":
                    self._extract_character_mono(
                        obj, container_path, object_map, character_links
                    )
                continue

            if container_path.startswith(BG_CONTAINER_PREFIX):
                if texture := read_obj(Sprite, obj):
                    self._extract_sprite(texture, "background", container_path)
                continue

            if container_path.startswith(
                (IMAGE_CONTAINER_PREFIX, ITEM_CONTAINER_PREFIX)
            ):
                if texture := read_obj(Sprite, obj):
                    self._extract_sprite(texture, "images", container_path)
                continue

        return character_links

    def check(self, diff_list: list[Diff]) -> bool:
        diff_set = {diff.path for diff in diff_list}
        self.ab_list = {
            bundle
            for asset, bundle in self.client.asset_to_bundle.items()
            if (
                asset.startswith("avg/characters/")
                or asset.startswith("avg/backgrounds/")
                or asset.startswith("avg/images/")
                or asset.startswith("avg/items/")
            )
            and bundle in diff_set
        }

        return len(self.ab_list) > 0

    async def start(self):
        paths = await self.client.fetch_asset_bundles(list(self.ab_list))
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        resolved_paths = [path[1] for path in paths]
        env = UnityPy.load(*resolved_paths)
        character_links = await self.unpack(env)
        if len(character_links) == 0:
            return

        character_link_path = BASE_DIR.joinpath("character.json")
        if character_link_path.exists():
            current_data = json.loads(character_link_path.read_text(encoding="utf-8"))
            if not isinstance(current_data, dict):
                raise ValueError(
                    f"Unexpected character json format at {character_link_path}"
                )
        else:
            current_data = {}

        current_data.update(character_links)
        character_link_path.write_text(
            json.dumps(current_data, ensure_ascii=False), encoding="utf-8"
        )
