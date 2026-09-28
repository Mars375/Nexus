"""Nexus — centre de contrôle de Loïc et de ses agents."""


def main() -> None:
    import uvicorn

    from nexus.app import create_app
    from nexus.config import Settings

    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
