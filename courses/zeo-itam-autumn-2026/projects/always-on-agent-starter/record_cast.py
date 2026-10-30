"""Record a command's real terminal output as an asciinema v2 cast, using only the Python standard library.

    python3 record_cast.py out.cast python3 demo_scenes.py 2

The command runs in a pseudo terminal, so it prints exactly what it prints in a real terminal. Each chunk of output is
written with the time it arrived. Nothing is added, removed or retimed. This is not the asciinema program, but its
files play in any asciinema player.
"""
import json
import os
import pty
import select
import sys
import time


def record(path, command, width=100, height=28):
    started = time.time()
    header = {"version": 2, "width": width, "height": height, "timestamp": int(started),
              "title": " ".join(command), "env": {"SHELL": "/bin/sh", "TERM": "xterm-256color"}}
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.update(COLUMNS=str(width), LINES=str(height), TERM="xterm-256color", PYTHONUNBUFFERED="1")
        os.execvp(command[0], command)
    with open(path, "w") as out:
        out.write(json.dumps(header) + "\n")
        while True:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if ready:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                out.write(json.dumps([round(time.time() - started, 6), "o", data.decode("utf8", "replace")]) + "\n")
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


if __name__ == "__main__":
    sys.exit(record(sys.argv[1], sys.argv[2:]))
