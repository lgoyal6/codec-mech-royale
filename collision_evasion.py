"""Preserve the normal action unless a visible projectile intersects its path."""

import math
from time import perf_counter_ns

from bot import direction, distance
from combat_horizon import Defensive


class Bot(Defensive):
    name = "codec-collision-evasion"

    def steer(self, obs, goal, threats, urgent, holding):
        ordinary = super().steer(obs, goal, threats, urgent, holding)
        me, zone = obs["self"], obs["zone"]
        if urgent or ordinary[2] or not me["grounded"] or "projectiles" not in obs:
            return ordinary
        projectiles = self.projectile_risk(obs)
        if not projectiles or perf_counter_ns() >= self.move_deadline:
            return ordinary

        body, p = me["stats"], me["pos"]
        charging = any(w and w.get("charge", 0.) > 0. for w in me["weapons"])
        factor = body["charge_move_mult"] if charging else 1.
        move, boosting, _ = ordinary
        current_yaw = math.atan2(move[1], move[0])
        base_speed = body["boost_speed"] if boosting else body["walk_speed"]
        risk = self.projectile_cost(me, projectiles, current_yaw, factor * base_speed * math.hypot(*move))
        if risk < 1.2:
            return ordinary

        room = me["energy"] > 19.
        collision = risk
        best = ordinary
        vx, vy = me["vel"][:2]
        for offset in (.60, -.60, 1.20, -1.20, 1.80, -1.80, 2.40, -2.40, math.pi):
            if perf_counter_ns() >= self.move_deadline:
                break
            yaw = current_yaw + offset
            dx, dy = direction(yaw)
            for boost in (boosting, not boosting) if room else (boosting,):
                speed = factor * (body["boost_speed"] if boost else body["walk_speed"])
                ramp = min(.43, math.hypot(dx * speed - vx, dy * speed - vy) / body["ground_accel"])
                q = (p[0] + dx * speed * (.47 - ramp / 2.) + vx * ramp / 2.,
                     p[1] + dy * speed * (.47 - ramp / 2.) + vy * ramp / 2.)
                if (distance(q, zone["center"]) + 8. > zone["radius"]
                        or not self.arena.ground_step(p, q, body)):
                    continue
                alternative = self.projectile_cost(me, projectiles, yaw, speed)
                metric = alternative + .20 * abs(offset) + .24 * (boost and not boosting)
                if metric < collision - .06:
                    collision = metric
                    best = (dx, dy), boost, False
            if collision < .40:
                break
        return best
