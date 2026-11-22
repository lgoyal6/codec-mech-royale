"""Short-horizon cover scoring for the official game observation."""

import math
from time import perf_counter_ns

from arena import Arena
from bot import Bot as Control, advance, angle_delta, direction, distance, heading

OFFSETS = (0., .43, -.43, .86, -.86, 1.29, -1.29, 1.85, -1.85, 2.45, -2.45, math.pi)


class Bot(Control):
    name = "codec-cover"

    def __init__(self, hello):
        super().__init__(hello)
        self.arena = Arena(hello["map"]["dir"], hello["config"]["mech"])
        self.last_travel_yaw = None
        self.last_damage = -math.inf
        self.last_hit = -math.inf

    def clear_shot(self, start, end):
        return perf_counter_ns() < self.tick_deadline + 1_000_000 and self.arena.clear(start, end)

    def route_to(self, obs, goal, urgent, deadline):
        return goal

    def track_damage(self, obs):
        for event in obs.get("events", ()):
            if event["type"] == "damaged":
                self.last_damage = obs["t"]
            elif event["type"] == "hit":
                self.last_hit = obs["t"]

    def movement(self, obs, goal, hold, urgent):
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p = me["pos"]
        hp = me["hp"] / me["max_hp"]
        here = distance(p, zone["center"]) - zone["radius"]
        threats = sorted(
            (target for target in obs["mechs"] if target["kind"] == "mech"
             and distance(p, target["pos"]) <= 160),
            key=lambda target: distance(p, target["pos"]),
        )[:3]
        danger = len(threats) >= 2 or hp < .68 or now - self.last_damage < 1.1
        budget = self.tick_deadline
        if hold and not danger and not threats:
            return (0., 0.), False, False
        waypoint = self.route_to(obs, goal, urgent, budget)
        toward = heading(p, waypoint)
        if not urgent and threats and here < -15:
            threat_yaw = heading(p, threats[0]["pos"])
            if danger or distance(p, threats[0]["pos"]) < 48:
                toward = threat_yaw + math.pi
            else:
                sign = self.escape_sign if int(now / 3.1) % 2 else -self.escape_sign
                toward = threat_yaw + sign * 1.2

        if not urgent and not threats and distance(p, goal) < 2:
            return (0., 0.), False, False
        stats = me["stats"]
        length = 7 if hold else 9
        eye_height = max(2., p[2] + stats["muzzle_height"] - self.arena.height(*p[:2]))
        credible = []
        for target in threats:
            target_pos = target["pos"]
            source = (*target_pos[:2], target_pos[2] + 7)
            credible.append((source, distance(p, target_pos)))
        best_yaw, best_score = None, -math.inf
        current_margin = distance(p, zone["next_center"]) - zone["next_radius"]
        for offset in OFFSETS:
            if best_yaw is not None and perf_counter_ns() >= budget:
                break
            yaw = toward + offset
            point = advance(p, yaw, length)
            if not self.arena.ground_step(p, point, stats):
                continue
            margin = distance(point, zone["center"]) - zone["radius"]
            ahead_margin = distance(point, zone["next_center"]) - zone["next_radius"]
            penalty = max(0., margin + 8) - max(0., here + 8)
            future = max(0., ahead_margin + min(22., zone["next_radius"] / 3)) - max(
                0., current_margin + min(22., zone["next_radius"] / 3)
            )
            score = 1.2 * math.cos(offset) - (.23 if urgent else .15) * penalty - .09 * future
            if self.last_travel_yaw is not None:
                score += .21 * math.cos(angle_delta(yaw, self.last_travel_yaw))
            if credible:
                dest_z = self.arena.height(*point) + eye_height
                for source, previous_distance in credible:
                    if perf_counter_ns() >= budget:
                        break
                    if self.arena.clear(source, (*point, dest_z)):
                        score -= .64 if danger else .22
                    if danger:
                        score += .03 * (distance(point, source) - previous_distance)
            if score > best_score:
                best_score, best_yaw = score, yaw

        if best_yaw is None:
            return super().movement(obs, waypoint, hold, urgent)
        self.last_travel_yaw = best_yaw
        is_escape = danger and bool(threats) and hp < .74 and now - self.last_damage < 2.0
        boost = me["grounded"] and me["energy"] >= (9 if not me["in_zone"] else 26) and (
            urgent or (is_escape and distance(p, threats[0]["pos"]) < 90)
        )
        return direction(best_yaw), boost, False

    def act(self, obs):
        self.tick_deadline = perf_counter_ns() + 7_000_000
        self.track_damage(obs)
        action = super().act(obs)
        hp = obs["self"]["hp"] / obs["self"]["max_hp"]
        if hp < .57 and obs["t"] - max(self.last_damage, self.last_hit) > 2.6:
            # A final shot breaks the cooldown needed for passive repair.
            nearby = any(t["kind"] == "mech" and distance(obs["self"]["pos"], t["pos"]) < 57
                         for t in obs["mechs"])
            if not nearby:
                action["fire"] = [False, False]
        return action
