"""Adjust Mech Royale combat posture using public observation features."""

import math

from adaptive_combat import Bot as AdaptiveCombat
from bot import clamp, distance


class Bot(AdaptiveCombat):
    name = "codec-combat-posture"
    weights = (.630, -.517, .677, .320, -.433, -.533, .314)

    def cover_for_matchup(self, obs, threats):
        ordinary = super().cover_for_matchup(obs, threats)
        if not threats:
            return ordinary
        me = obs["self"]
        p = me["pos"]
        rival = threats[0]
        gap = distance(p, rival["pos"])
        if gap > 150.:
            return ordinary
        hp = me["hp"] / me["max_hp"]
        held, _ = self.loadout(me)
        gun = me["weapons"][held["gun"]] if "gun" in held else None
        close = sum(distance(p, foe["pos"]) < 105. for foe in threats[:3])
        features = (1.,
                    1. if obs.get("alive", 16) > 13 else -.45,
                    1. - 1.65 * hp,
                    1. if close > 1 else -.4,
                    clamp((rival.get("hp", 1400.) - me["hp"]) / 700., -1., 1.),
                    1. if gun and (gun.get("reload", 0.) > .4 or gun.get("ammo", 0) < 2) else -.2,
                    1. if obs["t"] - self.last_damage < 1.6 else -.3)
        exponent = sum(a * b for a, b in zip(features, self.weights))
        return clamp(ordinary * math.exp(clamp(exponent, -1.9, 1.4)), .23, 9.)
