import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar, TypedDict

from torappu.consts import GAMEDATA_DIR, STORAGE_DIR
from torappu.core.utils.thread import run_sync
from torappu.log import logger
from torappu.models import Diff

from .base import BaseTask

OUTPUT_PATH = STORAGE_DIR / "asset" / "raw" / "story_index.json"


class StoryReference(TypedDict):
    type: str
    link: str
    name: str


class StoryScript(TypedDict):
    path: str
    references: list[StoryReference]


class StoryIndex(TypedDict):
    schemaVersion: int
    resVersion: str
    scripts: list[StoryScript]


def _object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _objects(value: object) -> Iterator[tuple[str, dict[str, object]]]:
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if isinstance(key, str) and isinstance(item, dict):
            yield key, item


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _record_value(record: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        if value := _string(record.get(key)):
            return value
    return None


def _path_name(value: str) -> str:
    return value.replace("\\", "/").removesuffix(".txt").rsplit("/", 1)[-1]


def _join_name(*parts: str | None) -> str:
    return "·".join(part for part in parts if part)


def _walk_story_paths(
    value: object,
    catalog: "StoryCatalog",
) -> Iterator[tuple[str, str, dict[str, object]]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and isinstance(child, str):
                if path := catalog.resolve(child):
                    yield path, key, value
            yield from _walk_story_paths(child, catalog)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_story_paths(child, catalog)


class StoryCatalog:
    def __init__(self, story_dir: Path) -> None:
        if not story_dir.is_dir():
            raise FileNotFoundError(f"story directory does not exist: {story_dir}")

        self.paths = sorted(
            path.relative_to(story_dir).with_suffix("").as_posix()
            for path in story_dir.rglob("*.txt")
        )
        self.references: dict[str, list[StoryReference]] = {
            path: [] for path in self.paths
        }
        self._seen: dict[str, set[tuple[str, str]]] = {
            path: set() for path in self.paths
        }
        self._casefold_paths: dict[str, str] = {}
        for path in self.paths:
            normalized = path.casefold()
            previous = self._casefold_paths.setdefault(normalized, path)
            if previous != path:
                raise RuntimeError(
                    f"story paths differ only by case: {previous!r} and {path!r}"
                )

    def resolve(self, raw_path: object) -> str | None:
        value = _string(raw_path)
        if value is None:
            return None

        value = value.replace("\\", "/")
        if value.casefold().endswith(".txt"):
            value = value[:-4]

        lowered = value.casefold()
        for prefix in ("dyn/gamedata/story/", "story/"):
            if lowered.startswith(prefix):
                value = value[len(prefix) :]
                lowered = value.casefold()
                break

        # storyInfo and breifPath use info/*, while the unpacked TextAssets live
        # under story/[uc]info/*. They are independent scripts in the index.
        if lowered.startswith("info/"):
            value = f"[uc]{value}"
            lowered = value.casefold()

        return self._casefold_paths.get(lowered)

    def add(self, raw_path: object, reference: StoryReference) -> bool:
        path = self.resolve(raw_path)
        if path is None:
            return False

        key = (reference["type"], reference["link"])
        if key in self._seen[path]:
            return False

        self._seen[path].add(key)
        self.references[path].append(reference)
        return True

    def has_reference_types(self, path: str, types: set[str]) -> bool:
        return any(reference["type"] in types for reference in self.references[path])

    def scripts(self) -> list[StoryScript]:
        return [
            {"path": path, "references": self.references[path]} for path in self.paths
        ]


class StoryIndexBuilder:
    def __init__(self, gamedata_dir: Path, res_version: str) -> None:
        self.gamedata_dir = gamedata_dir
        self.excel_dir = gamedata_dir / "excel"
        self.res_version = res_version
        self.catalog = StoryCatalog(gamedata_dir / "story")

    def _load_table(self, name: str) -> dict[str, object]:
        path = self.excel_dir / name
        if not path.exists():
            logger.warning(f"StoryIndex source table does not exist: {path}")
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(
                f"failed to read StoryIndex source table {path}"
            ) from exc
        if not isinstance(value, dict):
            raise TypeError(f"StoryIndex source table must be an object: {path}")
        return value

    def _add_story_review(self, table: dict[str, object]) -> None:
        count = 0
        for group_id, group in _objects(table):
            act_type = _string(group.get("actType"))
            entry_type = _string(group.get("entryType"))
            if act_type == "NONE" and entry_type == "NONE":
                continue

            reference_type = (
                "main-story"
                if act_type == "MAIN_STORY" or group_id.startswith("main_")
                else "side-story"
            )
            group_name = _string(group.get("name"))
            stories = group.get("infoUnlockDatas")
            if not isinstance(stories, list):
                continue

            for raw_story in stories:
                story = _object(raw_story)
                if story.get("storyCanShow") == -1:
                    continue
                story_id = _string(story.get("storyId"))
                story_name = _string(story.get("storyName"))
                if story_id is None or story_name is None:
                    continue

                code = _string(story.get("storyCode"))
                if story.get("storyReviewType") == "SP":
                    name = story_name
                elif code:
                    name = f"{code} {story_name}"
                    avg_tag = _string(story.get("avgTag"))
                    if avg_tag and avg_tag != "幕间":
                        name = _join_name(name, avg_tag)
                else:
                    name = _join_name(group_name, story_name)

                variation = _object(story.get("storyVariation"))
                name = _join_name(name, _string(variation.get("name")))
                reference: StoryReference = {
                    "type": reference_type,
                    "link": f"story/{story_id}",
                    "name": name,
                }
                for source_key in ("storyTxt", "storyInfo"):
                    count += self.catalog.add(story.get(source_key), reference)
        logger.debug(f"StoryIndex story_review_table references: {count}")

    def _add_operator_memories(
        self,
        handbook_table: dict[str, object],
        character_table: dict[str, object],
        story_table: dict[str, object],
    ) -> None:
        count = 0
        story_configs = {key.casefold(): value for key, value in story_table.items()}
        handbook = _object(handbook_table.get("handbookDict"))
        for handbook_char_id, raw_handbook in handbook.items():
            handbook_entry = _object(raw_handbook)
            memories = handbook_entry.get("handbookAvgList")
            if not isinstance(memories, list):
                continue

            for raw_memory in memories:
                memory = _object(raw_memory)
                set_id = _string(memory.get("storySetId"))
                set_name = _string(memory.get("storySetName"))
                char_id = _string(memory.get("charId")) or handbook_char_id
                if set_id is None or set_name is None:
                    continue

                char = _object(character_table.get(char_id))
                char_name = _string(char.get("name")) or char_id
                link_id = set_id.replace("_set_", "_", 1)
                reference: StoryReference = {
                    "type": "operator-memory",
                    "link": f"operator/{char_id}/memory/{link_id}",
                    "name": f"{char_name}干员密录·{set_name}",
                }

                stories = memory.get("avgList")
                if not isinstance(stories, list):
                    continue
                for raw_story in stories:
                    story = _object(raw_story)
                    story_txt = _string(story.get("storyTxt"))
                    config = _object(story_configs.get((story_txt or "").casefold()))
                    if config.get("disabled") is True:
                        continue
                    for source_key in ("storyTxt", "storyInfo"):
                        count += self.catalog.add(story.get(source_key), reference)
        logger.debug(f"StoryIndex operator-memory references: {count}")

    def _add_sandbox(self, table: dict[str, object]) -> None:
        count = 0
        basic_info = _object(table.get("basicInfo"))
        detail = _object(table.get("detail"))
        for raw_template in detail.values():
            for topic_id, topic_detail in _objects(raw_template):
                topic = _object(basic_info.get(topic_id))
                topic_name = _string(topic.get("topicName")) or topic_id
                for path, _, record in _walk_story_paths(topic_detail, self.catalog):
                    entry_id = _record_value(
                        record,
                        "dialogId",
                        "questId",
                        "storyKey",
                        "eventId",
                        "storyId",
                        "avgId",
                        "id",
                    ) or _path_name(path)
                    if "/" in entry_id or "\\" in entry_id:
                        entry_id = _path_name(entry_id)
                    label = (
                        _record_value(
                            record,
                            "storyName",
                            "name",
                            "title",
                            "questName",
                            "dialogId",
                            "questId",
                        )
                        or entry_id
                    )
                    reference: StoryReference = {
                        "type": "reclamation-algorithm",
                        "link": f"sandbox/{topic_id}/{entry_id}",
                        "name": _join_name(topic_name, label),
                    }
                    count += self.catalog.add(path, reference)
        logger.debug(f"StoryIndex sandbox references: {count}")

    @staticmethod
    def _rogue_ending_number(value: str) -> str | None:
        match = re.search(r"(?:ending|endbook)_\d*_*([0-9]+)(?:_|$)", value)
        return match.group(1) if match else None

    def _add_roguelike(self, table: dict[str, object]) -> None:
        count = 0
        topics = _object(table.get("topics"))
        details = _object(table.get("details"))
        for topic_id, raw_detail in _objects(details):
            topic = _object(topics.get(topic_id))
            topic_name = _string(topic.get("name")) or topic_id

            month_squads = {
                chat_id: squad
                for _, squad in _objects(raw_detail.get("monthSquad"))
                if (chat_id := _string(squad.get("chatId")))
            }
            endings = list(_objects(raw_detail.get("endings")))
            endings_by_number: dict[str, tuple[str, dict[str, object]]] = {}
            for ending_key, ending in endings:
                ending_id = _string(ending.get("id")) or ending_key
                number = self._rogue_ending_number(ending_id)
                if number:
                    endings_by_number[number] = (ending_id, ending)

            for path, field, record in _walk_story_paths(raw_detail, self.catalog):
                link: str
                label: str
                if field == "chatStoryId":
                    chat_id = re.sub(r"_[0-9]+$", "", _path_name(path))
                    squad = month_squads.get(chat_id, {})
                    squad_id = _string(squad.get("id")) or chat_id
                    label = _string(squad.get("teamName")) or chat_id
                    link = f"roguelike/{topic_id}/monthly-squad/{squad_id}"
                    label = _join_name(topic_name, "月度小队", label)
                elif field == "avgId":
                    ending_id = _string(record.get("endingId"))
                    ending = {}
                    if ending_id:
                        ending = next(
                            (
                                value
                                for key, value in endings
                                if key == ending_id
                                or _string(value.get("id")) == ending_id
                            ),
                            {},
                        )
                    else:
                        number = self._rogue_ending_number(path)
                        if number and number in endings_by_number:
                            ending_id, ending = endings_by_number[number]
                    ending_id = ending_id or _path_name(path)
                    ending_name = (
                        _string(ending.get("name"))
                        or _string(record.get("title"))
                        or ending_id
                    )
                    link = f"roguelike/{topic_id}/ending/{ending_id}"
                    label = _join_name(topic_name, "结局", ending_name)
                elif field == "textId":
                    entry_id = _string(record.get("endBookId")) or _path_name(path)
                    link = f"roguelike/{topic_id}/archive/{entry_id}"
                    label = _join_name(
                        topic_name,
                        "结局档案",
                        _string(record.get("endbookName")) or entry_id,
                    )
                else:
                    entry_id = _record_value(
                        record,
                        "storyId",
                        "challengeStoryId",
                        "id",
                        "endBookId",
                    ) or _path_name(path)
                    link = f"roguelike/{topic_id}/archive/{entry_id}"
                    label = _join_name(
                        topic_name,
                        _record_value(
                            record,
                            "storyName",
                            "challengeName",
                            "title",
                            "endbookName",
                        )
                        or entry_id,
                    )
                reference: StoryReference = {
                    "type": "integrated-strategies",
                    "link": link,
                    "name": label,
                }
                count += self.catalog.add(path, reference)

            for challenge_id, challenge in _objects(raw_detail.get("challenges")):
                sort_id = challenge.get("sortId")
                if not isinstance(sort_id, int):
                    continue
                challenge_story_id = (
                    _string(challenge.get("challengeStoryId")) or challenge_id
                )
                reference = {
                    "type": "integrated-strategies",
                    "link": f"roguelike/{topic_id}/challenge/{challenge_story_id}",
                    "name": _join_name(
                        topic_name,
                        "深入调查",
                        _string(challenge.get("challengeName")) or challenge_id,
                    ),
                }
                story_path = (
                    f"obt/rogue/{topic_id}/challenge/challenge_{topic_id}_1_{sort_id}"
                )
                count += self.catalog.add(story_path, reference)
        logger.debug(f"StoryIndex roguelike references: {count}")

    @staticmethod
    def _activity_id(path: str) -> str | None:
        match = re.search(r"(?:^|/)activities/([^/]+)", path.casefold())
        return match.group(1) if match else None

    def _activity_name(
        self, activity_id: str | None, basic_info: dict[str, object]
    ) -> str | None:
        if activity_id is None:
            return None
        return _string(_object(basic_info.get(activity_id)).get("name")) or activity_id

    def _add_activity(self, table: dict[str, object]) -> None:
        count = 0
        basic_info = _object(table.get("basicInfo"))
        for path, field, record in _walk_story_paths(table, self.catalog):
            if self.catalog.has_reference_types(path, {"main-story", "side-story"}):
                continue

            activity_id = self._activity_id(path)
            activity_name = self._activity_name(activity_id, basic_info)
            entry_id = _record_value(
                record,
                "storyKey",
                "taskId",
                "optionId",
                "cardId",
                "storyId",
                "id",
            ) or _path_name(path)
            if "/" in entry_id or "\\" in entry_id:
                entry_id = _path_name(entry_id)

            label = (
                _record_value(
                    record,
                    "storyName",
                    "titleName",
                    "cardName",
                    "optionDesc",
                    "taskId",
                )
                or entry_id
            )
            story_sort = _string(record.get("storySort"))
            if story_sort:
                label = f"{story_sort} {label}"

            is_story_entry = field in {"storyId", "storyInfo"} and bool(
                record.get("storyName")
            )
            reference: StoryReference = {
                "type": "side-story" if is_story_entry else "activity-story",
                "link": (
                    f"story/{entry_id}"
                    if is_story_entry
                    else f"activity/{activity_id or 'unknown'}/{entry_id}"
                ),
                "name": _join_name(activity_name, label),
            }
            count += self.catalog.add(path, reference)
        logger.debug(f"StoryIndex activity references: {count}")

    def _add_zone_records(self, table: dict[str, object]) -> None:
        count = 0
        zones = _object(table.get("zones"))
        for path, field, record in _walk_story_paths(table, self.catalog):
            if field not in {"recapId", "textPath"}:
                continue

            if field == "recapId":
                zone_id = _string(record.get("zoneId"))
                suffix = _string(record.get("buttonName")) or "章节回顾"
                entry_id = "recap"
            else:
                parts = path.casefold().split("/")
                zone_id = parts[2] if len(parts) > 2 and parts[1] == "record" else None
                suffix = _join_name(
                    "章节记录",
                    _string(record.get("bindStageId")) or _path_name(path),
                )
                entry_id = _path_name(path)

            zone = _object(zones.get(zone_id or ""))
            zone_name = " ".join(
                filter(
                    None,
                    (
                        _string(zone.get("zoneNameFirst")),
                        _string(zone.get("zoneNameSecond")),
                    ),
                )
            )
            reference: StoryReference = {
                "type": "main-story",
                "link": f"story/{zone_id or 'unknown'}/{entry_id}",
                "name": _join_name(zone_name or zone_id, suffix),
            }
            count += self.catalog.add(path, reference)
        logger.debug(f"StoryIndex zone record references: {count}")

    def _add_story_review_meta(
        self,
        table: dict[str, object],
        activity_table: dict[str, object],
        roguelike_table: dict[str, object],
    ) -> None:
        count = 0
        activity_info = _object(activity_table.get("basicInfo"))
        rogue_topics = _object(roguelike_table.get("topics"))
        resources = _object(table.get("actArchiveResData"))
        for path, _, record in _walk_story_paths(resources, self.catalog):
            entry_id = _record_value(record, "storyId", "id") or _path_name(path)
            label = (
                _record_value(record, "storyName", "titleName", "desc", "title")
                or entry_id
            )

            rogue_match = re.search(r"/(ro[0-9]+)/", path.casefold())
            if rogue_match:
                rogue_number = rogue_match.group(1)[2:]
                topic_id = f"rogue_{rogue_number}"
                topic = _object(rogue_topics.get(topic_id))
                reference_type = "integrated-strategies"
                link = f"roguelike/{topic_id}/archive/{entry_id}"
                group_name = _string(topic.get("name")) or topic_id
            else:
                activity_id = self._activity_id(path)
                reference_type = "activity-story"
                link = f"story/{entry_id}"
                group_name = self._activity_name(activity_id, activity_info)

            reference: StoryReference = {
                "type": reference_type,
                "link": link,
                "name": _join_name(group_name, label),
            }
            count += self.catalog.add(path, reference)
        logger.debug(f"StoryIndex story_review_meta references: {count}")

    @staticmethod
    def _normalize_level_id(value: str) -> str:
        value = value.replace("\\", "/").casefold()
        return value.removeprefix("levels/").removesuffix(".json")

    def _stage_by_level(
        self, stage_table: dict[str, object]
    ) -> dict[str, list[dict[str, object]]]:
        result: dict[str, list[dict[str, object]]] = {}
        for _, stage in _objects(stage_table.get("stages")):
            level_id = _string(stage.get("levelId"))
            if level_id is None:
                continue
            result.setdefault(self._normalize_level_id(level_id), []).append(stage)
        return result

    def _story_actions(self, value: object) -> Iterator[str]:
        if isinstance(value, dict):
            if value.get("actionType") == "STORY":
                if story_path := _string(value.get("key")):
                    yield story_path
            for child in value.values():
                yield from self._story_actions(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._story_actions(child)

    def _add_levels(
        self,
        stage_table: dict[str, object],
        sandbox_table: dict[str, object],
        roguelike_table: dict[str, object],
    ) -> None:
        count = 0
        stages_by_level = self._stage_by_level(stage_table)
        sandbox_info = _object(sandbox_table.get("basicInfo"))
        rogue_topics = _object(roguelike_table.get("topics"))
        levels_dir = self.gamedata_dir / "levels"
        if not levels_dir.is_dir():
            logger.warning(f"StoryIndex levels directory does not exist: {levels_dir}")
            return

        for level_path in levels_dir.rglob("*.json"):
            try:
                level = json.loads(level_path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"failed to read level data {level_path}") from exc

            relative_level = level_path.relative_to(levels_dir).with_suffix("")
            level_id = self._normalize_level_id(relative_level.as_posix())
            stages = stages_by_level.get(level_id, [])
            for story_path in self._story_actions(level):
                canonical_path = self.catalog.resolve(story_path)
                if canonical_path is None:
                    continue

                if stages:
                    for stage in stages:
                        stage_id = _string(stage.get("stageId")) or relative_level.name
                        code = _string(stage.get("code"))
                        stage_name = _string(stage.get("name"))
                        is_tutorial = "tutorial" in canonical_path.casefold() or (
                            code is not None and "-TR-" in code
                        )
                        suffix = "教学" if is_tutorial else "战斗内对话"
                        reference: StoryReference = {
                            "type": "tutorial" if is_tutorial else "battle-story",
                            "link": f"stage/{stage_id}",
                            "name": _join_name(
                                " ".join(part for part in (code, stage_name) if part),
                                suffix,
                            ),
                        }
                        count += self.catalog.add(canonical_path, reference)
                    continue

                path_parts = canonical_path.casefold().split("/")
                if "sandboxperm" in path_parts:
                    topic_id = next(
                        (part for part in path_parts if part.startswith("sandbox_")),
                        "sandbox",
                    )
                    topic = _object(sandbox_info.get(topic_id))
                    reference_type = "reclamation-algorithm"
                    link = f"sandbox/{topic_id}/level/{relative_level.name}"
                    group_name = _string(topic.get("topicName")) or topic_id
                elif "roguelike" in path_parts:
                    ro_part = next(
                        (
                            part
                            for part in path_parts
                            if re.fullmatch(r"ro[0-9]+", part)
                        ),
                        "ro",
                    )
                    topic_id = f"rogue_{ro_part[2:]}"
                    topic = _object(rogue_topics.get(topic_id))
                    reference_type = "integrated-strategies"
                    link = f"roguelike/{topic_id}/level/{relative_level.name}"
                    group_name = _string(topic.get("name")) or topic_id
                else:
                    reference_type = (
                        "tutorial" if "tutorial" in path_parts else "battle-story"
                    )
                    link = f"level/{relative_level.as_posix()}"
                    group_name = "教学" if reference_type == "tutorial" else "关卡"

                reference = {
                    "type": reference_type,
                    "link": link,
                    "name": _join_name(group_name, relative_level.name),
                }
                count += self.catalog.add(canonical_path, reference)
        logger.debug(f"StoryIndex level references: {count}")

    def build(self) -> StoryIndex:
        story_review_table = self._load_table("story_review_table.json")
        story_table = self._load_table("story_table.json")
        handbook_table = self._load_table("handbook_info_table.json")
        character_table = self._load_table("character_table.json")
        sandbox_table = self._load_table("sandbox_perm_table.json")
        roguelike_table = self._load_table("roguelike_topic_table.json")
        activity_table = self._load_table("activity_table.json")
        zone_table = self._load_table("zone_table.json")
        story_review_meta_table = self._load_table("story_review_meta_table.json")
        stage_table = self._load_table("stage_table.json")

        self._add_story_review(story_review_table)
        self._add_operator_memories(handbook_table, character_table, story_table)
        self._add_sandbox(sandbox_table)
        self._add_roguelike(roguelike_table)
        self._add_activity(activity_table)
        self._add_zone_records(zone_table)
        self._add_story_review_meta(
            story_review_meta_table, activity_table, roguelike_table
        )
        self._add_levels(stage_table, sandbox_table, roguelike_table)

        return {
            "schemaVersion": 1,
            "resVersion": self.res_version,
            "scripts": self.catalog.scripts(),
        }


class Task(BaseTask):
    # Keep this task after every extractor: story_index.json is the completion
    # signal consumed by downstream services.
    priority: ClassVar[int] = 100
    name = "StoryIndex"

    def check(self, diff_list: list[Diff]) -> bool:
        return True

    @run_sync
    def _build_and_write(self) -> None:
        version = self.client.version.res_version
        index = StoryIndexBuilder(GAMEDATA_DIR / version, version).build()
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = OUTPUT_PATH.with_suffix(".json.tmp")
        temp_path.write_text(
            json.dumps(index, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temp_path, OUTPUT_PATH)

        referenced = sum(bool(script["references"]) for script in index["scripts"])
        logger.info(
            f"Wrote StoryIndex with {len(index['scripts'])} scripts "
            f"({referenced} referenced) to {OUTPUT_PATH}"
        )

    async def start(self):
        await self._build_and_write()
