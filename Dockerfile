# PROD-008: conda-forge base, not a pip-on-slim-Python approach -- rasterio/
# fiona/pyproj/geopandas all bundle mutually-dependent GDAL/PROJ/GEOS binary
# versions that conda-forge's solver reconciles; a pip+apt mix risks a subtly
# broken combination that only fails at runtime, not at build time.
FROM condaforge/miniforge3:latest

WORKDIR /app

# Solve and create the environment first, as its own layer, so an
# environment.yaml-only change doesn't invalidate the (slow) dependency
# solve on every source-code change below.
COPY environment.yaml ./
RUN mamba env create -f environment.yaml && mamba clean --all --yes

# Mirrors ci.yml's exact install invocation, so the same command that's
# validated in CI is what actually ships.
COPY . .
RUN conda run -n wia-hazard-pipelines python -m pip install -e . --no-build-isolation

# data/ and outputs/ are bind-mounted at run time (no object-storage support
# exists in this codebase to do otherwise -- see docs/data-sources.md);
# CDS/EWDS credentials are injected as a mounted secret file, never baked
# into the image:
#   docker run --rm \
#     -v "$(pwd)/data:/app/data" \
#     -v "$(pwd)/outputs:/app/outputs" \
#     -v "$HOME/.cdsapirc:/root/.cdsapirc:ro" \
#     -v "$HOME/.ewdsapirc:/root/.ewdsapirc:ro" \
#     wia-hazard-pipelines run-flood --iso3 KEN --as-of-date 2025-12-31
ENTRYPOINT ["conda", "run", "--no-capture-output", "-n", "wia-hazard-pipelines", "python", "-m", "wia_pipelines.cli"]
CMD ["--help"]
