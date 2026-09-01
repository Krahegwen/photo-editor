import os

import uvicorn


def main() -> None:
    port = int(os.environ.get("PHOTOED_PORT", "8177"))
    uvicorn.run("photoeditor.api:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
