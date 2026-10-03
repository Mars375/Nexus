"""Nexus — centre de contrôle de Loïc et de ses agents."""


def main() -> None:
    """Lance Nexus (NEXUS_HOST / NEXUS_PORT)."""
    import uvicorn

    from nexus.app import create_app
    from nexus.config import Settings
    from nexus.logs import uvicorn_log_config

    settings = Settings.from_env()
    # Journal d'accès d'uvicorn coupé : il recopie les URL reçues (ADR-006) ; Nexus écrit le sien.
    uvicorn.run(
        create_app(settings), host=settings.host, port=settings.port,
        access_log=False, log_config=uvicorn_log_config(),
    )


def dev() -> None:
    """Lance Nexus avec rechargement automatique, sur le même port que le proxy Vite."""
    import uvicorn

    from nexus.config import Settings
    from nexus.logs import uvicorn_log_config

    settings = Settings.from_env()
    uvicorn.run(
        "nexus.app:create_app",
        factory=True,
        reload=True,
        host=settings.host,
        port=settings.port,
        access_log=False,
        log_config=uvicorn_log_config(),
    )
