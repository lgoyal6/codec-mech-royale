"""Take short opening climbs to safe roofs in Mech Royale."""

from time import perf_counter_ns

from arena import squared_distance_to_edge
from bot import distance
from skyline import Bot as LaserFinish


class Bot(LaserFinish):
    name = "codec-roof-guard"

    def __init__(self, hello):
        super().__init__(hello)
        self.opening_flight = False
        self.perch = None
        self.perch_until = 0.
        self.roof_points = []
        padding = self.config["mech"]["radius"] + 1.7
        for solid in self.arena.solids:
            left, right, bottom, top = solid.bounds
            for ix in range(1, 6):
                x = left + (right - left) * ix / 6
                for iy in range(1, 6):
                    y = bottom + (top - bottom) * iy / 6
                    if not solid.contains(x, y):
                        continue
                    edge = min(squared_distance_to_edge(x, y, e) for e in solid.boundary)
                    if not padding ** 2 <= edge <= 15 ** 2:
                        continue
                    altitude = solid.high - self.arena.height(x, y)
                    if 6 <= altitude <= 23:
                        point = (x, y, solid.high)
                        self.roof_points.append((point, altitude))

    def choose_flight(self, obs, urgent, move):
        existing = super().choose_flight(obs, urgent, move)
        if existing is not None:
            return existing
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        if (urgent or self.opening_flight or now > 15. or now < self.retry_flight_at
                or not me["grounded"] or me["energy"] < 62
                or me["hp"] < .95 * me["max_hp"]):
            return None

        p = me["pos"]
        if self.objective and self.objective.kind in ("pickup", "cube"):
            if distance(p, self.objective.point) < 28:
                return None
        if any(unit["kind"] == "mech" and distance(p, unit["pos"]) < 96 for unit in obs["mechs"]):
            return None

        options = []
        for pos, altitude in self.roof_points:
            span = distance(p, pos)
            if (7 < span <= 38 and 5 < pos[2] - p[2] <= 22
                    and distance(pos, zone["next_center"]) + 20 < zone["next_radius"]):
                options.append((span - .55 * altitude, pos))
        for _, pos in sorted(options)[:6]:
            if perf_counter_ns() >= self.fire_deadline + 850_000:
                break
            plan = self.loft(me, pos, now, "perch")
            if plan is not None:
                self.opening_flight = True
                return plan
        return None

    def fly(self, obs, action):
        plan, landings = self.flight, self.landed_flights
        result = super().fly(obs, action)
        if plan.kind == "perch" and self.landed_flights > landings:
            self.perch = plan.target
            self.perch_until = obs["t"] + 24.
        return result

    def choose_goal(self, obs):
        goal, hold, urgent = super().choose_goal(obs)
        me = obs["self"]
        if self.perch is not None and not urgent and obs["t"] < self.perch_until:
            if abs(me["pos"][2] - self.perch[2]) < 2. and me["hp"] > .62 * me["max_hp"]:
                return self.perch[:2], distance(me["pos"], self.perch) < 4., False
        self.perch = None
        return goal, hold, urgent
