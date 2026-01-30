from __future__ import annotations

from pathlib import Path

import typer

from wia_hazard_impacts.config import load_config

app = typer.Typer(add_completion=False)


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", exists=True, readable=True, help="Path to YAML config"),
):
    """Run a hazard pipeline based on a YAML config.

    For now this is a scaffold; we will wire hazards into a dispatch table next.
    """

    cfg = load_config(config)

    typer.echo(f"Loaded config for {cfg.iso3} | {cfg.hazard.name} | {cfg.window.start} to {cfg.window.end}")
    typer.echo("Pipeline dispatch is not yet implemented in this scaffold.")
    raise typer.Exit(code=2)


def main():
    app()


if __name__ == "__main__":
    main()
