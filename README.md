# codec Mech Royale control

Gun lead with velocity damping, torso-aware shot gating, and direct circle rotation with stall recovery.

Build from this directory with the root Dockerfile.

```sh
docker build --platform linux/amd64 -t codec-mech:control .
```

The process reads mechfight/1 observations from stdin and writes one JSON action per decision to stdout. The event supplies the arena at `/arena`. The image starts as UID 65534 and uses Python 3.13 with the standard library.

## Attribution

Team codec wrote the transport, policy, and navigation code. The [Builders protocol and bot kit](https://www.joinbuilders.org/buildathon/tracks/builders) specify the wire format and supplied the map and checker used in testing. Arena assets come from the scorer mount. The source is available under the MIT License.
