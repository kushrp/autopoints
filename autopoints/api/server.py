from __future__ import annotations

import uvicorn


def run() -> None:
    uvicorn.run(
        "autopoints.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    run()
