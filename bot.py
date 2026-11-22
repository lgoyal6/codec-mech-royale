"""Original Mech Royale policy. This module consumes only official observations."""

import math


def clamp(value, low, high):
    return max(low, min(value, high))


def angle_delta(target, current):
    return math.remainder(target - current, math.tau)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def heading(a, b):
    return math.atan2(b[1] - a[1], b[0] - a[0])


def direction(yaw):
    return math.cos(yaw), math.sin(yaw)


def advance(point, yaw, length):
    dx, dy = direction(yaw)
    return point[0] + length * dx, point[1] + length * dy


class Bot:
    name = "codec-control"

    def __init__(self, hello):
        cfg = hello["config"]
        self.step = 1 / cfg["match"]["tick_hz"]
        self.interval = self.step * cfg["match"]["decide_every"]
        cube_config = cfg["cubes"]
        self.size_per_cube = cube_config.get("size_per_cube", .05)
        self.base_radius = cfg["mech"]["radius"]
        self.base_height = cfg["mech"]["height"]
        self.velocity = {}
        self.target_id = None
        self.progress_anchor = None
        self.progress_time = 0
        self.escape_until = 0
        self.escape_sign = 1 if hello["slot"] % 2 else -1
        self.heading_before_escape = 0

    def choose_goal(self, obs):
        me, zone = obs["self"], obs["zone"]
        pos, center = me["pos"], zone["next_center"]
        span = distance(pos, center)
        radius = zone["next_radius"]
        safe_radius = max(0., radius - min(32., radius * .45))
        edge = distance(pos, zone["center"]) - zone["radius"]
        travel = max(0., span - safe_radius) / max(me["stats"]["walk_speed"], 1)
        urgent = not me["in_zone"] or edge > -7 or (
            span > safe_radius and obs["t"] + travel + 7 >= zone["shrink_end"]
        )
        if not me["in_zone"] and radius > 20 and span > safe_radius:
            dest = advance(center, heading(center, pos), safe_radius * .70)
        elif radius > 20 and span > safe_radius:
            dest = advance(center, heading(center, pos), safe_radius * .66)
        else:
            dest = center
        hold = span <= max(2.0, min(16., radius * .20)) and not urgent
        return dest, hold, urgent

    def movement(self, obs, goal, hold, urgent):
        me = obs["self"]
        pos, now = me["pos"], obs["t"]
        yaw = heading(pos, goal)
        if hold or distance(pos, goal) <= 1.3:
            self.progress_anchor = pos
            self.progress_time = now
            return (0., 0.), False, False
        if self.progress_anchor is None:
            self.progress_anchor = pos
            self.progress_time = now
        if now - self.progress_time >= .9:
            if distance(pos, self.progress_anchor) < 2.0 and now >= self.escape_until:
                self.escape_sign *= -1
                self.heading_before_escape = yaw
                self.escape_until = now + 1.3
            self.progress_anchor = pos
            self.progress_time = now
        escaping = now < self.escape_until
        if escaping:
            yaw = self.heading_before_escape + self.escape_sign * 1.2
        boost = urgent and me["energy"] > (5 if not me["in_zone"] else 21)
        jump = escaping and me["grounded"] and me["energy"] >= 35
        return direction(yaw), boost, jump

    def aim_for_gun(self, me, target, stats, now):
        size = 1 + target.get("cubes", 0) * self.size_per_cube
        radius = target.get("radius", self.base_radius * size)
        midpoint = target.get("height", self.base_height * size) / 2
        muzzle = me["stats"]["muzzle_height"]
        offset = [b - a for a, b in zip(me["pos"], target["pos"])]
        offset[2] += midpoint - muzzle

        speed = stats["speed"]
        velocity = target.get("vel", (0., 0., 0.))
        own_velocity = me["vel"]
        prior = self.velocity.get(target["id"])
        damp = 1.
        if prior and 0 < now - prior[0] <= .35:
            change = math.dist(prior[1], velocity)
            damp = clamp(1. - .055 * change, .45, 1.)
        launch = self.step
        predicted = [r + (v - own) * launch for r, v, own in zip(offset, velocity, own_velocity)]
        launch_offset = me["stats"]["radius"] + .5
        flight = max(0., math.hypot(*predicted) - launch_offset) / speed
        vector = [r + v * flight * damp for r, v in zip(predicted, velocity)]
        xy = math.hypot(*vector[:2])
        yaw = math.atan2(vector[1], vector[0])
        pitch = math.atan2(vector[2], xy)
        origin = (me["pos"][0], me["pos"][1], me["pos"][2] + muzzle)
        impact = tuple(a + own * launch + relative for a, own, relative in zip(origin, own_velocity, vector))
        return yaw, pitch, impact, radius, math.hypot(*vector)

    def clear_shot(self, start, end):
        return True

    def combat(self, obs, action):
        me, now = obs["self"], obs["t"]
        gun_slot = next((i for i, w in enumerate(me["weapons"]) if w and w["kind"] == "gun"), None)
        if gun_slot is None:
            return
        gun = me["weapons"][gun_slot]
        pos = me["pos"]
        threats = [t for t in obs["mechs"] if t["kind"] == "mech"]
        threats.sort(key=lambda t: distance(pos, t["pos"]) - 9 * (t["id"] == self.target_id))
        muzzle = (*pos[:2], pos[2] + me["stats"]["muzzle_height"])
        for candidate in threats[:6]:
            yaw, pitch, impact, radius, span = self.aim_for_gun(me, candidate, gun["stats"], now)
            if span > gun["stats"]["range"]:
                continue
            if not self.clear_shot(muzzle, impact):
                continue
            self.target_id = candidate["id"]
            action["aim"] = [yaw, pitch]
            allowed_pitch = clamp(pitch, me["stats"]["min_pitch"], me["stats"]["max_pitch"])
            yaw_error = max(0., abs(angle_delta(yaw, me["aim"][0])) - me["stats"]["turn_rate"] * self.step)
            pitch_error = max(0., abs(allowed_pitch - me["aim"][1]) - me["stats"]["pitch_rate"] * self.step)
            tolerance = math.atan2(radius, max(1., span)) + .009
            if pitch != allowed_pitch:
                pitch_error += abs(pitch - allowed_pitch)
            action["fire"][gun_slot] = math.hypot(yaw_error, pitch_error) <= tolerance
            break
        else:
            self.target_id = None
            if threats:
                action["aim"] = [heading(pos, threats[0]["pos"]), 0.]
            elif gun.get("ammo", 0) < gun["stats"]["mag"] * .5 and not gun.get("reload", 0):
                action["reload"] = True
        self.velocity = {t["id"]: (now, t.get("vel", (0., 0., 0.))) for t in threats}

    def upgrades(self, obs, action):
        offer = obs.get("offer")
        if offer:
            values = {"nanites": 7, "plating": 6, "servos": 5, "armor": 5, "gyros": 4,
                      "gun_damage": 4, "gun_velocity": 3, "gun_rate": 3, "gun_mag": 2}
            choices = offer["choices"]
            if choices:
                action["pick"] = max(range(len(choices)), key=lambda i: values.get(choices[i]["id"], 1))

    def act(self, obs):
        me = obs["self"]
        goal, hold, urgent = self.choose_goal(obs)
        move, boost, jump = self.movement(obs, goal, hold, urgent)
        scan = heading(me["pos"], goal)
        if hold:
            scan += (int(obs["t"] / 1.4) % 6) * math.tau / 6
        action = {"tick": obs["tick"], "move": move, "boost": boost, "jump": jump,
                  "aim": [angle_delta(scan, 0.), 0.], "fire": [False, False]}
        self.combat(obs, action)
        self.upgrades(obs, action)
        return action
