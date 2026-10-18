"""Nexus — centre de contrôle de Loïc et de ses agents."""


def main() -> None:
    """Run Nexus on the addresses of NEXUS_HOST and the port NEXUS_PORT (ADR-021)."""
    import asyncio
    import logging
    import sys

    import uvicorn
    from uvicorn.server import STARTUP_FAILURE

    from nexus import serving
    from nexus.app import create_app
    from nexus.config import Settings
    from nexus.logs import uvicorn_log_config

    settings = Settings.from_env()
    # Journal d'accès d'uvicorn coupé : il recopie les URL reçues (ADR-006) ; Nexus écrit le sien.
    config = uvicorn.Config(
        create_app(settings), port=settings.port, access_log=False,
        log_config=uvicorn_log_config(),
    )
    # What `uvicorn.run` does around `Server.run`: it relaunches SIGINT after the shutdown,
    # which then surfaces here as a KeyboardInterrupt and means a clean exit.
    try:
        started = asyncio.run(
            serving.serve(config, settings), loop_factory=config.get_loop_factory()
        )
    except KeyboardInterrupt:
        return
    except serving.LoopbackBindError as exc:
        # Written the way `Server.startup` writes a failed bind; the loopback address is fine.
        logging.getLogger("uvicorn.error").error(exc.__cause__)
        sys.exit(STARTUP_FAILURE)
    if not started:
        sys.exit(STARTUP_FAILURE)


def dev() -> None:
    """Lance Nexus avec rechargement automatique, sur le même port que le proxy Vite."""
    import uvicorn

    from nexus.config import Settings
    from nexus.logs import uvicorn_log_config

    settings = Settings.from_env()
    if settings.tailnet_host is not None:
        raise SystemExit(
            "nexus-dev n'écoute que la boucle locale : retire l'adresse du tailnet de "
            "NEXUS_HOST, ou lance nexus (ADR-021)"
        )
    uvicorn.run(
        "nexus.app:create_app",
        factory=True,
        reload=True,
        host=settings.loopback_host,
        port=settings.port,
        access_log=False,
        log_config=uvicorn_log_config(),
    )
