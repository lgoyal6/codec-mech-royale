"""Resumable A* for blocked ground rotations."""

import heapq
import math
from time import perf_counter_ns

from bot import distance
from tactics import Bot as Cover

NEIGHBORS = ((1, 0, 1.), (-1, 0, 1.), (0, 1, 1.), (0, -1, 1.),
             (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
             (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)))


class Search:
    def __init__(self, arena, start, goal):
        self.arena, self.goal = arena, goal
        self.best = {start: 0.}
        self.parent = {start: None}
        self.queue = [(math.dist(start, goal), 0., start)]
        self.result = None
        self.visited = 0

    def advance(self, deadline, expansions=112):
        for _ in range(expansions):
            if not self.queue or self.visited >= 3600:
                return True
            if perf_counter_ns() >= deadline:
                return False
            _, cost, point = heapq.heappop(self.queue)
            if cost != self.best[point]:
                continue
            if point == self.goal:
                path = []
                while point is not None:
                    path.append(point)
                    point = self.parent[point]
                self.result = path[::-1]
                return True
            self.visited += 1
            px, py = point
            for dx, dy, length in NEIGHBORS:
                successor = px + dx, py + dy
                total = cost + length
                if total >= self.best.get(successor, math.inf) or not self.arena.open(successor):
                    continue
                if dx and dy and (not self.arena.open((px + dx, py))
                                  or not self.arena.open((px, py + dy))):
                    continue
                self.best[successor] = total
                self.parent[successor] = point
                heapq.heappush(self.queue, (total + math.dist(successor, self.goal), total, successor))
        return False


class Bot(Cover):
    name = "codec-routed"

    def __init__(self, hello):
        super().__init__(hello)
        self.path = []
        self.waypoint = 0
        self.search = None
        self.search_goal = None
        self.plan_again_at = 0.
        self.plan_anchor = None
        self.anchor_at = 0.
        self.expansions = 0
        self.completed_routes = 0

    def nearest_cell(self, point):
        x, y = self.arena.cell_at(point)
        for radius in range(5):
            cells = [(x + dx, y + dy) for dx in range(-radius, radius + 1)
                     for dy in range(-radius, radius + 1) if max(abs(dx), abs(dy)) == radius]
            candidates = [cell for cell in cells if self.arena.open(cell)]
            if candidates:
                return min(candidates, key=lambda cell: distance(point, self.arena.center(cell)))
        return None

    def clear_grid(self, start, goal):
        x, y = start[:2]
        dx, dy = goal[0] - x, goal[1] - y
        count = max(1, math.ceil(math.hypot(dx, dy) / (self.arena.cell / 2)))
        last = self.arena.cell_at(start)
        for n in range(1, count + 1):
            t = n / count
            cell = self.arena.cell_at((x + dx * t, y + dy * t))
            if not self.arena.open(cell):
                return False
            if cell[0] != last[0] and cell[1] != last[1] and (
                not self.arena.open((cell[0], last[1])) or not self.arena.open((last[0], cell[1]))
            ):
                return False
            last = cell
        return True

    def route_to(self, obs, goal, urgent, deadline):
        me, now = obs["self"], obs["t"]
        p = me["pos"]
        if not me["grounded"] or p[2] - self.arena.height(*p[:2]) > 2.5:
            return goal
        if self.plan_anchor is None:
            self.plan_anchor, self.anchor_at = p, now
        stuck = False
        if now - self.anchor_at >= 1.25:
            stuck = distance(p, self.plan_anchor) < 3 and distance(p, goal) > 13
            self.plan_anchor, self.anchor_at = p, now

        dest = self.nearest_cell(goal)
        if dest is None:
            return goal
        dest_xy = self.arena.center(dest)
        if distance(p, goal) < 30:
            # The local controller uses continuous geometry and is better at
            # reaching a point inside a coarse cell, especially late in the game.
            if self.arena.ground_step(p, goal, me["stats"]):
                return goal
        elif self.clear_grid(p, dest_xy) and not stuck:
            self.search, self.path = None, []
            return goal

        replaced = self.search_goal is None or math.dist(dest, self.search_goal) > 3
        if now >= self.plan_again_at and (replaced or stuck or (self.search is None and not self.path)):
            start = self.nearest_cell(p)
            if start is not None:
                self.search = Search(self.arena, start, dest)
                self.search_goal = dest
                if replaced or stuck:
                    self.path = []
                self.plan_again_at = now + .7

        if self.search is not None:
            before = self.search.visited
            done = self.search.advance(min(deadline, perf_counter_ns() + 1_350_000))
            self.expansions += self.search.visited - before
            if done:
                if self.search.result:
                    self.path = [self.arena.center(cell) for cell in self.search.result]
                    self.waypoint = 0
                    self.completed_routes += 1
                self.search = None

        while self.waypoint < len(self.path) and distance(p, self.path[self.waypoint]) < 5:
            self.waypoint += 1
        for point in reversed(self.path[self.waypoint:self.waypoint + 4]):
            if self.clear_grid(p, point) and self.arena.ground_step(p, point, me["stats"]):
                return point
        if self.waypoint >= len(self.path):
            self.path = []
        return dest_xy if distance(dest_xy, goal) > self.arena.cell else goal
