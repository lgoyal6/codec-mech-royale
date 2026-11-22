"""Press favorable exchanges and hide from overlapping fire."""

from bot import angle_delta, distance, heading
from collision_evasion import Bot as CollisionEvasion


class Bot(CollisionEvasion):
    name = "codec-adaptive-combat"

    def horizon_move(self, obs, goal, threats, urgent):
        self.cover_weight = self.cover_for_matchup(obs, threats)
        return super().horizon_move(obs, goal, threats, urgent)

    def cover_for_matchup(self, obs, threats):
        if not threats:
            return 2.6
        me = obs["self"]
        p = me["pos"]
        hp = me["hp"] / me["max_hp"]
        rival = threats[0]
        span = distance(p, rival["pos"])
        if span > 157.:
            return 2.6

        clear_fighters = 0
        for threat in threats[:4]:
            if distance(p, threat["pos"]) > 146.:
                break
            aim = abs(angle_delta(heading(threat["pos"], p), threat["aim"][0]))
            if aim < .92 and self.arena.clear(self.muzzle(me), self.direct_aim(me, threat)[0]):
                clear_fighters += 1
        if clear_fighters >= 2:
            return 5.1 if hp < .72 else 3.9
        if hp < .46:
            return 4.2

        held, _ = self.loadout(me)
        enemy = rival.get("weapons", ())
        wounded = rival.get("hp", 1400.) < .82 * me["hp"]
        counter = ("laser" in held and "mortar" in enemy
                   or "lightning" in held and "laser" in enemy and span < 52. and me["energy"] > 30.)
        if hp >= .61 and clear_fighters < 2 and (wounded or counter):
            return .78
        return 2.6
