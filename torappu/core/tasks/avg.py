import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol, TypedDict, cast

import UnityPy
from UnityPy.classes import (
    MonoBehaviour,
    PPtr,
    Sprite,
    Texture2D,
)
from UnityPy.files.ObjectReader import ObjectReader

from torappu.consts import STORAGE_DIR
from torappu.core.tasks.utils import (
    get_source,
    merge_alpha,
    read_obj,
)
from torappu.models import Diff

from .base import BaseTask

BASE_DIR = STORAGE_DIR.joinpath("asset", "raw", "avg")
CHAR_NAME_REGEX = re.compile(r"^(\d+(?:\$\d+)?)(?:\.png)?$", re.IGNORECASE)
CHAR_CONTAINER_PREFIX = "dyn/avg/characters/"
BG_CONTAINER_PREFIX = "dyn/avg/backgrounds/"
IMAGE_CONTAINER_PREFIX = "dyn/avg/images/"
ITEM_CONTAINER_PREFIX = "dyn/avg/items/"

if TYPE_CHECKING:
    from UnityPy.files.SerializedFile import SerializedFile


class Vector2Json(TypedDict):
    x: float
    y: float


class FaceRectJson(TypedDict):
    x: int
    y: int
    w: int
    h: int


class CharacterGroupJson(TypedDict):
    mode: Literal["face_overlay"]
    base: str
    faceRect: FaceRectJson


class CharacterArrayFaceJson(TypedDict):
    name: str
    alias: str
    group: int
    face: str


class CharacterArraySingleJson(TypedDict):
    name: str
    alias: str
    group: Literal[-1]
    image: str


CharacterArrayJson = CharacterArrayFaceJson | CharacterArraySingleJson


class CharacterDataJson(TypedDict):
    pos: Vector2Json
    size: Vector2Json
    array: list[CharacterArrayJson]
    groups: list[CharacterGroupJson]


class NamedGameObject(Protocol):
    m_Name: str
    m_Components: list[PPtr[object]]


def _vector_component(source: object, key: str) -> float:
    if isinstance(source, dict):
        return float(source.get(key, 0.0))
    if key == "x":
        return float(source.x)  # type: ignore[attr-defined]
    if key == "y":
        return float(source.y)  # type: ignore[attr-defined]
    raise ValueError(f"Unexpected vector component `{key}`")


def _build_pptr(raw: object, assets_file: "SerializedFile") -> PPtr[object]:
    if isinstance(raw, PPtr):
        return raw
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid PPtr source `{type(raw)!r}`")
    return PPtr(
        m_FileID=int(raw.get("m_FileID", 0)),
        m_PathID=int(raw.get("m_PathID", 0)),
        assetsfile=assets_file,
    )


@dataclass(slots=True)
class FloatVector2:
    x: float
    y: float

    @classmethod
    def from_source(cls, data: object) -> "FloatVector2 | None":
        if data is None:
            return None
        return cls(
            x=_vector_component(data, "x"),
            y=_vector_component(data, "y"),
        )

    def to_json(self) -> Vector2Json:
        return {"x": self.x, "y": self.y}


@dataclass(slots=True)
class FaceRect:
    x: int
    y: int
    w: int
    h: int

    def to_json(self) -> FaceRectJson:
        return {"x": self.x, "y": self.y, "w": self.w, "h": self.h}


@dataclass(slots=True)
class CharacterSpriteEntry:
    sprite: PPtr[Sprite]
    alpha_tex: PPtr[Texture2D] | None
    alias: str
    is_whole_body: bool

    @classmethod
    def from_group_data(
        cls, data: object, assets_file: "SerializedFile"
    ) -> "CharacterSpriteEntry | None":
        if not isinstance(data, dict):
            return None

        sprite = data.get("sprite")
        if not isinstance(sprite, dict):
            return None

        alpha_tex = data.get("alphaTex")
        alpha_pptr = None
        if alpha_tex is not None:
            if not isinstance(alpha_tex, dict):
                raise ValueError("Invalid alphaTex in character sprite entry")
            if int(alpha_tex.get("m_PathID", 0)) != 0:
                alpha_pptr = cast(
                    "PPtr[Texture2D]", _build_pptr(alpha_tex, assets_file)
                )

        return cls(
            sprite=cast("PPtr[Sprite]", _build_pptr(sprite, assets_file)),
            alpha_tex=alpha_pptr,
            alias=str(data.get("alias", "")),
            is_whole_body=int(data.get("isWholeBody", 0)) == 1,
        )

    @classmethod
    def from_legacy_object(cls, data: object) -> "CharacterSpriteEntry | None":
        sprite = getattr(data, "sprite", None)
        if not isinstance(sprite, PPtr):
            return None

        alpha_tex = getattr(data, "alphaTex", None)
        alpha_pptr = alpha_tex if alpha_tex and isinstance(alpha_tex, PPtr) else None

        return cls(
            sprite=cast("PPtr[Sprite]", sprite),
            alpha_tex=cast("PPtr[Texture2D] | None", alpha_pptr),
            alias=str(getattr(data, "alias", "")),
            is_whole_body=int(getattr(data, "isWholeBody", 0)) == 1,
        )


@dataclass(slots=True)
class CharacterSpriteGroup:
    sprites: list[CharacterSpriteEntry]
    face_pos: FloatVector2 | None
    face_size: FloatVector2 | None

    @classmethod
    def from_group_data(
        cls, data: object, assets_file: "SerializedFile"
    ) -> "CharacterSpriteGroup | None":
        if not isinstance(data, dict):
            return None

        sprites = data.get("sprites")
        if not isinstance(sprites, list):
            return None

        normalized_sprites: list[CharacterSpriteEntry] = []
        for sprite in sprites:
            normalized_sprite = CharacterSpriteEntry.from_group_data(
                sprite, assets_file
            )
            if normalized_sprite is None:
                raise ValueError("Invalid sprite item in character sprite group")
            normalized_sprites.append(normalized_sprite)

        return cls(
            sprites=normalized_sprites,
            face_pos=FloatVector2.from_source(data.get("facePos")),
            face_size=FloatVector2.from_source(data.get("faceSize")),
        )

    @classmethod
    def from_legacy_object(cls, data: MonoBehaviour) -> "CharacterSpriteGroup | None":
        sprites = getattr(data, "sprites", None)
        if not isinstance(sprites, list):
            return None

        normalized_sprites: list[CharacterSpriteEntry] = []
        for sprite in sprites:
            normalized_sprite = CharacterSpriteEntry.from_legacy_object(sprite)
            if normalized_sprite is None:
                raise ValueError("Invalid legacy sprite item in character sprite group")
            normalized_sprites.append(normalized_sprite)

        return cls(
            sprites=normalized_sprites,
            face_pos=FloatVector2.from_source(getattr(data, "FacePos", None)),
            face_size=FloatVector2.from_source(getattr(data, "FaceSize", None)),
        )


@dataclass(slots=True)
class CharacterRenderSingle:
    base: str


@dataclass(slots=True)
class CharacterRenderFaceOverlay:
    base: str
    face: str
    face_rect: FaceRect


CharacterRender = CharacterRenderSingle | CharacterRenderFaceOverlay


@dataclass(slots=True)
class CharacterLinkItem:
    name: str
    alias: str
    render: CharacterRender


@dataclass(slots=True)
class CharacterLinkData:
    pos: FloatVector2
    size: FloatVector2
    array: list[CharacterLinkItem]


class Task(BaseTask):
    priority: ClassVar[int] = 4
    name = "Avg"

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

    @classmethod
    def _vector2(cls, source: object) -> FloatVector2:
        vector = FloatVector2.from_source(source)
        if vector is None:
            return FloatVector2(x=0.0, y=0.0)
        return vector

    @staticmethod
    def _get_face_rect(group: CharacterSpriteGroup) -> tuple[int, int, int, int]:
        if group.face_pos is None or group.face_size is None:
            return (0, 0, 0, 0)
        x = int(group.face_pos.x)
        y = int(group.face_pos.y)
        w = int(group.face_size.x)
        h = int(group.face_size.y)
        return (x, y, w, h)

    @staticmethod
    def _read_texture(texture_pptr: PPtr[Texture2D] | None) -> Texture2D | None:
        if texture_pptr is None or not texture_pptr:
            return None
        return texture_pptr.deref_parse_as_object()

    def _extract_character_sprite(
        self,
        key: str,
        sprite_pptr: PPtr[Sprite],
        alpha_pptr: PPtr[Texture2D] | None,
        output_dir: Path,
        exported_images: set[str],
    ) -> tuple[str, str]:
        if not sprite_pptr:
            raise ValueError(f"Sprite pointer is empty for `{key}`")
        sprite = sprite_pptr.deref_parse_as_object()

        rgb_texture = sprite.m_RD.texture.read()
        alpha_texture = self._read_texture(alpha_pptr)
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
        group: CharacterSpriteGroup,
        output_dir: Path,
        exported_images: set[str],
    ) -> list[CharacterLinkItem]:
        sprites = group.sprites
        if len(sprites) == 0:
            return []

        face_x, face_y, face_w, face_h = self._get_face_rect(group)
        is_face = face_w > 0 and face_h > 0 and len(sprites) > 1

        last_sprite = sprites[-1]
        base_sprite = last_sprite.sprite
        base_alpha = last_sprite.alpha_tex
        base_image_name: str | None = None
        if is_face and base_sprite:
            base_image_name, _ = self._extract_character_sprite(
                key,
                base_sprite,
                base_alpha,
                output_dir,
                exported_images,
            )
        elif is_face:
            # Some entries contain placeholder rows with m_PathID=0.
            is_face = False

        output: list[CharacterLinkItem] = []
        for item in sprites:
            if not item.sprite:
                continue

            if is_face and (
                item.sprite == base_sprite and item.alpha_tex == base_alpha
            ):
                continue

            image_name, sprite_name = self._extract_character_sprite(
                key,
                item.sprite,
                item.alpha_tex,
                output_dir,
                exported_images,
            )
            item_name = self._normalize_sprite_name(sprite_name)

            if (
                is_face
                and CHAR_NAME_REGEX.match(sprite_name)
                and base_image_name is not None
                and not item.is_whole_body
            ):
                render: CharacterRender = CharacterRenderFaceOverlay(
                    base=base_image_name,
                    face=image_name,
                    face_rect=FaceRect(x=face_x, y=face_y, w=face_w, h=face_h),
                )
            else:
                render = CharacterRenderSingle(base=image_name)

            output.append(
                CharacterLinkItem(name=item_name, alias=item.alias, render=render)
            )
        return output

    @staticmethod
    def _resolve_character_groups(
        behaviour: MonoBehaviour,
        data: dict[str, object],
    ) -> list[CharacterSpriteGroup] | None:
        # Newer avg prefabs store groups directly under `spriteGroups`.
        groups = data.get("spriteGroups")
        if groups is not None:
            if not isinstance(groups, list):
                return None

            normalized_groups: list[CharacterSpriteGroup] = []
            for group in groups:
                normalized = CharacterSpriteGroup.from_group_data(
                    group, behaviour.assets_file
                )
                if normalized is None:
                    raise ValueError("Invalid sprite group type in character prefab")
                normalized_groups.append(normalized)
            return normalized_groups

        # Older prefabs keep a flat `sprites` list plus top-level face metadata.
        legacy_group = CharacterSpriteGroup.from_legacy_object(behaviour)
        return [legacy_group] if legacy_group is not None else None

    def _resolve_character_game_object(
        self,
        behaviour: MonoBehaviour,
        container_path: str,
    ) -> tuple[str, object | None]:
        game_object_name = self._container_filename(container_path)
        game_object: object | None = None

        if behaviour.m_GameObject:
            game_object = behaviour.m_GameObject.deref_parse_as_object()
            resolved_game_object = cast("NamedGameObject", game_object)
            if resolved_game_object.m_Name:
                game_object_name = resolved_game_object.m_Name

        return game_object_name, game_object

    def _build_character_rect_link(
        self,
        key: str,
        game_object: object | None,
    ) -> tuple[FloatVector2, FloatVector2]:
        pos = FloatVector2(x=0.0, y=0.0)
        size = FloatVector2(x=0.0, y=0.0)
        if game_object is None:
            return pos, size

        resolved_game_object = cast("NamedGameObject", game_object)
        if len(resolved_game_object.m_Components) == 0:
            return pos, size

        rect_pptr = resolved_game_object.m_Components[0]
        if not rect_pptr:
            return pos, size

        rect_obj = rect_pptr.deref()
        if rect_obj.type.name != "RectTransform":
            return pos, size

        rect_data = rect_obj.read_typetree()
        if not isinstance(rect_data, dict):
            raise ValueError(f"Invalid RectTransform typetree for character `{key}`")

        rect_pos = self._vector2(rect_data.get("m_AnchoredPosition"))
        if rect_pos.x != 0.0 or rect_pos.y != 0.0:
            pos = rect_pos

        rect_size = self._vector2(rect_data.get("m_SizeDelta"))
        if rect_size.x != 0.0 or rect_size.y != 0.0:
            size = rect_size

        return pos, size

    def _extract_character_mono(
        self,
        mono_obj: ObjectReader[MonoBehaviour],
        container_path: str,
        character_links: dict[str, CharacterDataJson],
    ):
        behaviour = read_obj(MonoBehaviour, mono_obj)
        if behaviour is None:
            return
        data = mono_obj.read_typetree()
        if not isinstance(data, dict):
            return

        groups = self._resolve_character_groups(behaviour, data)
        if groups is None:
            return

        game_object_name, game_object = self._resolve_character_game_object(
            behaviour, container_path
        )
        if game_object_name in character_links:
            raise ValueError(f"Duplicate character key `{game_object_name}`")

        pos, size = self._build_character_rect_link(game_object_name, game_object)
        char_link = CharacterLinkData(pos=pos, size=size, array=[])

        output_dir = BASE_DIR.joinpath("characters")
        exported_images: set[str] = set()
        for group in groups:
            char_link.array.extend(
                self._extract_character_group(
                    game_object_name, group, output_dir, exported_images
                )
            )

        character_links[game_object_name] = self._compact_character_links(
            game_object_name, char_link
        )

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
    def _compact_character_links(
        cls, key: str, character_data: CharacterLinkData
    ) -> CharacterDataJson:
        groups: list[CharacterGroupJson] = []
        group_index_map: dict[str, int] = {}
        compact_array: list[CharacterArrayJson] = []

        for index, item in enumerate(character_data.array):
            render = item.render

            if isinstance(render, CharacterRenderFaceOverlay):
                group_data: CharacterGroupJson = {
                    "mode": "face_overlay",
                    "base": render.base,
                    "faceRect": render.face_rect.to_json(),
                }
                group_key = json.dumps(group_data, ensure_ascii=False, sort_keys=True)
                group_index = group_index_map.get(group_key)
                if group_index is None:
                    group_index = len(groups)
                    groups.append(group_data)
                    group_index_map[group_key] = group_index

                compact_array.append(
                    {
                        "name": item.name,
                        "alias": item.alias,
                        "group": group_index,
                        "face": render.face,
                    }
                )
            elif isinstance(render, CharacterRenderSingle):
                compact_array.append(
                    {
                        "name": item.name,
                        "alias": item.alias,
                        "group": -1,
                        "image": render.base,
                    }
                )
            else:
                raise ValueError(
                    f"Unexpected render type `{type(render)!r}` for `{key}` "
                    f"at index `{index}`"
                )

        return {
            "pos": character_data.pos.to_json(),
            "size": character_data.size.to_json(),
            "groups": groups,
            "array": compact_array,
        }

    async def unpack(
        self, env: UnityPy.Environment, unpacking_source: list[str]
    ) -> dict[str, CharacterDataJson]:
        character_links: dict[str, CharacterDataJson] = {}

        for obj in env.objects:
            source = get_source(obj)
            if source not in unpacking_source:
                continue

            container_path = obj.container
            if container_path is None:
                continue

            if container_path.startswith(CHAR_CONTAINER_PREFIX):
                if obj.type.name == "MonoBehaviour":
                    self._extract_character_mono(obj, container_path, character_links)
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
        resolved_filenames: list[str] = [
            Path(resolved_path).name for resolved_path in resolved_paths
        ]
        env = UnityPy.load(*self.client.anon_paths, *resolved_paths)
        character_links = await self.unpack(env, resolved_filenames)
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
            current_data: dict[str, CharacterDataJson] = {}

        current_data.update(character_links)
        character_link_path.write_text(
            json.dumps(current_data, ensure_ascii=False), encoding="utf-8"
        )
