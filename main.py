"""Read newline-delimited mechfight/1 input and answer the newest observation."""
import json
import os
import select
import sys

from routing import Bot


def messages():
    pending = b""
    while True:
        data = os.read(0, 65536)
        if not data:
            return
        pending += data
        while select.select([0], [], [], 0)[0]:
            data = os.read(0, 65536)
            if not data:
                break
            pending += data
        *lines, pending = pending.split(b"\n")
        yield lines
        if not data:
            return


def send(message):
    sys.stdout.write(json.dumps(message, separators=(",", ":"), allow_nan=False) + "\n")
    sys.stdout.flush()


def main():
    bot = None
    for batch in messages():
        latest = None
        for line in batch:
            if not line:
                continue
            message = json.loads(line)
            kind = message.get("type")
            if kind == "hello":
                bot = Bot(message)
                send({"type": "ready", "name": bot.name})
            elif kind == "obs":
                latest = message
            elif kind == "end":
                return
        if latest is not None and bot is not None:
            send(bot.act(latest))


if __name__ == "__main__":
    main()
