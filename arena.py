"""Ground navigation and line of sight against the mounted arena."""

from array import array
from collections import defaultdict
import json
import math
from pathlib import Path
import sys


def squared_distance_to_edge(x, y, edge):
    x0, y0, dx, dy, norm = edge
    fraction = min(1., max(0., ((x - x0) * dx + (y - y0) * dy) / norm))
    return (x - x0 - fraction * dx) ** 2 + (y - y0 - fraction * dy) ** 2


def edges(flat):
    ring = list(zip(flat[::2], flat[1::2]))
    result = []
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        dx, dy = x1 - x0, y1 - y0
        norm = dx * dx + dy * dy
        if norm:
            result.append((x0, y0, dx, dy, norm))
    return result


def contains(x, y, ring):
    inside = False
    for x0, y0, dx, dy, _ in ring:
        if (y0 > y) != (y0 + dy > y) and x < x0 + (y - y0) * dx / dy:
            inside = not inside
    return inside


class Solid:
    def __init__(self, entry):
        ring = entry["ring"]
        self.low, self.high = entry["base"], entry["top"]
        self.bounds = min(ring[::2]), max(ring[::2]), min(ring[1::2]), max(ring[1::2])
        self.outer = edges(ring)
        self.holes = [edges(hole) for hole in entry.get("holes", [])]
        self.boundary = self.outer + [edge for hole in self.holes for edge in hole]

    def contains(self, x, y):
        return contains(x, y, self.outer) and not any(contains(x, y, hole) for hole in self.holes)

    def blocks_footprint(self, x, y, z, radius, height, step):
        x0, x1, y0, y1 = self.bounds
        if (x < x0 - radius or x > x1 + radius or y < y0 - radius or y > y1 + radius
                or self.high <= z + step or self.low >= z + height):
            return False
        return self.contains(x, y) or any(
            squared_distance_to_edge(x, y, edge) <= radius * radius for edge in self.boundary
        )

    def hits_ray(self, start, end):
        x, y, z = start
        dx, dy, dz = (b - a for a, b in zip(start, end))
        x0, x1, y0, y1 = self.bounds
        enter, leave = 0., 1.
        for origin, delta, low, high in ((x, dx, x0, x1), (y, dy, y0, y1),
                                         (z, dz, self.low, self.high)):
            if abs(delta) < 1e-9:
                if origin < low or origin > high:
                    return False
                continue
            near, far = (low - origin) / delta, (high - origin) / delta
            if near > far:
                near, far = far, near
            enter, leave = max(enter, near), min(leave, far)
            if enter > leave:
                return False
        if self.contains(x + dx * enter, y + dy * enter) or self.contains(x + dx * leave, y + dy * leave):
            return True
        for sx, sy, ex, ey, _ in self.boundary:
            cross = dx * ey - dy * ex
            if abs(cross) < 1e-9:
                continue
            rx, ry = sx - x, sy - y
            ray_at = (rx * ey - ry * ex) / cross
            edge_at = (rx * dy - ry * dx) / cross
            if enter <= ray_at <= leave and 0 <= edge_at <= 1:
                return True
        return False


class Arena:
    cell = 6
    bin_size = 30

    def __init__(self, map_dir, stats):
        folder = Path(map_dir) / "v2"
        world = json.loads((folder / "world.json").read_bytes())
        self.terrain = world["terrain"]
        self.heights = array("h")
        self.heights.frombytes((folder / "terrain.i16").read_bytes())
        if sys.byteorder != "little":
            self.heights.byteswap()
        bounds = world["bounds"]
        self.x0, self.y0 = bounds["minX"], bounds["minY"]
        self.x1, self.y1 = bounds["maxX"], bounds["maxY"]
        self.nx = int((self.x1 - self.x0) / self.cell)
        self.ny = int((self.y1 - self.y0) / self.cell)
        self.solids = [Solid(p) for p in world["prisms"]]
        self.bins = defaultdict(list)
        for i, solid in enumerate(self.solids):
            x0, x1, y0, y1 = solid.bounds
            for y in range(math.floor(y0 / self.bin_size), math.floor(y1 / self.bin_size) + 1):
                for x in range(math.floor(x0 / self.bin_size), math.floor(x1 / self.bin_size) + 1):
                    self.bins[x, y].append(i)
        self.pad = stats["radius"] + 1.25
        self.step = stats["step_up"]
        self.slope = math.tan(math.radians(stats["max_slope_deg"]))
        self.walkable = bytearray([1]) * (self.nx * self.ny)
        self._mark_obstacles(stats["height"])

    def height(self, x, y):
        t = self.terrain
        gx = (x - t["minX"]) / t["step"]
        gy = (y - t["minY"]) / t["step"]
        gx = max(0., min(t["nx"] - 1.0001, gx))
        gy = max(0., min(t["ny"] - 1.0001, gy))
        i, j = int(gx), int(gy)
        u, v = gx - i, gy - j
        row = t["nx"]
        k = j * row + i
        hs = self.heights
        return ((hs[k] * (1 - u) + hs[k + 1] * u) * (1 - v)
                + (hs[k + row] * (1 - u) + hs[k + row + 1] * u) * v) * .01

    def cell_at(self, pos):
        return math.floor((pos[0] - self.x0) / self.cell), math.floor((pos[1] - self.y0) / self.cell)

    def center(self, cell):
        return self.x0 + (cell[0] + .5) * self.cell, self.y0 + (cell[1] + .5) * self.cell

    def open(self, cell):
        x, y = cell
        return 0 <= x < self.nx and 0 <= y < self.ny and self.walkable[y * self.nx + x]

    def _mark_obstacles(self, height):
        pad = self.pad
        for solid in self.solids:
            x0, x1, y0, y1 = solid.bounds
            i0, j0 = self.cell_at((x0 - pad, y0 - pad))
            i1, j1 = self.cell_at((x1 + pad, y1 + pad))
            for j in range(max(0, j0), min(self.ny, j1 + 1)):
                for i in range(max(0, i0), min(self.nx, i1 + 1)):
                    x, y = self.center((i, j))
                    if solid.blocks_footprint(x, y, self.height(x, y), pad, height, self.step):
                        self.walkable[j * self.nx + i] = 0

    def _nearby(self, a, b, pad=0.):
        size = self.bin_size
        seen = set()
        for y in range(math.floor((min(a[1], b[1]) - pad) / size),
                       math.floor((max(a[1], b[1]) + pad) / size) + 1):
            for x in range(math.floor((min(a[0], b[0]) - pad) / size),
                           math.floor((max(a[0], b[0]) + pad) / size) + 1):
                for i in self.bins.get((x, y), ()):
                    if i not in seen:
                        seen.add(i)
                        yield self.solids[i]

    def clear(self, start, end):
        if any(solid.hits_ray(start, end) for solid in self._nearby(start, end)):
            return False
        dx, dy, dz = (b - a for a, b in zip(start, end))
        count = max(1, math.ceil(math.hypot(dx, dy) / 4))
        for n in range(1, count):
            t = n / count
            if self.height(start[0] + dx * t, start[1] + dy * t) >= start[2] + dz * t:
                return False
        return True

    def ground_step(self, start, end, stats):
        radius = stats["radius"] + .2
        if not (self.x0 + radius <= end[0] <= self.x1 - radius
                and self.y0 + radius <= end[1] <= self.y1 - radius):
            return False
        x, y = start[:2]
        dx, dy = end[0] - x, end[1] - y
        count = max(1, math.ceil(math.hypot(dx, dy) / 2))
        solids = tuple(self._nearby(start, end, radius))
        ground = self.height(x, y)
        # A mech that landed above ground should be able to move off a roof.
        height_above = max(0., start[2] - ground if len(start) > 2 else 0.)
        for n in range(1, count + 1):
            t = n / count
            u, v = x + dx * t, y + dy * t
            z = self.height(u, v)
            if height_above < 1.4 and z - ground > max(stats["step_up"], self.slope * math.hypot(dx, dy) / count):
                return False
            ground = z
            z += height_above
            if any(solid.blocks_footprint(u, v, z, radius, stats["height"], stats["step_up"])
                   for solid in solids):
                return False
        return True
