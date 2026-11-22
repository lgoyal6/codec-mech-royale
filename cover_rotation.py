"""Choose a walkable position with static cover inside the upcoming zone."""
from math import cos, hypot, pi, sin

from skyline import Bot as LaserFinish

BEARINGS = tuple((cos(i*pi/4), sin(i*pi/4)) for i in range(8))


class Bot(LaserFinish):
    name = "codec-bounded-cover"

    def __init__(self, hello):
        super().__init__(hello)
        self.cover_zone = None
        self.cover_options = ()
        self.cover_samples = []
        self.cover_last_tick = -1
        self.cover_point = None

    def choose_goal(self, obs):
        default = super().choose_goal(obs)
        zone = obs["zone"]
        radius = zone["next_radius"]
        if default[2] or radius < 32:
            return default

        x, y = zone["next_center"]
        key = (x, y, radius)
        if key != self.cover_zone:
            self.cover_zone = key
            self.cover_point = None
            self.cover_samples = []
            offset = min(56.0, radius * .36)
            self.cover_options = tuple(
                (x + dx * ring, y + dy * ring)
                for ring in (offset * .50, offset)
                for dx, dy in BEARINGS
                if self.arena.open(self.arena.cell_at((x + dx * ring, y + dy * ring)))
            )

        remaining = len(self.cover_samples)
        if obs["tick"] != self.cover_last_tick and remaining < len(self.cover_options):
            self.cover_last_tick = obs["tick"]
            px, py = self.cover_options[remaining]
            z = self.arena.height(px, py) + obs["self"]["stats"]["height"] * .8
            origin = (px, py, z)
            blocked = 0
            for dx, dy in BEARINGS:
                qx, qy = px + dx * 35, py + dy * 35
                blocked += not self.arena.clear(origin, (qx, qy, self.arena.height(qx, qy) + 7))
            self.cover_samples.append((blocked, px, py))
            if len(self.cover_samples) == len(self.cover_options):
                sx, sy, *_ = obs["self"]["pos"]
                cover, cx, cy = max(
                    self.cover_samples,
                    key=lambda candidate: candidate[0] - hypot(candidate[1] - sx, candidate[2] - sy) / 100,
                )
                if cover >= 2:
                    self.cover_point = (cx, cy)

        point = self.cover_point
        if point is None:
            return default
        px, py = point
        zx, zy = zone["center"]
        if hypot(px - zx, py - zy) >= zone["radius"] - 9:
            return default
        sx, sy, *_ = obs["self"]["pos"]
        walk_to_cover = hypot(sx - px, sy - py)
        base_point, base_hold, _ = default
        walk_to_base = 0. if base_hold else hypot(sx - base_point[0], sy - base_point[1])
        if walk_to_cover > walk_to_base + 24.:
            return default
        return point, walk_to_cover <= 5., False
