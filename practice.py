"""Practice policy for the published Mech Royale observation and action protocol."""

import math
from time import perf_counter_ns
from typing import NamedTuple

from bot import advance, angle_delta, clamp, direction, distance, heading
from routing import Bot as Routed


class Goal(NamedTuple):
    kind: str
    point: tuple
    radius: float


# High-value turns get sampled first if we exhaust the decision budget.
TURNS = (0., .42, -.42, .85, -.85, 1.36, -1.36, 2.1, -2.1, math.pi)
WEAPON_VALUE = {"laser": 2, "lightning": 1}
MOBILE_WEAPON_VALUE = {"lightning": 2, "laser": 1}


class Bot(Routed):
    name = "codec-economy"
    seek_resources = True

    def __init__(self, hello):
        super().__init__(hello)
        self.config = hello["config"]
        self.pickup_radius = self.config["loot"]["pickup_radius"]
        self.cube_radius = self.config["cubes"]["pickup_radius"]
        self.sprinting = False
        self.damage_bearing = None
        self.bearing_time = -math.inf
        self.objective = None
        self.loot_memory = {}
        self.crate_memory = {}
        self.last_selected = None
        self.mobility_opening = False

    def observe(self, obs):
        self.track_damage(obs)
        now = obs["t"]
        for event in obs.get("events", ()):
            if event["type"] == "damaged" and event.get("bearing") is not None:
                self.damage_bearing = event["bearing"]
                self.bearing_time = now
            elif event["type"] in ("took", "take_failed") and event.get("reason", "gone") == "gone":
                self.loot_memory.pop(event["id"], None)
        for key, memory in (("pickups", self.loot_memory), ("crates", self.crate_memory)):
            for entry in obs.get(key, ()):
                memory[entry["id"]] = now, entry
            for item_id in tuple(memory):
                seen, entry = memory[item_id]
                if now - seen > 2.4 or (seen != now and distance(obs["self"]["pos"], entry["pos"]) <= 6):
                    del memory[item_id]

    def muzzle(self, mech):
        p = mech["pos"]
        return p[0], p[1], p[2] + mech["stats"]["muzzle_height"]

    def weapon_value(self, me):
        return MOBILE_WEAPON_VALUE if self.mobility_opening and me["energy"] >= 45 else WEAPON_VALUE

    def loadout(self, me):
        held = {weapon["kind"]: i for i, weapon in enumerate(me["weapons"]) if weapon}
        empty = next((i for i, weapon in enumerate(me["weapons"]) if weapon is None), None)
        return held, empty

    def upgrade_slot(self, me, kind):
        held, empty = self.loadout(me)
        priorities = self.weapon_value(me)
        if kind not in priorities or kind in held:
            return None
        if empty is not None:
            return empty
        for weapon, slot in held.items():
            if weapon != "gun" and priorities.get(kind, 0) > priorities.get(weapon, 0):
                if not me["weapons"][slot].get("charge", 0):
                    return slot
        return None

    def choose_resource(self, obs, threats, urgent):
        if not self.seek_resources or urgent:
            return None
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p = me["pos"]
        hp = me["hp"] / me["max_hp"]
        nearest = distance(p, threats[0]["pos"]) if threats else math.inf
        opening = now < 72 and me["cubes"] < 6
        pressure = nearest < 54 or now - self.last_damage < 1.4
        soon = 8 + (17 if zone["next_radius"] > 70 else 6)
        options = []

        def option(kind, key, pos, radius, value, reach):
            gap = distance(p, pos)
            if gap > reach or abs(pos[2] - p[2]) > 4:
                return
            if distance(pos, zone["center"]) + radius > zone["radius"] + 1:
                return
            if now + gap / me["stats"]["walk_speed"] + soon >= zone["shrink_end"]:
                if distance(pos, zone["next_center"]) + radius > zone["next_radius"]:
                    return
            if (perf_counter_ns() >= self.move_deadline or
                    (gap <= 18 and not self.arena.ground_step(p, pos, me["stats"]))):
                return
            value -= gap * .078
            if threats and distance(pos, threats[0]["pos"]) < min(nearest + 2, 62):
                value -= 3.0
            if self.last_selected == key:
                value += 1.2
            options.append((value, key, Goal(kind, tuple(pos[:2]), radius)))

        for drop in obs.get("drops", ()):
            pos = drop["pos"]
            close_enemies = sum(distance(pos, enemy["pos"]) < 28 for enemy in threats)
            if (drop.get("holder") not in (None, me["id"]) or
                    drop["lands_in"] > max(4., distance(p, pos) / 10 + 1.5) or close_enemies > 0):
                continue
            option("drop", drop["id"], pos, max(1., drop["radius"] - 2),
                   10 + 11 * (1 - hp) + (2.5 if drop.get("holder") == me["id"] else 0), 116)

        loot = sorted(self.loot_memory.values(), key=lambda x: distance(p, x[1]["pos"]))[:8]
        for seen, entry in loot:
            if self.upgrade_slot(me, entry["kind"]) is None:
                continue
            value = (9. if opening else 6.5) + self.weapon_value(me)[entry["kind"]]
            option("pickup", entry["id"], entry["pos"], max(1.3, self.pickup_radius - 1.),
                   value - .5 * (now - seen), 32 if pressure else 121)

        for cube in sorted(obs.get("cubes", ()), key=lambda x: distance(p, x["pos"]))[:6]:
            option("cube", cube["id"], cube["pos"], max(1.0, self.cube_radius - .7),
                   6.5 + 1.3 * opening, 22 if pressure else 64)

        if (nearest > 82 and now - self.last_damage > 2 and hp >= .62
                and (opening or me["cubes"] < 5)):
            for seen, crate in sorted(self.crate_memory.values(), key=lambda x: distance(p, x[1]["pos"]))[:5]:
                option("crate", crate["id"], crate["pos"], 4.0,
                       6.2 + 2.2 * opening + 2. * (1 - crate["hp"] / self.config["crates"]["hp"])
                       - .8 * (now - seen), 81)

        if not options:
            self.last_selected = None
            return None
        value, key, resource = max(options, key=lambda choice: choice[0])
        self.last_selected = key if value > 0 else None
        return resource if self.last_selected is not None else None

    def projectile_risk(self, obs):
        me = obs["self"]
        px, py, pz = me["pos"]
        mx, my, mz = me["vel"]
        body = me["stats"]
        threats = []
        for shot in obs.get("projectiles", ()):
            q, velocity = shot["pos"], shot["vel"]
            x, y, z = q[0] - px, q[1] - py, q[2] - pz
            vx, vy, vz = velocity
            rx, ry = vx - mx, vy - my
            speed_squared = rx * rx + ry * ry
            if speed_squared < 16 or abs(x) + abs(y) > 230:
                continue
            arrival = -(x * rx + y * ry) / speed_squared
            if not 0 <= arrival <= .61:
                continue
            shell = shot["kind"] == "mortar"
            gravity = self.config["weapons"]["mortar"]["gravity"] if shell else 0.
            radius = body["radius"] + (6. if shell else .35)
            vertical = z + (vz - mz) * arrival - gravity * arrival * arrival / 2
            if not -6 < vertical < body["height"] + 7:
                continue
            lateral = math.hypot(x + rx * arrival, y + ry * arrival)
            if lateral > radius + 3 + .5 * body["ground_accel"] * arrival ** 2:
                continue
            threats.append((arrival, x, y, z, vx, vy, vz, gravity, radius))
        return sorted(threats)[:4]

    def projectile_cost(self, me, projectiles, yaw, speed):
        ux, uy = direction(yaw)
        vx, vy, vz = me["vel"]
        change_x, change_y = ux * speed - vx, uy * speed - vy
        accel = me["stats"]["ground_accel"] if me["grounded"] else me["stats"]["air_accel"]
        settle = math.hypot(change_x, change_y) / accel
        cost = 0.
        for arrival, x, y, z, sx, sy, sz, gravity, radius in projectiles:
            # Approximate the curved acceleration path around the nearest
            # crossing using continuous intersections on short segments.
            start = max(0., arrival - .12)
            previous = None
            closest = math.inf
            for n in range(5):
                t = start + .065 * n
                active = min(t, settle)
                progress = active * (t - .5 * active) / settle if settle else 0.
                dx = x + (sx - vx) * t - change_x * progress
                dy = y + (sy - vy) * t - change_y * progress
                dz = z + (sz - vz) * t - .5 * gravity * t * t
                if previous is not None:
                    ax, ay, az = previous
                    nx, ny = dx - ax, dy - ay
                    fraction = clamp(-(ax * nx + ay * ny) / max(.01, nx * nx + ny * ny), 0., 1.)
                    vertical = az + (dz - az) * fraction
                    margin = 4.5 if gravity else .45
                    if -margin <= vertical <= me["stats"]["height"] + margin:
                        closest = min(closest, math.hypot(ax + nx * fraction, ay + ny * fraction))
                previous = dx, dy, dz
            cost += 3.5 * max(0., min(1., (radius + 1.5 - closest) / 2))
        return cost

    def steer(self, obs, goal, threats, urgent, holding):
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p = me["pos"]
        hp = me["hp"] / me["max_hp"]
        nearest = distance(p, threats[0]["pos"]) if threats else math.inf
        resource = goal.kind in ("pickup", "cube", "crate", "drop")
        recovering = hp < .72 and (len(threats) > 1 or nearest < 75 or now - self.last_damage < 4)
        pressure = len(threats) > 1 or nearest < 49 or now - self.last_damage < 1.15
        projectiles = self.projectile_risk(obs)
        if holding and not urgent and not projectiles and (goal.kind == "drop" or not pressure):
            return [0., 0.], False, False

        gap = distance(p, goal.point)
        waypoint = self.route_to(obs, goal.point, urgent, self.move_deadline) if gap > 20 else goal.point
        toward = heading(p, waypoint)
        if threats and not urgent and not resource:
            back = heading(threats[0]["pos"], p)
            if pressure or recovering or self.mobility_opening:
                if distance(p, zone["center"]) < zone["radius"] - 25:
                    blend = .80 if hp < .52 else .63
                    tx, ty = direction(toward)
                    bx, by = direction(back)
                    toward = math.atan2(ty * (1 - blend) + by * blend, tx * (1 - blend) + bx * blend)
            elif nearest < 130:
                side = self.escape_sign * (1 if int(now / 3.6) % 2 else -1)
                toward = back + side * 1.18

        reserve = 4. if not me["in_zone"] else (14. if urgent else (21. if pressure else 34.))
        start_sprint = min(me["max_energy"] * .75, reserve + (9 if pressure or urgent else 22))
        self.sprinting = me["energy"] > (reserve if self.sprinting else start_sprint)
        boost = me["grounded"] and self.sprinting and (gap > 17 or pressure or urgent)
        charging = any(w and w["kind"] == "laser" and w.get("charge", 0) > 0 for w in me["weapons"])
        if charging:
            boost = boost and (urgent or nearest < 55)
        speed = me["stats"]["boost_speed"] if boost else me["stats"]["walk_speed"]
        if charging:
            speed *= me["stats"].get("charge_move_mult", self.config["mech"]["charge_move_mult"])
        travel = min(8.5, max(3., gap))
        here = distance(p, zone["center"]) - zone["radius"]
        best_score, best_yaw = -math.inf, None
        eye_offset = p[2] - self.arena.height(*p[:2]) + me["stats"]["muzzle_height"]

        for offset in TURNS:
            if perf_counter_ns() >= self.move_deadline and best_yaw is not None:
                break
            yaw = toward + offset
            point = advance(p, yaw, travel)
            if not self.arena.ground_step(p, point, me["stats"]):
                continue
            margin = distance(point, zone["center"]) - zone["radius"]
            next_margin = distance(point, zone["next_center"]) - zone["next_radius"]
            score = 1.8 * math.cos(offset)
            score -= (.34 if urgent else .19) * (max(0., margin + 12) - max(0., here + 12))
            score -= .08 * max(0., next_margin + 13)
            if resource:
                score += .13 * (gap - distance(point, goal.point))
            if self.last_travel_yaw is not None:
                score += .26 * math.cos(angle_delta(yaw, self.last_travel_yaw))
            eye = (*point, self.arena.height(*point) + eye_offset)
            for threat in threats[:2]:
                if perf_counter_ns() >= self.move_deadline:
                    break
                enemy = threat["pos"]
                change = distance(point, enemy) - distance(p, enemy)
                if pressure or recovering:
                    score += .052 * change
                enemy_eye = (*enemy[:2], enemy[2] + 7)
                if self.arena.clear(enemy_eye, eye):
                    score -= .83 if recovering or pressure else .25
            if projectiles:
                score -= self.projectile_cost(me, projectiles, yaw, speed)
            if score > best_score:
                best_score, best_yaw = score, yaw
        if best_yaw is None:
            return super().movement(obs, waypoint, holding, urgent)
        self.last_travel_yaw = best_yaw
        return direction(best_yaw), boost, False

    def set_pickup(self, obs, action):
        me = obs["self"]
        for item in sorted(obs.get("pickups", ()), key=lambda x: distance(x["pos"], me["pos"])):
            if distance(item["pos"], me["pos"]) > self.pickup_radius:
                return
            if abs(item["pos"][2] - me["pos"][2]) > 4:
                continue
            slot = self.upgrade_slot(me, item["kind"])
            if slot is not None:
                action["take"] = item["id"]
                if me["weapons"][slot] is not None:
                    action["drop"] = slot
                return

    def aim_window(self, me, aim, yaw_tolerance, pitch_tolerance):
        yaw_error = abs(angle_delta(aim[0], me["aim"][0]))
        pitch_error = abs(aim[1] - me["aim"][1])
        stats = me["stats"]
        return (yaw_error <= yaw_tolerance + stats["turn_rate"] * self.step and
                pitch_error <= pitch_tolerance + stats["pitch_rate"] * self.step and
                stats["min_pitch"] <= aim[1] <= stats["max_pitch"])

    def direct_aim(self, me, target):
        center = target["pos"]
        size = 1 + target.get("cubes", 0) * self.size_per_cube
        height = self.base_height * size if target.get("kind") == "mech" else target["height"]
        speed = target.get("vel", (0., 0., 0.))
        target_xyz = tuple(coord + v * self.step for coord, v in zip(center, speed))
        point = (*target_xyz[:2], target_xyz[2] + height * .5)
        source = self.muzzle(me)
        span = math.dist(source, point)
        aim = (heading(source, point), math.atan2(point[2] - source[2], distance(source, point)))
        return point, span, aim

    def fire(self, obs, action, threats, urgent):
        me, now = obs["self"], obs["t"]
        held, _ = self.loadout(me)
        p = me["pos"]
        hp = me["hp"] / me["max_hp"]
        recover = hp < .66 and now - self.last_damage > .9 and (
            not threats or distance(p, threats[0]["pos"]) > (53 if urgent else 75))
        targets = sorted(threats, key=lambda t: distance(p, t["pos"])
                         + .028 * t.get("hp", 1400) - 12 * (t["id"] == self.target_id))[:5]
        if (self.objective and self.objective.kind == "crate" and
                (not threats or distance(p, threats[0]["pos"]) > 99) and not recover):
            item = next((x for x in obs.get("crates", ()) if x["id"] == self.last_selected), None)
            if item:
                targets.insert(0, {**item, "kind": "crate", "height": self.config["crates"]["height"]})
        gun = me["weapons"][held["gun"]] if "gun" in held else None
        laser = me["weapons"][held["laser"]] if "laser" in held else None
        lightning = me["weapons"][held["lightning"]] if "lightning" in held else None
        target, direct, gun_aim = None, None, None
        source = self.muzzle(me)

        for entry in targets if not recover else ():
            if perf_counter_ns() >= self.fire_deadline:
                break
            point, span, aim = self.direct_aim(me, entry)
            if not self.arena.clear(source, point):
                continue
            if gun and entry["kind"] == "mech":
                lead_x, lead_y, impact, radius, gun_span = self.aim_for_gun(me, entry, gun["stats"], now)
                if gun_span <= gun["stats"]["range"] and self.arena.clear(source, impact):
                    gun_aim = (lead_x, lead_y), math.atan2(radius, max(1., gun_span))
            elif gun and span <= gun["stats"]["range"]:
                gun_aim = aim, math.atan2(self.config["crates"]["radius"], max(1., span))
            if gun_aim or (laser and span <= laser["stats"]["range"]) or (
                lightning and span <= lightning["stats"]["range"]
            ):
                target, direct = entry, (span, aim)
                break

        self.target_id = target["id"] if target else None
        self.velocity = {t["id"]: (now, t.get("vel", (0., 0., 0.))) for t in threats}
        if target is None:
            if self.damage_bearing is not None and now - self.bearing_time < 3.:
                action["aim"] = [self.damage_bearing, 0.]
            if gun and gun.get("ammo", 0) < gun["stats"]["mag"] * .55 and not gun.get("reload", 0):
                action["reload"] = True
            return

        span, aim = direct
        chosen = gun_aim[0] if gun_aim else aim
        if laser and span <= laser["stats"]["range"]:
            stats, charge = laser["stats"], laser.get("charge", 0.)
            want_charge = stats["charge"]
            if target["kind"] == "crate":
                needed = target["hp"] / max(1., stats["damage"])
                want_charge = max(stats["min_charge"], stats["charge"] *
                                  clamp((needed - stats["min_frac"]) / (1 - stats["min_frac"]), 0., 1.))
            elif "hp" in target:
                rules = self.config["cubes"]
                bonus = 1 + rules["damage_per_cube"] * min(me["cubes"], rules["stat_cap"])
                cookoff = 1 + stats.get("cookoff", .6) * ("mortar" in target.get("weapons", ()))
                needed = target["hp"] * 1.08 / max(1., stats["damage"] * bonus * cookoff)
                fraction = (needed - stats["min_frac"]) / (1 - stats["min_frac"])
                want_charge = max(stats["min_charge"] + self.step,
                                  stats["charge"] * clamp(fraction, 0., 1.))
            laser_tol = math.atan2(self.base_radius, max(1., span))
            aligned = self.aim_window(me, aim, laser_tol, laser_tol)
            recently_hit = now - self.last_damage < 1.5
            can_slow = not urgent and (not recently_hit or hp > .60 or span < 72)
            use_laser = charge > 0 or (can_slow and laser["cooldown"] <= .10 and
                                      abs(angle_delta(aim[0], me["aim"][0])) < .65)
            if use_laser:
                chosen = aim
                hold = charge < want_charge - self.step or not aligned
                action["fire"][held["laser"]] = hold and (can_slow or charge == 0)
        if lightning and span <= lightning["stats"]["range"]:
            cone = math.radians(lightning["stats"]["cone_deg"])
            if not self.aim_window(me, aim, cone * .7, cone):
                chosen = aim
            action["fire"][held["lightning"]] = (
                self.aim_window(me, aim, cone * .85, cone) and
                me["energy"] >= lightning["stats"]["energy"] + (18 if urgent else 4))
        action["aim"] = list(chosen)
        if gun_aim:
            gun_target, tolerance = gun_aim
            same_heading = abs(angle_delta(chosen[0], gun_target[0])) <= tolerance
            same_pitch = abs(chosen[1] - gun_target[1]) <= tolerance
            action["fire"][held["gun"]] = (
                same_heading and same_pitch and self.aim_window(me, gun_target, tolerance, tolerance))

    def act(self, obs):
        start = perf_counter_ns()
        self.move_deadline = start + 4_800_000
        self.fire_deadline = start + 7_400_000
        self.tick_deadline = self.move_deadline
        self.observe(obs)
        me = obs["self"]
        p = me["pos"]
        threats = sorted((t for t in obs["mechs"] if t["kind"] == "mech"),
                         key=lambda t: distance(p, t["pos"]))
        center_goal, hold, urgent = self.choose_goal(obs)
        resource = self.choose_resource(obs, threats, urgent)
        self.objective = resource
        goal = resource or Goal("circle", center_goal, 2.)
        holding = distance(p, goal.point) <= goal.radius if resource else hold
        motion, boost, jump = self.steer(obs, goal, threats, urgent, holding)
        yaw = heading(p, goal.point)
        if not threats:
            if motion != (0., 0.) and math.hypot(*motion) > .3:
                yaw = math.atan2(motion[1], motion[0])
            yaw += (-.8, 0., .8, 0.)[int(obs["t"] / .8) % 4]
        action = {"tick": obs["tick"], "move": motion, "boost": boost, "jump": jump,
                  "aim": [angle_delta(yaw, 0.), 0.], "fire": [False, False]}
        self.set_pickup(obs, action)
        self.fire(obs, action, threats, urgent)
        self.upgrades(obs, action)
        return action
