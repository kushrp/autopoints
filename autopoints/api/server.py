from __future__ import annotations

import os

import uvicorn


def run() -> None:
    uvicorn.run(
        "autopoints.api.main:app",
        host=os.getenv("AUTOPOINTS_HOST", "127.0.0.1"),
        port=int(os.getenv("AUTOPOINTS_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
