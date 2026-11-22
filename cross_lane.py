"""Change transverse movement during clear exchanges in Mech Royale."""

import math
from time import perf_counter_ns

from adaptive_combat import Bot as AdaptiveCombat
from bot import angle_delta, clamp, direction, distance, heading


class Bot(AdaptiveCombat):
    name = "codec-cross-lane"

    def __init__(self, hello):
        super().__init__(hello)
        self.strafe_rival = None
        self.strafe_side = 1
        self.strafe_until = 0.

    def strafe(self, obs, goal, threats, urgent):
        me, now, zone = obs["self"], obs["t"], obs["zone"]
        position, stats = me["pos"], me["stats"]
        if (urgent or not me["grounded"] or not threats or me["hp"] < .42 * me["max_hp"]
                or goal.kind == "drop" or (goal.kind in ("cube", "pickup") and distance(position, goal.point) < 17.)):
            return None
        rival = threats[0]
        gap = distance(position, rival["pos"])
        if not 30. <= gap <= 135. or distance(position, zone["center"]) + 20. >= zone["radius"]:
            return None
        if len(threats) > 1 and distance(position, threats[1]["pos"]) < 90.:
            return None
        bearing = heading(position, rival["pos"])
        if (abs(angle_delta(bearing + math.pi, rival["aim"][0])) > .88
                or not self.arena.clear(self.muzzle(me), self.direct_aim(me, rival)[0])
                or self.projectile_risk(obs)):
            return None

        held, _ = self.loadout(me)
        use_lightning = "lightning" in held and me["energy"] > 30.
        laser = me["weapons"][held["laser"]] if "laser" in held else None
        charging = laser is not None and laser["charge"] > 0.
        comfortable = 37. if use_lightning else 63.
        range_bias = clamp((gap - comfortable) / 55., -.58, .48)
        if rival.get("hp", 1400.) < .33 * me["hp"] and gap > comfortable:
            range_bias = max(range_bias, .36)
        orientation = math.acos(range_bias)
        boost = not charging and me["energy"] > (38. if gap > 45. else 53.)
        speed = stats["boost_speed"] if boost else stats["walk_speed"]
        if charging:
            speed *= stats["charge_move_mult"]
        same_rival = self.strafe_rival == rival["id"]
        flip = same_rival and now >= self.strafe_until
        side = self.strafe_side * (-1 if flip else 1)
        if not same_rival:
            side = 1 if angle_delta(heading(position, goal.point), bearing) >= 0. else -1
        for chosen in (side, -side):
            if perf_counter_ns() >= self.move_deadline - 350_000:
                return None
            dx, dy = direction(bearing + chosen * orientation)
            vx, vy = me["vel"][:2]
            ramp = min(.48, math.hypot(dx * speed - vx, dy * speed - vy) / stats["ground_accel"])
            seconds = .68
            point = (position[0] + dx * speed * (seconds - ramp / 2.) + vx * ramp / 2.,
                     position[1] + dy * speed * (seconds - ramp / 2.) + vy * ramp / 2.)
            if (distance(point, zone["center"]) + 13. >= zone["radius"]
                    or distance(point, zone["next_center"]) > distance(position, zone["next_center"]) + 12.
                    or not self.arena.ground_step(position, point, stats)):
                continue
            if not same_rival or flip or chosen != self.strafe_side:
                self.strafe_rival, self.strafe_side = rival["id"], chosen
                phase = (obs["tick"] * 53 + 17 * rival["id"]) % 19
                self.strafe_until = now + .55 + .016 * phase + .002 * gap
            return (dx, dy), boost, False
        return None

    def steer(self, obs, goal, threats, urgent, holding):
        move = self.strafe(obs, goal, threats, urgent)
        return move if move is not None else super().steer(obs, goal, threats, urgent, holding)
