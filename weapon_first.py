"""Prioritize equipping a second weapon in the early Mech Royale match."""

from math import hypot
from time import perf_counter_ns

from bot import angle_delta, distance
from cover_rotation import Bot as CoverRotation
from practice import Goal


class Bot(CoverRotation):
    name = "codec-weapon-first"

    def searching(self, obs):
        me = obs["self"]
        return (obs["t"] < 36. and me["grounded"] and me["in_zone"]
                and me["hp"] >= .84 * me["max_hp"]
                and any(w is None for w in me["weapons"])
                and obs["t"] - self.last_damage > 1.5)

    def choose_resource(self, obs, threats, urgent):
        base = super().choose_resource(obs, threats, urgent)
        if urgent or not self.searching(obs):
            return base
        me,now,zone = obs["self"],obs["t"],obs["zone"]
        p = me["pos"]
        if threats and distance(p, threats[0]["pos"]) < 72.:
            return base
        options = []
        for seen, item in sorted(self.loot_memory.values(),
                                 key=lambda pair: distance(p, pair[1]["pos"]))[:6]:
            if perf_counter_ns() >= self.move_deadline - 850_000:
                break
            dest, kind = item["pos"], item["kind"]
            gap = distance(p, dest)
            if gap > 135. or abs(p[2] - dest[2]) > 4. or self.upgrade_slot(me, kind) is None:
                continue
            if distance(dest,zone["center"]) + 12. > zone["radius"]:
                continue
            if now + gap/me["stats"]["walk_speed"] + 9. > zone["shrink_end"]:
                if distance(dest,zone["next_center"]) + 12. > zone["next_radius"]:
                    continue
            direct = self.clear_grid(p,dest) if gap > 18 else self.arena.ground_step(p,dest,me["stats"])
            if gap <= 18 and not direct:
                continue
            eta = gap / me["stats"]["walk_speed"]
            if not direct:
                eta = eta * 1.35 + 1.5
            best_type = 1.25 if kind == "laser" else .40 if kind == "lightning" else 0.
            threat_cost = sum(max(0., 1. - distance(dest,t["pos"]) / 95.) for t in threats[:3])
            score = eta + .65*(now-seen) + 3.4*threat_cost - best_type
            if item["id"] == self.last_selected:
                score -= .5
            options.append((score,item["id"],dest))
        if not options:
            return base
        _, self.last_selected, dest = min(options)
        return Goal("pickup",tuple(dest[:2]),max(1.3,self.pickup_radius-1.))

    def act(self, obs):
        action = super().act(obs)
        if not self.searching(obs) or self.flight is not None:
            return action
        p = obs["self"]["pos"]
        nearby_enemy = any(x["kind"]=="mech" and distance(x["pos"],p)<108. for x in obs["mechs"])
        if nearby_enemy or action["jump"] or any(action["fire"]):
            return action
        now, me = obs["t"], obs["self"]
        if self.objective is None:
            yaw = me["aim"][0] + self.escape_sign * 1.35
            action["aim"] = [angle_delta(yaw,0.),0.]
        if (self.objective is None or self.objective.kind=="pickup") and hypot(*action["move"])>.7:
            if me["energy"] > 60. and now < 20.:
                action["boost"] = True
        return action
