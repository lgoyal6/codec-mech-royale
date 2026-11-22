"""Optional short jet climb for visible roof loot and blocked rotations."""

import math
from time import perf_counter_ns
from typing import NamedTuple

from bot import advance, direction, distance, heading
from bombard import Bot as FullLoadout


class Flight(NamedTuple):
    target: tuple
    altitude: float
    finish_by: float
    kind: str


class Bot(FullLoadout):
    name = "codec-trajectory-dodge"

    def __init__(self, hello):
        super().__init__(hello)
        self.flight = None
        self.retry_flight_at = 0.
        self.stall_at = 0.
        self.stall_pos = None
        self.attempted_flights = 0
        self.landed_flights = 0

    def loft(self, me, target, now, kind):
        start = me["pos"]
        body = me["stats"]
        gap = distance(start, target)
        if not 7 < gap <= 45 or me["energy"] < 54 or not me["grounded"]:
            return None
        nearby = tuple(self.arena._nearby(start, target, body["radius"] + 1))
        required = max(start[2], target[2])
        steps = math.ceil(gap / 2.5)
        for n in range(steps + 1):
            f = n / steps
            x, y = start[0] + (target[0] - start[0]) * f, start[1] + (target[1] - start[1]) * f
            required = max(required, self.arena.height(x, y))
            for solid in nearby:
                if solid.blocks_footprint(x, y, start[2], body["radius"] + 1,
                                          100., body["step_up"]):
                    required = max(required, solid.high)
        ascent = required - start[2] + 1.4
        if not 3 <= ascent <= 25:
            return None
        altitude = start[2] + ascent
        for solid in nearby:
            if solid.blocks_footprint(start[0], start[1], start[2],
                                      body["radius"] + .4, ascent + body["height"],
                                      body["step_up"]):
                return None

        # Reserve energy for the climb and the worst case of holding height
        # until the full target segment is clear.
        climb_s = ascent / body["max_rise_speed"]
        traverse_s = gap / body["walk_speed"] + body["walk_speed"] / body["air_accel"]
        burn = body["jet_drain"] * (climb_s + .6 * traverse_s)
        if burn + 18 > me["energy"]:
            return None
        return Flight(tuple(target), altitude, now + climb_s + traverse_s + 2.2, kind)

    def choose_flight(self, obs, urgent, move):
        me, now = obs["self"], obs["t"]
        p = me["pos"]
        if now < self.retry_flight_at or not me["grounded"] or me["energy"] < 54:
            return None
        if any(enemy["kind"] == "mech" and distance(p, enemy["pos"]) < 70 for enemy in obs["mechs"]):
            return None
        if perf_counter_ns() >= self.fire_deadline:
            return None
        zone = obs["zone"]
        if distance(p, zone["center"]) + 14 >= zone["radius"]:
            return None
        pickups = sorted(obs.get("pickups", ()), key=lambda x: distance(x["pos"],p))
        for item in pickups[:4] if not urgent else ():
            target = item["pos"]
            if not 4 < target[2] - p[2] <= 24 or self.upgrade_slot(me,item["kind"]) is None:
                continue
            flight = self.loft(me,target,now,"pickup")
            if flight and distance(target,zone["center"])+10 < zone["radius"]:
                return flight
        if self.stall_pos is None:
            self.stall_pos, self.stall_at = p, now
            return None
        if now - self.stall_at < 1.5:
            return None
        stalled = math.hypot(*move) > .6 and distance(p,self.stall_pos) < 2.8
        self.stall_pos, self.stall_at = p, now
        if not stalled:
            return None
        center = zone["next_center"]
        target_yaw = heading(p,center)
        for offset in (0.,.45,-.45):
            q = advance(p,target_yaw+offset,23)
            if self.arena.ground_step(p,q,me["stats"]):
                continue
            target = (*q,self.arena.height(*q))
            flight = self.loft(me,target,now,"rotation")
            if flight and distance(target,zone["center"])+6 < zone["radius"]:
                return flight
        return None

    def fly(self, obs, action):
        me, now = obs["self"], obs["t"]
        p, plan = me["pos"], self.flight
        gap = distance(p,plan.target)
        if now >= plan.finish_by or me["energy"] < 7:
            self.flight = None
            self.retry_flight_at = now + 6.
            return action
        if me["grounded"] and gap < 4 and abs(p[2]-plan.target[2]) <= 4:
            self.flight = None
            self.landed_flights += 1
            self.retry_flight_at = now + 2.
            return action
        rising = p[2] < plan.altitude - .8
        close = gap <= 3.1
        if rising and not close and me["grounded"]:
            motion = (0.,0.)
        elif rising and not close and p[2] < plan.altitude - 2.5:
            motion = (.15 * action["move"][0], .15 * action["move"][1])
        elif close:
            vx,vy = me["vel"][:2]
            motion = (-max(-.45,min(.45,vx/12)), -max(-.45,min(.45,vy/12)))
        else:
            motion = direction(heading(p,plan.target))
        action.update(move=motion,jump=me["grounded"] and rising,
                      boost=not me["grounded"] and not close and p[2] < plan.altitude+1.2)
        return action

    def act(self, obs):
        action = super().act(obs)
        if self.flight is None:
            _,_,urgent = self.choose_goal(obs)
            self.flight = self.choose_flight(obs,urgent,action["move"])
            if self.flight is not None:
                self.attempted_flights += 1
        return self.fly(obs,action) if self.flight is not None else action
