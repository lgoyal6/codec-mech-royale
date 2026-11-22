"""Stage off the supply ring and enter near landing when it is clear."""

from math import inf
from time import perf_counter_ns

from bot import distance
from cover_rotation import BEARINGS, Bot as CoverRotation
from practice import Goal


class Bot(CoverRotation):
    name = "codec-staged-supply"

    def __init__(self, hello):
        super().__init__(hello)
        self.stage_id = None
        self.stage_point = None
        self.stage_review = 0.

    def staging_point(self, obs, drop, threats):
        now = obs["t"]
        if self.stage_id == drop["id"] and now < self.stage_review:
            return self.stage_point
        self.stage_id = drop["id"]
        self.stage_review = now + 1.
        self.stage_point = None
        me, zone = obs["self"], obs["zone"]
        position, stats = me["pos"], me["stats"]
        x, y, _ = drop["pos"]
        radius = drop["radius"] + 11.
        best = -inf
        for dx, dy in BEARINGS:
            if perf_counter_ns() >= self.move_deadline:
                break
            point = x + radius * dx, y + radius * dy
            if (distance(point, zone["center"]) + 10. > zone["radius"]
                    or not self.arena.open(self.arena.cell_at(point))):
                continue
            ground = self.arena.height(*point)
            if not self.arena.ground_step((*point, ground), drop["pos"], stats):
                continue
            gap = distance(position, point)
            score = -.045 * gap + 1.1 * self.clear_grid(position, point)
            eye = (*point, ground + stats["muzzle_height"])
            for enemy in threats[:4]:
                incoming = enemy["pos"]
                span = distance(point, incoming)
                if span < 105.:
                    score -= max(0., 65. - span) * .055
                    if self.arena.clear(eye, (*incoming[:2], incoming[2] + 7.)):
                        score -= 1.8
            if score > best:
                best, self.stage_point = score, point
        return self.stage_point

    def choose_resource(self, obs, threats, urgent):
        ordinary = super().choose_resource(obs, threats, urgent)
        me, zone = obs["self"], obs["zone"]
        if urgent or not me["grounded"] or not obs.get("drops"):
            return ordinary
        position = me["pos"]
        hp = me["hp"] / me["max_hp"]
        if hp < .32 or (hp > .93 and me["cubes"] >= 4):
            return ordinary
        nearest = distance(position, threats[0]["pos"]) if threats else inf
        if nearest < 29. and hp < .58:
            return ordinary

        for drop in sorted(obs["drops"], key=lambda d: distance(position, d["pos"])):
            if perf_counter_ns() >= self.move_deadline:
                break
            point, radius, remaining = drop["pos"], drop["radius"], drop["lands_in"]
            gap = distance(position, point)
            if (gap > min(225., 110. + remaining * 9.)
                    or distance(point, zone["center"]) + radius + 8. > zone["radius"]
                    or distance(point, zone["next_center"]) + radius > zone["next_radius"] + 1.):
                continue
            holding = drop.get("holder") == me["id"]
            if drop.get("holder") is not None and not holding:
                continue
            if ordinary and ordinary.kind == "pickup" and hp > .68 and distance(position, ordinary.point) < 12.:
                continue
            ring_eta = max(0., gap - radius + 3.) / me["stats"]["walk_speed"]
            if nearest < 75. and gap > 52. and hp < .63:
                continue
            approach = [
                (distance(point, enemy["pos"]), distance(point, (
                    enemy["pos"][0] + enemy["vel"][0] * 2.,
                    enemy["pos"][1] + enemy["vel"][1] * 2.,
                )))
                for enemy in threats[:4]
            ]
            contested = any(span < 22. or (span < 52. and predicted < 24.)
                            for span, predicted in approach)
            if holding or (not contested and (remaining <= 4. or ring_eta + 1. >= remaining)):
                if gap <= 18. and not self.arena.ground_step(position, point, me["stats"]):
                    continue
                self.last_selected = drop["id"]
                return Goal("drop", tuple(point[:2]), max(1., radius - 3.))
            if remaining <= 0. and (not contested or gap < 16.):
                continue
            stage = self.staging_point(obs, drop, threats)
            if stage is not None and all(distance(stage, enemy["pos"]) >= 18. for enemy in threats[:4]):
                self.last_selected = drop["id"]
                return Goal("drop", stage, 4.)
        return ordinary
