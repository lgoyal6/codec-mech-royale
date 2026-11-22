"""Choose movement by forecasting incoming and outgoing lines of fire."""

import math
from time import perf_counter_ns

from bot import advance, angle_delta, clamp, direction, distance, heading
from staged_supply import Bot as StagedSupply


class Bot(StagedSupply):
    name = "codec-combat-horizon"
    cover_weight = 1.2

    def horizon_move(self, obs, goal, threats, urgent):
        me, zone, now = obs["self"], obs["zone"], obs["t"]
        p, body = me["pos"], me["stats"]
        if (urgent or not me["grounded"] or not threats or goal.kind == "drop"
                or (goal.kind in ("cube","pickup") and distance(p, goal.point) < 17.)):
            return None
        active = [foe for foe in threats[:4] if distance(p, foe["pos"]) < 155.]
        if not active or self.projectile_risk(obs):
            return None
        hp = me["hp"] / me["max_hp"]
        held, _ = self.loadout(me)
        laser = me["weapons"][held["laser"]] if "laser" in held else None
        charge = laser and laser.get("charge",0.)
        nearest = distance(p, active[0]["pos"])
        boost = me["energy"] > 42. and not charge and (nearest < 67. or now-self.last_damage < 1.25)
        desired_range = 37. if "lightning" in held and me["energy"] > 26. else 72.
        speed = body["boost_speed"] if boost else body["walk_speed"]
        if charge:
            speed *= body["charge_move_mult"]
        vx,vy = me["vel"][:2]
        initial_eye = self.muzzle(me)
        targets = []
        for foe in active:
            q = foe["pos"]
            velocity = foe.get("vel",(0.,0.,0.))
            dz = self.base_height * (1.+foe.get("cubes",0)*self.size_per_cube) * .5
            current = (q[0],q[1],q[2]+dz)
            predicted = tuple(coord + .48 * v for coord,v in zip(current,velocity))
            if not self.arena.clear(current,predicted):
                predicted = current
            facing = abs(angle_delta(heading(q,p),foe["aim"][0]))
            pressure = 1. if facing < .66 else .60
            if foe.get("charging") and facing < .56:
                pressure *= 1.7
            if not self.arena.clear(current,initial_eye):
                pressure *= .82
            targets.append((foe,predicted,pressure))

        guide = self.route_to(obs,goal.point,False,self.move_deadline-2_200_000)
        towards = heading(p,guide)
        old_gap = distance(p,guide)
        weights = self.cover_weight * (1.8 if hp < .62 else 1.)
        leads = (0., .78, -.78, 1.57, -1.57, 2.35, -2.35, math.pi)
        best = None
        for offset in (*leads,None):
            if best is not None and perf_counter_ns() >= self.move_deadline - 250_000:
                break
            if offset is None:
                dx,dy = 0.,0.
            else:
                dx,dy = direction(towards+offset)
            seconds = .70
            ramp = min(.42,math.hypot(dx*speed-vx,dy*speed-vy)/body["ground_accel"])
            x = p[0]+dx*speed*(seconds-ramp/2)+vx*ramp/2
            y = p[1]+dy*speed*(seconds-ramp/2)+vy*ramp/2
            q = x,y
            if (distance(q,zone["center"])+8. > zone["radius"]
                    or not self.arena.ground_step(p,q,body)):
                continue
            eye = (*q,self.arena.height(*q)+body["muzzle_height"])
            danger = attack = 0.
            for foe,target,pressure in targets:
                gap = distance(q,target)
                if not self.arena.clear(eye,target):
                    continue
                danger += pressure * clamp((164.-gap)/132.,.15,1.12)
                quality = clamp(1.-abs(gap-desired_range)/115., .10, 1.)
                if foe.get("hp",1400.) < 440.:
                    quality *= 1.3
                attack = max(attack,quality)
            progress = old_gap-distance(q,guide)
            margin = zone["next_radius"]-distance(q,zone["next_center"])
            score = .11*progress + (2.3 if hp >= .62 else 1.25)*attack - weights*danger
            score -= .10*max(0.,13.-margin)
            if best is None or score > best[0]:
                best = score,(dx,dy)
        if best is None:
            return None
        return best[1], boost and best[1] != (0.,0.), False

    def steer(self, obs, goal, threats, urgent, holding):
        choice = self.horizon_move(obs,goal,threats,urgent)
        return choice if choice is not None else super().steer(obs,goal,threats,urgent,holding)


class Defensive(Bot):
    name = "codec-defensive-horizon"
    cover_weight = 2.6
