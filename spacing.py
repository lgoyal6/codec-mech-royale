"""Choose a firing lane against an isolated opponent in Mech Royale."""

from time import perf_counter_ns

from bot import advance, angle_delta, distance, heading
from practice import Goal
from skyline import Bot as LaserFinish


class Bot(LaserFinish):
    name = "codec-reactive-spacing"

    def __init__(self, hello):
        super().__init__(hello)
        self.attackers = {}

    def observe(self, obs):
        super().observe(obs)
        now = obs["t"]
        for actor, at in tuple(self.attackers.items()):
            if now - at > 3.5:
                del self.attackers[actor]
        for event in obs.get("events", ()):
            actor = event.get("by")
            if event["type"] == "damaged" and actor in range(self.config["match"]["mechs"]):
                self.attackers[actor] = now

    def pursuing(self, point, target, span):
        if target["id"] in self.attackers:
            return True
        aim = target.get("aim")
        if aim is None or abs(angle_delta(heading(target["pos"], point), aim[0])) > .58:
            return False
        vx, vy = target.get("vel", (0., 0., 0.))[:2]
        dx, dy = point[0] - target["pos"][0], point[1] - target["pos"][1]
        return (vx * dx + vy * dy) / span > 3.3

    def choose_resource(self, obs, threats, urgent):
        objective = super().choose_resource(obs, threats, urgent)
        if urgent or not threats or (objective and objective.kind != "crate"):
            return objective
        me, zone = obs["self"], obs["zone"]
        p, target = me["pos"], threats[0]
        span = distance(p, target["pos"])
        if not 21 < span < 127 or me["hp"] < .62 * me["max_hp"]:
            return objective
        if not self.pursuing(p, target, span):
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
