"""
Entrypoint that reads PORT directly in Python instead of passing --port on the
command line. Whether the platform invokes this via a shell, execs it directly, or
overrides the start command in a dashboard, there's no "$PORT" string left for
anything to fail to substitute — os.environ always resolves it correctly.
"""
import os

import uvicorn

if __name__ == "__main__":
    port_raw = os.environ.get("PORT", "8000")
    try:
        port = int(port_raw)
    except ValueError:
        print(f"WARNING: PORT env var was {port_raw!r} (not an integer) — falling back to 8000.")
        port = 8000

    print(f"Starting uvicorn on 0.0.0.0:{port} (PORT env var was {port_raw!r})")
    uvicorn.run("server:app", host="0.0.0.0", port=port)
