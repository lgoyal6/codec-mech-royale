# codec Mech Royale roof guard

The bot uses bounded route recovery, energy-aware movement, and nearby loot and repair objectives. It retains its arm gun and can equip a laser, lightning, or mortar weapon. The mortar policy checks its intended arc against the arena geometry. The bot can also use short jet climbs for accessible rooftop pickups and blocked rotations. It releases the laser early when the charge is sufficient for a finishing shot. The opening looks for a short climb to a reachable roof within the upcoming circle.

Build from this directory with the root Dockerfile.

```sh
docker build --platform linux/amd64 -t codec-mech:roofguard .
```

The process reads mechfight/1 observations from stdin and writes one JSON action per decision to stdout. The event supplies the arena at `/arena`. The image starts as UID 65534 and uses Python 3.13 with the standard library.

## Attribution

Team codec wrote the transport, policy, and navigation code. The [Builders protocol and bot kit](https://www.joinbuilders.org/buildathon/tracks/builders) specify the wire format and supplied the map and checker used in testing. Arena assets come from the scorer mount. The source is available under the MIT License.
