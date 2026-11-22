"""In-game mortar support for mechfight/1."""

import math
from time import perf_counter_ns

from bot import angle_delta, distance
from practice import Bot as Economy

WEAPON_VALUE = {"mortar": 1, "lightning": 2, "laser": 3}


def arcs(origin, destination, velocity, shell, offset, limit):
    """Return approximate Mech Royale arc solutions in order of travel time."""
    dx, dy, dz = (target - start for target, start in zip(destination,origin))
    vx,vy,vz = velocity
    gravity, speed = shell["gravity"], shell["speed"]

    def displacement(time):
        return dx+vx*time,dy+vy*time,dz+vz*time+gravity*time*time*.5

    def error(time):
        return math.hypot(*displacement(time))-(speed*time+offset)

    low=.10
    previous=error(low)
    for n in range(1,33):
        sample=.10+(limit-.10)*n/32
        upper=error(sample)
        if previous*upper <= 0.:
            a,b,sign=low,sample,previous
            for _ in range(14):
                mid=(a+b)*.5
                if error(mid)*sign>0:
                    a=mid
                else:
                    b=mid
            time=(a+b)*.5
            diff=displacement(time)
            norm=math.hypot(*diff)
            if norm:
                yield time, tuple(c/norm for c in diff)
        low,previous=sample,upper


def shell_point(origin, unit, velocity, gravity, offset, t):
    span=offset+velocity*t
    return (origin[0]+unit[0]*span, origin[1]+unit[1]*span,
            origin[2]+unit[2]*span-gravity*t*t*.5)


class Bot(Economy):
    name = "codec-bombard"

    def weapon_value(self, me):
        return WEAPON_VALUE

    def mortar_aim(self, me, target, weapon):
        body=me["stats"]
        source=(*me["pos"][:2],me["pos"][2]+body["height"]+.5)
        size=1+target.get("cubes",0)*self.size_per_cube
        height=self.base_height*size if target["kind"]=="mech" else self.config["crates"]["height"]
        aim_at=(*target["pos"][:2],target["pos"][2]+height*.40)
        velocity=target.get("vel",(0.,0.,0.))
        # Long extrapolation magnifies late movement changes in the game.
        velocity=tuple(.73*v for v in velocity)
        shell=weapon["stats"]
        offset=body["radius"]+.5
        separation=math.dist(source,aim_at)
        minimum=max(17.,shell["splash_radius"]+8.)
        if separation < minimum or separation > 178.:
            return None
        limit = 6.85 if math.hypot(*velocity) < 3 else 3.5
        for seconds,unit in arcs(source,aim_at,velocity,shell,offset,min(shell["ttl"]-.10,limit)):
            pitch=math.asin(unit[2])
            yaw=math.atan2(unit[1],unit[0])
            if not body["min_pitch"] <= pitch <= body["max_pitch"]:
                continue
            count=max(4,math.ceil(seconds/.18))
            segments=[source]+[
                shell_point(source,unit,shell["speed"],shell["gravity"],offset,seconds*i/count)
                for i in range(count+1)
            ]
            clear=True
            for a,b in zip(segments,segments[1:]):
                if perf_counter_ns()>=self.fire_deadline or not self.arena.clear(a,b):
                    clear=False
                    break
            if clear:
                return (yaw,pitch), separation
        return None

    def fire(self,obs,action,threats,urgent):
        super().fire(obs,action,threats,urgent)
        me=obs["self"]
        held,_=self.loadout(me)
        if "mortar" not in held or urgent or perf_counter_ns()>=self.fire_deadline:
            return
        p=me["pos"]
        hp=me["hp"]/me["max_hp"]
        if hp<.66 and obs["t"]-self.last_damage>.9 and (
            not threats or distance(p,threats[0]["pos"])>75
        ):
            return
        slot=held["mortar"]
        shell=me["weapons"][slot]
        if shell["cooldown"]>.25:
            return
        ranked=sorted(threats,key=lambda entity:distance(p,entity["pos"])+.012*entity.get("hp",1400))
        if not ranked and self.objective and self.objective.kind=="crate":
            ranked=[
                {**crate,"kind":"crate"} for crate in obs.get("crates",())
                if crate["id"]==self.last_selected and crate["hp"]>90
            ]
        for target in ranked[:3]:
            if perf_counter_ns()>=self.fire_deadline:
                return
            support=self.mortar_aim(me,target,shell)
            if support is None:
                continue
            aim,span=support
            tolerance=math.atan2(max(2.,shell["stats"]["splash_radius"]*.40),max(1.,span))
            if ("gun" in held and (abs(angle_delta(aim[0],action["aim"][0]))>tolerance or
                                   abs(aim[1]-action["aim"][1])>tolerance)):
                action["fire"][held["gun"]]=False
            action["aim"]=list(aim)
            action["fire"][slot]=shell["cooldown"]<=self.interval and self.aim_window(
                me,aim,tolerance,tolerance)
            return
