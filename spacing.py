"""Choose a firing lane against an isolated opponent in Mech Royale."""

from time import perf_counter_ns

from bot import advance, distance, heading
from practice import Goal
from skyline import Bot as LaserFinish


class Bot(LaserFinish):
    name = "codec-spacing"

    def choose_resource(self, obs, threats, urgent):
        objective = super().choose_resource(obs, threats, urgent)
        if urgent or not threats or (objective and objective.kind != "crate"):
            return objective
        me, zone = obs["self"], obs["zone"]
        p, target = me["pos"], threats[0]
        span = distance(p, target["pos"])
        if not 21 < span < 127 or me["hp"] < .62 * me["max_hp"]:
            return objective
        if len(threats) > 1 and distance(p, threats[1]["pos"]) < 125:
            return objective
        if not me["grounded"] or abs(target["pos"][2] - p[2]) > 10:
            return objective

        target_point, _, _ = self.direct_aim(me, target)
        if not self.arena.clear(self.muzzle(me), target_point):
            return objective
        weapons = target.get("weapons", ())
        prefer = 64. if "lightning" in weapons else 52.
        radial = heading(target["pos"], p)
        for offset in (.57 * self.escape_sign, -.57 * self.escape_sign, 0.):
            if perf_counter_ns() >= self.move_deadline:
                break
            pos = advance(target["pos"], radial + offset, prefer)
            if distance(pos, zone["center"]) + 24 > zone["radius"]:
                continue
            step = min(12., distance(p, pos))
            near = advance(p, heading(p, pos), step)
            if not self.arena.ground_step(p, near, me["stats"]):
                continue
            muzzle = (*near, self.arena.height(*near) + me["stats"]["muzzle_height"])
            if self.arena.clear(muzzle, target_point):
                return Goal("spacing", pos, 4.)
        return objective
