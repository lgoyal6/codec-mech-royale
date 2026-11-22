"""Build early power from isolated drones and visible loot."""

import math
from time import perf_counter_ns

from bot import angle_delta, distance
from practice import Goal
from skyline import Bot as RoofAndMortar


class Bot(RoofAndMortar):
    name = "codec-scavenge"
    farm_drones = True
    sweep_at_spawn = True

    def __init__(self, hello):
        super().__init__(hello)
        self.last_mech_damage = -math.inf

    def observe(self, obs):
        super().observe(obs)
        for event in obs.get("events", ()):
            if event["type"] == "damaged" and event.get("by") in range(self.config["match"]["mechs"]):
                self.last_mech_damage = obs["t"]

    def choose_resource(self, obs, threats, urgent):
        objective = super().choose_resource(obs, threats, urgent)
        if not self.farm_drones or urgent or (objective and objective.kind != "crate"):
            return objective
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        point = me["pos"]
        if me["cubes"] >= 7 or me["hp"] < .65 * me["max_hp"] or now - self.last_mech_damage < 3:
            return objective
        nearest = distance(point, threats[0]["pos"]) if threats else math.inf
        if nearest < 95:
            return objective
        drones = sorted((x for x in obs["mechs"] if x["kind"] == "npc"),
                        key=lambda x: distance(point, x["pos"]) + .045 * x.get("hp", 350))
        for target in drones[:3]:
            if perf_counter_ns() >= self.move_deadline:
                break
            p = target["pos"]
            gap = distance(point, p)
            if not gap < min(72., nearest - 45) or abs(p[2] - point[2]) > 6:
                continue
            if distance(p, zone["center"]) + 12 > zone["radius"]:
                continue
            if now + gap / me["stats"]["walk_speed"] + 15 >= zone["shrink_end"]:
                if distance(p, zone["next_center"]) + 12 > zone["next_radius"]:
                    continue
            center = (*p[:2], p[2] + .5 * self.config["npc"]["height"])
            if not self.arena.clear(self.muzzle(me), center):
                continue
            self.last_selected = target["id"]
            return Goal("npc", tuple(p[:2]), 16.)
        return objective

    def act(self, obs):
        action = super().act(obs)
        if (self.sweep_at_spawn and obs["t"] < 1.6 and self.objective is None
                and not any(x["kind"] == "mech" for x in obs["mechs"])):
            yaw = obs["self"]["aim"][0] + self.escape_sign * 1.4
            action["aim"] = [angle_delta(yaw, 0.), 0.]
        return action
