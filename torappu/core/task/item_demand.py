import json
import itertools

import httpx

from torappu.core.client import Change
from torappu.core.task.base import Task
from torappu.core.task.utils import trans_prof
from torappu.consts import BASE_DIR, GAMEDATA_DIR


def ensure_item_exists(item_demand, item_name, char_id, char_detail, skill_num):
    if not item_demand.get(item_name):
        item_demand[item_name] = {}
    if not item_demand[item_name].get(char_id):
        item_demand[item_name][char_id] = {
            "rarity": int(char_detail["rarity"].replace("TIER_", "")),
            "name": char_detail["name"],
            "profession": char_detail["profession"],
            "elite": 0,
            "skill": 0,
            "uniequip": 0,
            "mastery": [0 for i in range(0, skill_num)],
        }


class ItemDemand(Task):
    name = "ItemDemand"

    def need_run(self, change_list: list[Change]) -> bool:
        return True

    def fetch_data(self, path: str):
        with open(GAMEDATA_DIR / self.client.version.res_version / path) as f:
            return json.load(f)

    async def inner_run(self):
        demand = self.get_item_demand()
        if self.client.config is None:
            with open(BASE_DIR / "itemDemand.json", "w+") as f:
                json.dump(demand, f)
            return
        async with httpx.AsyncClient() as client:
            await client.post(
                self.client.config.endpoint + "/api/v1/item/demand",
                headers={"torappu-auth": self.client.config.token},
                json=demand,
            )

    def get_item_demand(self):
        character_table = self.fetch_data("excel/character_table.json")
        item_table = self.fetch_data("excel/item_table.json")
        char_patch_table = self.fetch_data("excel/char_patch_table.json")
        uniequip_table = self.fetch_data("excel/uniequip_table.json")

        for patch_char_id, patch_char_detail in char_patch_table["patchChars"].items():
            patch_char_detail[
                "name"
            ] += f"({trans_prof(patch_char_detail['profession'])})"
            character_table[patch_char_id] = patch_char_detail

        item_demand = {}
        for char_id, char_detail in character_table.items():
            if (
                char_detail["profession"] == "TRAP"
                or char_detail["profession"] == "TOKEN"
            ):
                continue

            for phase in char_detail["phases"]:
                if phase["evolveCost"]:
                    for evolve_cost_item in phase["evolveCost"]:
                        item_name = item_table["items"][evolve_cost_item["id"]]["name"]
                        ensure_item_exists(
                            item_demand,
                            item_name,
                            char_id,
                            char_detail,
                            len(char_detail.get("skills", [{}, {}, {}])),
                        )
                        if char_id == "char_1001_amiya2":
                            item_demand[item_name][char_id]["elite"] = 0
                            continue
                        item_demand[item_name][char_id]["elite"] += evolve_cost_item[
                            "count"
                        ]

            if not char_detail["skills"]:
                continue

            for skill_level_up in char_detail["allSkillLvlup"]:
                if not skill_level_up["lvlUpCost"]:
                    continue
                for demand in skill_level_up["lvlUpCost"]:
                    item_name = item_table["items"][demand["id"]]["name"]
                    ensure_item_exists(
                        item_demand,
                        item_name,
                        char_id,
                        char_detail,
                        len(char_detail["skills"]),
                    )
                    item_demand[item_name][char_id]["skill"] += demand["count"]

            i = 0
            for skill in char_detail["skills"]:
                if not skill["levelUpCostCond"]:
                    continue
                for cost_cond in skill["levelUpCostCond"]:
                    if not cost_cond["levelUpCost"]:
                        continue
                    for demand in cost_cond["levelUpCost"]:
                        item_name = item_table["items"][demand["id"]]["name"]
                        ensure_item_exists(
                            item_demand,
                            item_name,
                            char_id,
                            char_detail,
                            len(char_detail["skills"]),
                        )
                        item_demand[item_name][char_id]["mastery"][i] += demand["count"]
                i += 1

        for uniequip_id, uniequip_detail in uniequip_table["equipDict"].items():
            if not uniequip_detail["itemCost"]:
                continue
            item_costs = list(
                itertools.chain.from_iterable(uniequip_detail["itemCost"].values())
            )
            for demand in item_costs:
                item_name = item_table["items"][demand["id"]]["name"]
                char_id = uniequip_detail["charId"]
                if demand["type"] != "MATERIAL":
                    continue
                ensure_item_exists(
                    item_demand,
                    item_name,
                    char_id,
                    character_table[char_id],
                    len(character_table[char_id].get("skills", [])),
                )
                item_demand[item_name][char_id]["uniequip"] += demand["count"]

        delete_demand = []
        for item_name, demand_detail in item_demand.items():
            for char_id, char_demand in demand_detail.items():
                if (
                    char_demand["elite"] == 0
                    and char_demand["skill"] == 0
                    and set(char_demand["mastery"]) == {0}
                    and char_demand["uniequip"] == 0
                ):
                    delete_demand.append((item_name, char_id))

        for delete_target in delete_demand:
            item_name, char_id = delete_target
            del item_demand[item_name][char_id]

        return item_demand
