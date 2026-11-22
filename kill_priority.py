"""Finish one opponent before spreading fire across several."""

from time import perf_counter_ns

from bot import angle_delta, distance, heading
from staged_supply import Bot as StagedSupply


class Bot(StagedSupply):
    name = "codec-kill-priority"

    def priority_target(self, obs, threats, urgent):
        me = obs["self"]
        p = me["pos"]
        if len(threats) < 2 or urgent or me["hp"] < .57 * me["max_hp"]:
            return None
        if distance(p, threats[1]["pos"]) > 170.:
            return None

        slots, _ = self.loadout(me)
        eye = self.muzzle(me)
        shortest = float("inf")
        choice = None
        for target in threats[:5]:
            if perf_counter_ns() >= self.fire_deadline - 2_000_000:
                break
            if "hp" not in target or distance(p, target["pos"]) > 175.:
                continue
            point, span, aim = self.direct_aim(me, target)
            if not self.arena.clear(eye, point):
                continue
            dps = 0.
            if "gun" in slots:
                gun = me["weapons"][slots["gun"]]
                stats = gun["stats"]
                if span < stats["range"]:
                    dps += stats["damage"] / stats["cooldown"] * max(.20, .80 - span / 250.) * (
                        .40 if gun["reload"] > .2 or not gun["ammo"] else 1.)
            if "laser" in slots:
                laser = me["weapons"][slots["laser"]]
                stats = laser["stats"]
                if span < stats["range"]:
                    damage = stats["damage"] * (
                        1. + stats["cookoff"] if "mortar" in target.get("weapons", ()) else 1.)
                    dps += .73 * damage / (stats["cooldown"] + stats["charge"])
            if "lightning" in slots:
                lightning = me["weapons"][slots["lightning"]]["stats"]
                if span < lightning["range"] and me["energy"] > 15.:
                    dps += .77 * lightning["damage"] / lightning["cooldown"]
            if not dps:
                continue
            if abs(angle_delta(heading(target["pos"], p), target["aim"][0])) > 1.65:
                dps *= 1.35
            turn = abs(angle_delta(aim[0], me["aim"][0])) / me["stats"]["turn_rate"]
            seconds = target["hp"] / dps + turn + span * .005
            if target["id"] == self.target_id:
                seconds -= .35
            if seconds < shortest:
                shortest, choice = seconds, target
        return choice

    def fire(self, obs, action, threats, urgent):
        choice = self.priority_target(obs, threats, urgent)
        super().fire(obs, action, [choice] if choice is not None else threats, urgent)
