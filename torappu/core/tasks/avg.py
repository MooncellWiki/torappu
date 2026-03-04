import re
from pathlib import Path
from typing import Any, ClassVar

import UnityPy
from PIL import Image
from UnityPy.classes import GameObject, MonoBehaviour, Sprite, Texture2D

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
    def _get_char_name(sprite_name: str, key: str) -> str:
        if match := CHAR_NAME_REGEX.match(sprite_name):
            if key:
                return f"{key}-{match.group(1)}"
            return match.group(1)
        return sprite_name

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

    def _extract_character_group(
        self,
        key: str,
        group: dict[str, Any],
        object_map: dict[int, Any],
        output_dir: Path,
    ):
        sprites = group.get("sprites")
        if not isinstance(sprites, list) or len(sprites) == 0:
            return

        face_x, face_y, face_w, face_h = self._get_face_rect(group)
        is_face = face_w > 0 and face_h > 0 and len(sprites) > 1

        last_sprite = sprites[-1]
        last_sprite_path_id = int(last_sprite["sprite"]["m_PathID"])
        last_alpha_path_id = int(last_sprite["alphaTex"]["m_PathID"])
        face_base: Image.Image | None = None
        if is_face:
            if (last_obj := object_map.get(last_sprite_path_id)) is not None:
                if last_sprite_obj := read_obj(Sprite, last_obj):
                    last_rgb_texture = last_sprite_obj.m_RD.texture.read()
                    last_alpha_texture = self._read_texture(
                        object_map, last_alpha_path_id
                    )
                    face_base, _ = merge_alpha(last_alpha_texture, last_rgb_texture)  # type: ignore

        for item in sprites:
            if not isinstance(item, dict):
                continue
            sprite_path_id = int(item["sprite"]["m_PathID"])
            alpha_path_id = int(item["alphaTex"]["m_PathID"])
            if is_face and (
                sprite_path_id == last_sprite_path_id
                and alpha_path_id == last_alpha_path_id
            ):
                continue

            obj = object_map.get(sprite_path_id)
            if obj is None:
                continue
            if (sprite := read_obj(Sprite, obj)) is None:
                continue

            rgb_texture = sprite.m_RD.texture.read()
            alpha_texture = self._read_texture(object_map, alpha_path_id)
            out_image, _ = merge_alpha(alpha_texture, rgb_texture)  # type: ignore

            sprite_name = sprite.m_Name
            image_name = self._get_char_name(sprite_name, key)
            if (
                is_face
                and CHAR_NAME_REGEX.match(sprite_name)
                and face_base is not None
                and int(item.get("isWholeBody", 0)) != 1
            ):
                face_image = out_image.resize(
                    (face_w, face_h), resample=Image.Resampling.BICUBIC
                )
                out_image = face_base.copy()
                out_image.paste(face_image, (face_x, face_y))

            output_path = output_dir.joinpath(f"{image_name}.png")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            out_image.save(output_path)

    def _extract_character_mono(
        self,
        mono_obj: Any,
        container_path: str,
        object_map: dict[int, Any],
    ):
        if read_obj(MonoBehaviour, mono_obj) is None:
            return
        data = mono_obj.read_typetree()
        if not isinstance(data, dict):
            return

        groups = data.get("spriteGroups")
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

        game_object_ptr = data.get("m_GameObject")
        game_object_name = ""
        game_object_path_id = int(game_object_ptr["m_PathID"])
        if game_object_path_id != 0:
            if (go_obj := object_map.get(game_object_path_id)) is not None:
                if game_object := read_obj(GameObject, go_obj):
                    game_object_name = game_object.m_Name
        if not game_object_name:
            game_object_name = self._container_filename(container_path)

        output_dir = BASE_DIR.joinpath("characters")
        for group in groups:
            if isinstance(group, dict):
                self._extract_character_group(
                    game_object_name, group, object_map, output_dir
                )

    def _extract_sprite(self, sprite: Sprite, subdir: str):
        output_path = BASE_DIR.joinpath(subdir, f"{sprite.m_Name}.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sprite.image.save(output_path)

    async def unpack(self, env):
        container_map = build_container_path(env)
        object_map = {obj.path_id: obj for obj in env.objects}

        for obj in env.objects:
            container_path = container_map.get(obj.path_id)
            if container_path is None:
                continue

            if container_path.startswith(CHAR_CONTAINER_PREFIX):
                if obj.type.name == "MonoBehaviour":
                    self._extract_character_mono(obj, container_path, object_map)
                continue

            if container_path.startswith(BG_CONTAINER_PREFIX):
                if texture := read_obj(Sprite, obj):
                    self._extract_sprite(texture, "background")
                continue

            if container_path.startswith(
                (IMAGE_CONTAINER_PREFIX, ITEM_CONTAINER_PREFIX)
            ):
                if texture := read_obj(Sprite, obj):
                    self._extract_sprite(texture, "images")
                continue

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
        await self.unpack(env)
