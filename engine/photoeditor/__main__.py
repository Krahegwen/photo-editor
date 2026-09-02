import os

import uvicorn


def main() -> None:
    from . import config

    port = int(os.environ.get("PHOTOED_PORT", "8177"))
    # Por defecto solo loopback (la API no tiene autenticación). Para el móvil
    # en red local: PHOTOED_HOST=0.0.0.0 o "host": "0.0.0.0" en config.json.
    host = os.environ.get("PHOTOED_HOST") or config._file_config().get("host") or "127.0.0.1"
    uvicorn.run("photoeditor.api:app", host=host, port=port)


if __name__ == "__main__":
    main()
