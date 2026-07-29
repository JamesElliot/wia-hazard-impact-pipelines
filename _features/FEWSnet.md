FEWS NET Data Integration Exploratory Project Specification

1. Project title

FEWS NET Data Integration Feasibility Study for the WASH Insecurity Analysis

2. Project purpose

This project will assess, document and prototype the use of FEWS NET as a data provider for the WASH Insecurity Analysis.

The work will determine:

* which FEWS NET datasets are available through public or authenticated interfaces;
* their geographic, temporal and thematic coverage;
* their relevance to existing or proposed WIA indicators and analytical modules;
* their licensing, attribution and redistribution conditions;
* the technical requirements for automated ingestion;
* the feasibility of harmonising FEWS NET data to WIA Admin2 units;
* whether selected datasets should proceed to operational integration.

The project is exploratory. It must produce working evidence about data availability and API behaviour rather than relying only on documentation or assumptions.

The initial priority datasets are:

1. acute food-insecurity classifications;
2. acutely food-insecure population estimates;
3. market prices;
4. cross-border trade;
5. crop-production data, where accessible;
6. FEWS NET geographic reference units and livelihood zones;
7. selected USGS FEWS NET environmental datasets, especially runoff, soil moisture and rainfall.

The project must not assume that every dataset available through FEWS NET can be freely stored, transformed or redistributed. Licensing must be assessed at dataset and source-document level.

⸻

3. WIA context

The WASH Insecurity Analysis is a subnational analytical framework used to identify and compare WASH insecurity within countries.

The WIA operates primarily at Admin2 level and combines indicators across four dimensions:

1. WASH service access;
2. hazard impact;
3. hazard exposure;
4. WASH-related vulnerability.

Indicators are generally expressed as proportions, rates, categorical classifications or spatially aggregated measures. The WIA is intended to support national and subnational prioritisation rather than direct comparison between countries.

FEWS NET may contribute to the WIA in several ways:

* food-security vulnerability indicators;
* contextual validation of WIA findings;
* market-stress and affordability analysis;
* agricultural and livelihood analysis;
* drought-impact analysis;
* anticipatory or risk-monitoring modules;
* spatial reference data, including livelihood zones and food-security analysis areas.

FEWS NET data may use geographic units that do not correspond directly to WIA Admin2 boundaries. These can include:

* Admin1;
* Admin2;
* livelihood zones;
* food-security analysis areas;
* intersections between administrative units and livelihood zones;
* markets;
* border points;
* camps;
* other FEWS NET geographic units.

The project must therefore treat geographic harmonisation as a core workstream rather than a minor post-processing step.

⸻

4. Project objectives

4.1 Primary objective

Determine whether FEWS NET can provide reliable, automatable and legally usable data inputs for the WIA.

4.2 Specific objectives

The project will:

1. create a reproducible inventory of FEWS NET datasets, endpoints, metadata and source documents;
2. document authentication, filtering, pagination, output formats and API limitations;
3. quantify geographic and temporal coverage for selected WIA countries;
4. identify data-series units, scenarios, forecast vintages and methodological distinctions;
5. assess licensing and attribution requirements;
6. build a reusable Python API client;
7. build prototype extraction pipelines for selected datasets;
8. retrieve and store FEWS NET geographic units;
9. test harmonisation to WIA Admin2 boundaries;
10. test ingestion of selected USGS FEWS NET raster products;
11. produce a feasibility assessment and recommendations for operational integration.

⸻

5. Core research questions

The project must answer the following questions.

5.1 Data availability

* What public API endpoints are available?
* Which datasets require authentication?
* Which datasets appear in the Data Explorer but not in the documented API?
* Which datasets appear in the API but not in the Data Explorer?
* What metadata are available for datasets, source documents, collections, series and observations?
* Are crop production, nutrition, response and demographic data accessible through documented or discoverable endpoints?
* Are historical records available?
* Are historical values revised?

5.2 Coverage

For each target dataset:

* Which countries are covered?
* What is the earliest and latest observation?
* What is the update frequency?
* What geographic level is used?
* How many WIA Admin2 units can be represented directly or indirectly?
* Are there major missing periods?
* Is coverage current?
* Is the dataset based on FEWS NET analysis or third-party source data?

5.3 Technical access

* What authentication method is required?
* How are tokens requested and refreshed?
* What pagination model is used?
* What request parameters and field filters are supported?
* What temporal aggregation is applied by default?
* What rate limits or practical request constraints exist?
* What errors are returned?
* Are responses stable enough for production ingestion?
* Can data be accessed in JSON, CSV, GeoJSON or other machine-readable formats?

5.4 Geographic interoperability

* How are FEWS NET geographic units identified?
* How stable are fnid identifiers?
* How are historical boundaries represented?
* How are parent, child, predecessor and successor relationships represented?
* Which FEWS NET units correspond directly to WIA Admin2?
* Where spatial intersection is required, what allocation rule is appropriate?
* Can classification areas be transferred to Admin2 using population-weighted overlap?
* What uncertainty should be recorded?

5.5 Licensing

* What rights apply to each source document and data series?
* Is automated retrieval permitted?
* Is internal storage permitted?
* Is transformation permitted?
* Is publication of derived Admin2 indicators permitted?
* Is redistribution of raw values permitted?
* What attribution wording is required?
* Which datasets derive from proprietary or restricted sources?
* Which licence conditions are unclear and require written clarification?

5.6 WIA relevance

* Which datasets map to existing WIA indicators?
* Which datasets could support proposed modules?
* Which datasets are better suited to contextual analysis than formal scoring?
* Which datasets should not be used because their construct, coverage or methodology is unsuitable?
* What additional methodological work would be required before adoption?

⸻

6. Initial datasets and endpoint families

The following endpoint families should be investigated first. Endpoint names must be verified against the live API and current documentation.

6.1 Acute food-insecurity classifications

Likely endpoint family:

ipcphase

Related metadata or series endpoint:

ipcclassification

Important fields may include:

* country;
* FEWS NET geographic identifier;
* phase;
* scenario;
* start date;
* end date;
* collection date;
* publication or issue date;
* source organisation;
* source document;
* analytical framework;
* value;
* data-series identifier.

Relevant scenario codes may include:

* CS: current situation;
* ML1: near-term projection;
* ML2: medium-term projection.

The project must verify the meaning of each code using current metadata and documentation.

6.2 Acutely food-insecure population estimates

Likely endpoint family:

ipcpopulationsize

Related metadata or series endpoint:

ipcpopulation

Important distinctions include:

* absolute population;
* percentage of population;
* phase-specific population;
* population in Phase 3 or worse;
* current versus projected estimates;
* denominator source;
* issue date;
* scenario;
* source analytical framework.

Potential scenario codes may include:

* CS;
* FIPE6.

These codes must be verified rather than hard-coded based only on prior documentation.

6.3 Market prices

Likely endpoint family:

marketpricefacts

Related series or product endpoint:

marketproduct

Important dimensions include:

* market;
* geographic coordinates;
* commodity;
* commodity classification;
* local or imported status;
* retail, wholesale, producer or other price type;
* currency;
* unit;
* reporting period;
* source organisation;
* source document.

The project should prioritise staple-food products and, where available, wage series.

6.4 Cross-border trade

Likely endpoint family:

tradeflowquantityvalue

Related series endpoint:

tradeflowquantity

Important dimensions include:

* origin;
* destination;
* reporting country;
* border point;
* commodity;
* formal or informal trade;
* quantity;
* value;
* currency;
* reporting period.

6.5 Geographic data

Investigate endpoints providing:

* geographic-unit metadata;
* GeoJSON or other geometry;
* livelihood zones;
* markets;
* food-security analysis areas;
* administrative hierarchy;
* geographic relationships;
* historical boundary records.

The project should identify the preferred endpoint for retrieving:

* current geographic units;
* historical geographic units;
* spatial geometry;
* parent-child relationships;
* predecessor-successor relationships;
* geographic-unit type.

6.6 Additional structured datasets

Search the API and metadata for:

* crop production;
* planted area;
* harvested area;
* yield;
* nutrition;
* humanitarian response;
* population;
* demographics;
* livelihoods;
* agricultural calendars;
* seasonal classifications.

Do not assume these datasets have equivalent public API support. Record whether they are:

* publicly accessible;
* authenticated;
* restricted;
* documented;
* undocumented but discoverable;
* visible only through the Data Explorer;
* unavailable.

6.7 USGS FEWS NET raster products

Investigate at least:

* CHIRPS rainfall;
* runoff;
* soil moisture;
* Water Requirement Satisfaction Index;
* evapotranspiration;
* NDVI;
* land-surface temperature.

Priority should be given to:

1. runoff;
2. soil moisture;
3. CHIRPS rainfall.

The project must identify:

* catalogue structure;
* file naming conventions;
* download URLs;
* file formats;
* spatial resolution;
* temporal resolution;
* projection;
* nodata values;
* units;
* geographic extent;
* update latency;
* licence and attribution requirements;
* whether automated bulk download is permitted.

⸻

7. Initial country scope

The first coverage audit should prioritise countries already completed, underway or anticipated in the WIA.

Initial country list:

Afghanistan
Benin
Burkina Faso
Central African Republic
Democratic Republic of the Congo
El Salvador
Grenada
Haiti
Honduras
Kenya
Lebanon
Mali
Niger
Saint Vincent and the Grenadines
South Sudan
Togo
Yemen

Country identifiers should be stored using:

* ISO 3166-1 alpha-2;
* ISO 3166-1 alpha-3;
* FEWS NET country identifier, where applicable;
* official country name;
* WIA internal country identifier, where available.

The implementation should make the country list configurable rather than embedding it in extraction logic.

⸻

8. Deliverables

The project must produce the following deliverables.

8.1 Dataset inventory

A machine-readable dataset catalogue containing:

* endpoint;
* dataset name;
* source organisation;
* source-document identifier;
* series identifier;
* thematic category;
* country coverage;
* geographic level;
* earliest date;
* latest date;
* number of observations;
* update frequency;
* units;
* scenarios;
* access type;
* licence status;
* attribution requirement;
* redistribution status;
* notes.

Preferred formats:

outputs/catalogue/fewsnet_dataset_catalogue.parquet
outputs/catalogue/fewsnet_dataset_catalogue.csv

8.2 Country coverage audit

For every selected dataset and country:

* record count;
* number of unique geographic units;
* earliest and latest observation;
* most recent collection date;
* expected and observed temporal frequency;
* missing periods;
* percentage of current WIA Admin2 units covered directly;
* percentage coverable through spatial allocation;
* source organisations;
* licence status.

Preferred outputs:

outputs/coverage/country_dataset_coverage.parquet
outputs/coverage/country_dataset_coverage.csv
outputs/coverage/coverage_summary.md

8.3 API client

A reusable Python client supporting:

* unauthenticated access;
* authenticated access;
* JWT retrieval;
* token refresh or re-authentication;
* pagination;
* retry logic;
* explicit timeouts;
* structured logging;
* configurable page size;
* JSON response handling;
* CSV response handling where appropriate;
* field filtering;
* temporal schedule parameters;
* raw-response persistence;
* test fixtures.

8.4 Prototype ingestion pipelines

Working pipelines for:

1. food-insecurity classifications;
2. food-insecure population estimates;
3. market prices;
4. FEWS NET geography;
5. one selected environmental raster product.

Cross-border trade should be added if access and coverage are sufficient during the exploratory phase.

8.5 Geography crosswalk prototype

A prototype table linking FEWS NET geographic units to WIA Admin2 units.

Required fields:

fewsnet_fnid
fewsnet_name
fewsnet_unit_type
fewsnet_geometry_version
wia_country_id
wia_admin2_id
wia_admin2_name
match_method
area_overlap_fraction
population_overlap_fraction
match_confidence
review_required
notes

8.6 Licensing register

A dataset-level licensing register containing:

provider
dataset
endpoint
source_document_id
source_organisation
licence_name
licence_url
attribution_text
automated_access_permitted
internal_storage_permitted
transformation_permitted
raw_redistribution_permitted
derived_redistribution_permitted
commercial_restriction
access_restriction
licence_checked_at
review_status
notes

Unknown values must be represented explicitly as unknown, not assumed to be permitted.

8.7 Feasibility report

A final report covering:

* datasets assessed;
* live API behaviour;
* coverage;
* geographic interoperability;
* licensing;
* data quality;
* prototype results;
* operational risks;
* recommended datasets;
* rejected or deferred datasets;
* recommended next phase;
* questions requiring confirmation from FEWS NET or USGS.

Preferred output:

outputs/reports/fewsnet_wia_feasibility_report.md

8.8 Reproducible run instructions

Provide:

* environment setup;
* credential setup;
* commands to run each stage;
* test commands;
* expected outputs;
* troubleshooting guidance;
* data-cleaning instructions;
* notes on restricted data.

⸻

9. Proposed repository structure

fewsnet-wia-exploration/
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── Makefile
├── config/
│   ├── countries.yml
│   ├── datasets.yml
│   ├── logging.yml
│   └── licences.yml
├── docs/
│   ├── project-specification.md
│   ├── fewsnet-platform-overview.md
│   ├── api-notes.md
│   ├── geographic-harmonisation.md
│   ├── licensing-notes.md
│   ├── indicator-relevance.md
│   └── decisions/
│       └── README.md
├── src/
│   └── fewsnet_wia/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── logging.py
│       ├── exceptions.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── auth.py
│       │   ├── pagination.py
│       │   ├── schemas.py
│       │   └── endpoints.py
│       ├── extract/
│       │   ├── __init__.py
│       │   ├── classifications.py
│       │   ├── populations.py
│       │   ├── market_prices.py
│       │   ├── trade.py
│       │   ├── geography.py
│       │   ├── metadata.py
│       │   └── usgs_rasters.py
│       ├── transform/
│       │   ├── __init__.py
│       │   ├── common.py
│       │   ├── classifications.py
│       │   ├── populations.py
│       │   ├── market_prices.py
│       │   ├── geography.py
│       │   └── rasters.py
│       ├── coverage/
│       │   ├── __init__.py
│       │   ├── audit.py
│       │   ├── temporal.py
│       │   ├── geographic.py
│       │   └── reporting.py
│       ├── geography/
│       │   ├── __init__.py
│       │   ├── crosswalk.py
│       │   ├── matching.py
│       │   ├── overlay.py
│       │   ├── population_weights.py
│       │   └── validation.py
│       ├── licensing/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   ├── rules.py
│       │   └── validation.py
│       ├── storage/
│       │   ├── __init__.py
│       │   ├── raw.py
│       │   ├── parquet.py
│       │   ├── database.py
│       │   └── manifests.py
│       └── reports/
│           ├── __init__.py
│           ├── catalogue.py
│           ├── coverage.py
│           └── feasibility.py
├── scripts/
│   ├── inspect_api.py
│   ├── build_catalogue.py
│   ├── run_coverage_audit.py
│   ├── download_geographies.py
│   ├── build_crosswalk.py
│   ├── download_usgs_product.py
│   └── generate_report.py
├── notebooks/
│   ├── 01_api_discovery.ipynb
│   ├── 02_country_coverage.ipynb
│   ├── 03_geography_crosswalk.ipynb
│   ├── 04_market_price_exploration.ipynb
│   └── 05_raster_product_assessment.ipynb
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── data/
│   ├── raw/
│   ├── interim/
│   ├── reference/
│   └── processed/
└── outputs/
    ├── catalogue/
    ├── coverage/
    ├── crosswalk/
    ├── licensing/
    ├── figures/
    └── reports/

Large downloaded files, credentials and restricted data must not be committed to Git.

⸻

10. Technology choices

Use Python 3.12 or later.

Preferred dependencies:

httpx
tenacity
pydantic
pydantic-settings
pyyaml
pandas
pyarrow
geopandas
pyogrio
shapely
rasterio
xarray
rioxarray
duckdb
sqlalchemy
psycopg
structlog
typer
rich
pytest
pytest-httpx
respx
ruff
mypy

Use uv for package and environment management unless the existing WIA repository already has a different standard.

Use:

* Parquet for most extracted and transformed tabular data;
* GeoParquet for spatial vectors;
* Cloud-optimised GeoTIFF where raster conversion is required;
* JSON manifests for extraction metadata;
* DuckDB for local exploratory querying;
* PostgreSQL/PostGIS only as an optional output target.

Do not make the exploratory pipeline depend on access to a production database.

⸻

11. Configuration

11.1 Environment variables

Create .env.example containing:

FEWSNET_USERNAME=
FEWSNET_PASSWORD=
FEWSNET_BASE_URL=https://fdw.fews.net/api
FEWSNET_TOKEN_URL=https://fdw.fews.net/api-token-auth/
FEWSNET_REQUEST_TIMEOUT=60
FEWSNET_PAGE_SIZE=1000
FEWSNET_RAW_DATA_DIR=data/raw/fewsnet
USGS_FEWSNET_RAW_DATA_DIR=data/raw/usgs_fewsnet
WIA_BOUNDARIES_PATH=data/reference/wia_admin2.parquet
WIA_POPULATION_RASTER_PATH=
DATABASE_URL=
LOG_LEVEL=INFO

Credentials must be optional because public endpoints may not require authentication.

11.2 Dataset configuration

Create config/datasets.yml with one entry per candidate dataset.

Example:

datasets:
  food_security_classification:
    enabled: true
    endpoint: ipcphase
    format: json
    schedule: Daily
    fields:
      - id
      - dataseries
      - fnid
      - start_date
      - end_date
      - collection_date
      - scenario
      - phase
      - value
    countries: all_configured
    raw_snapshot: true
  food_insecure_population:
    enabled: true
    endpoint: ipcpopulationsize
    format: json
    schedule: Daily
    raw_snapshot: true
  market_prices:
    enabled: true
    endpoint: marketpricefacts
    format: json
    schedule: Daily
    raw_snapshot: true

Endpoint field names must be updated after inspecting live schema responses.

11.3 Country configuration

Create config/countries.yml containing official names and identifiers.

Example:

countries:
  - name: South Sudan
    iso2: SS
    iso3: SSD
    wia_id: SSD
    enabled: true
  - name: Kenya
    iso2: KE
    iso3: KEN
    wia_id: KEN
    enabled: true

⸻

12. API client requirements

Implement a class such as:

class FewsNetClient:
    def authenticate(self) -> None: ...
    def request(self, endpoint: str, params: dict) -> dict: ...
    def iter_pages(self, endpoint: str, params: dict) -> Iterator[dict]: ...
    def iter_records(self, endpoint: str, params: dict) -> Iterator[dict]: ...
    def get_metadata(self, endpoint: str, params: dict | None = None) -> dict: ...

Required behaviour

The client must:

* support public requests without credentials;
* authenticate when credentials are provided;
* store the token only in memory;
* use the Authorization header rather than query-string authentication;
* detect authentication failures;
* re-authenticate once following token expiry;
* follow the API-provided next URL;
* avoid reapplying query parameters when following a complete next URL;
* implement retries for transient failures;
* not retry permanent 4xx errors except 408, 409, 425 and 429;
* use exponential backoff with jitter;
* log endpoint, status, page count and record count;
* redact credentials and tokens from logs;
* support explicit field selection;
* support explicit temporal schedule selection;
* store request metadata with every raw snapshot.

Raw request manifest

Each extraction should create a manifest such as:

{
  "provider": "FEWS NET",
  "endpoint": "ipcpopulationsize",
  "request_url": "redacted",
  "request_parameters": {},
  "retrieved_at": "2026-07-27T18:00:00Z",
  "http_status": 200,
  "record_count": 1250,
  "page_count": 2,
  "content_hash": "sha256:...",
  "authenticated": false,
  "client_version": "0.1.0"
}

Do not store passwords, JWTs or session cookies.

⸻

13. Discovery workflow

The first implementation phase must inspect the live API before building assumptions into transformation code.

13.1 Discovery tasks

For each candidate endpoint:

1. make a minimal request;
2. record response fields;
3. identify pagination structure;
4. identify metadata links;
5. test country filters;
6. test date filters;
7. test scenario filters;
8. test field selection;
9. test output formats;
10. test temporal schedule parameters;
11. test authenticated and unauthenticated behaviour;
12. record representative responses as sanitised test fixtures.

13.2 Discovery output

Create:

outputs/catalogue/api_endpoint_discovery.csv
docs/api-notes.md

Fields should include:

endpoint
status
authentication_required
default_format
supported_formats
pagination_type
default_page_size
maximum_observed_page_size
country_filter
date_filter
schedule_filter
fields_filter
geometry_supported
metadata_endpoint
notes
checked_at

13.3 Unknown endpoint discovery

Review:

* API root responses;
* browsable API links;
* metadata records;
* Data Explorer network requests, where legally and technically appropriate;
* official documentation;
* source-document links.

The project must not bypass access controls or reverse engineer protected interfaces. It may inspect normal browser requests made by publicly accessible pages.

⸻

14. Canonical data model

All transformed records should map into a common observation model where possible.

14.1 Core observation table

provider
dataset
endpoint
record_id
source_document_id
data_collection_id
data_series_id
source_organisation
country_iso2
country_iso3
fewsnet_fnid
wia_admin2_id
geographic_unit_name
geographic_unit_type
indicator_code
indicator_name
scenario
phase
reference_start
reference_end
collection_date
publication_date
value
lower_bound
upper_bound
unit
currency
commodity_code
market_id
quality_flag
licence_status
retrieved_at
raw_snapshot_path

Not every field will be populated for every dataset.

14.2 Temporal rules

Preserve separately:

* reference start;
* reference end;
* collection date;
* publication date;
* extraction date;
* scenario;
* forecast vintage.

Never overwrite records solely because they refer to the same geography and reference period.

A recommended natural key is:

provider
endpoint
data_series_id
fewsnet_fnid
reference_start
reference_end
collection_date
scenario
phase

If the API provides a stable record identifier, preserve it and include it in the uniqueness constraint.

14.3 Units

Do not transform units silently.

Store:

* original value;
* original unit;
* standardised value;
* standardised unit;
* conversion factor;
* conversion method.

Currency conversion is outside the initial project scope unless required for a limited market-price demonstration.

⸻

15. Dataset-specific transformation requirements

15.1 Food-security classifications

The transformed table should retain:

* phase;
* scenario;
* issue or collection date;
* reference period;
* analytical framework;
* source organisation;
* geographic-unit type.

Do not assume all records using an IPC-labelled endpoint are official IPC outputs.

Create derived flags only where metadata allow:

phase_3_plus
phase_4_plus
current_or_projected
forecast_horizon_months

Record the method used to interpret scenario codes.

15.2 Food-insecure population

Determine whether records represent:

* count;
* percentage;
* phase-specific count;
* cumulative Phase 3+ count;
* central estimate;
* range.

Preserve denominator data where available.

Potential derived fields:

population_phase_3_plus
population_phase_3_plus_pct
population_denominator
denominator_source

Do not calculate percentages using FEWS NET population fields unless the denominator source and licence are acceptable.

15.3 Market prices

Normalise:

* commodity names;
* commodity codes;
* market names;
* price type;
* currency;
* units;
* reporting period.

Preserve local currency values.

Potential diagnostics:

* duplicate market-month-product records;
* abrupt unit changes;
* currency changes;
* missing market coordinates;
* long reporting gaps;
* implausible zero values;
* extreme month-on-month changes.

Do not develop a final WIA market indicator in this project. Produce exploratory summaries and identify feasible indicator formulations.

15.4 Cross-border trade

Preserve:

* origin;
* destination;
* reporting country;
* commodity;
* quantity;
* value;
* unit;
* formal or informal status;
* border location;
* reporting period.

The project should assess whether these records can be associated with Admin2 areas without unsupported assumptions.

15.5 Environmental rasters

For each tested product:

* download one historical and one recent observation;
* validate file integrity;
* inspect metadata;
* identify CRS;
* identify spatial resolution;
* identify unit;
* identify nodata value;
* calculate basic descriptive statistics;
* aggregate values to a sample WIA Admin2 boundary dataset;
* record runtime and file size;
* assess update automation.

⸻

16. Geographic harmonisation

16.1 Inputs

The project requires:

* FEWS NET geographic metadata;
* FEWS NET vector geometry;
* current WIA Admin2 boundaries;
* a population raster, where population-weighted allocation is tested.

If the WIA boundary dataset is not yet available in the repository, the code should accept a configurable external path and document the required fields.

Minimum WIA boundary fields:

country_iso3
wia_admin2_id
wia_admin2_name
geometry
boundary_version

16.2 Matching hierarchy

Apply the following hierarchy:

1. exact known identifier crosswalk;
2. exact normalised name within country and parent unit;
3. high-confidence fuzzy name match with matching parent geography;
4. spatial containment;
5. spatial overlap;
6. population-weighted overlap;
7. manual review.

16.3 Match-method values

Use controlled values:

exact_identifier
exact_name
fuzzy_name
spatial_containment
area_weighted_overlap
population_weighted_overlap
manual
unmatched

16.4 Population-weighted allocation

Where a FEWS NET area overlaps multiple WIA Admin2 units:

allocated_value_i =
source_value × population_in_overlap_i / total_population_in_source_area

This method is valid for population counts but not necessarily for categorical classifications, prices or rates.

For categorical food-security classifications, assess alternatives such as:

* assign the dominant population-weighted phase;
* assign the maximum phase;
* calculate the percentage of Admin2 population within each phase;
* preserve the intersected areas without collapsing to one phase.

The exploratory project should compare these approaches and recommend one. It must not select a method solely because it is technically easy.

16.5 Crosswalk quality checks

Report:

* unmatched FEWS NET units;
* one-to-many mappings;
* many-to-one mappings;
* overlap totals below 0.95 or above 1.05;
* invalid geometry;
* sliver polygons;
* mismatched country identifiers;
* historical boundary conflicts.

⸻

17. Licensing workflow

17.1 Default policy

No dataset should be marked redistributable unless supported by explicit licence or policy evidence.

Use the following controlled statuses:

permitted
restricted
permission_required
unknown
not_applicable

17.2 Licence classes

Create an operational classification:

Class A: public and redistributable

May be stored and published with attribution.

Class B: public with specific attribution requirements

May be stored and published only with required attribution.

Class C: analysis permitted, raw redistribution restricted

May be stored internally and used for derived analysis subject to licence conditions.

Class D: restricted-access

Must not be ingested without documented permission.

Class E: unclear

Must be quarantined pending review.

17.3 Enforcement

The pipeline must include a validation function such as:

def assert_publishable(dataset_id: str, output_type: str) -> None:
    ...

Publication steps should fail closed when licence status is unknown, restricted or permission_required.

17.4 Evidence storage

For every licence decision, record:

* policy title;
* policy URL;
* relevant excerpt or summary;
* date accessed;
* decision;
* reviewer;
* notes.

Avoid storing long copyrighted policy text. Store a concise summary and URL.

⸻

18. Data quality and validation

18.1 General checks

Implement checks for:

* missing identifiers;
* missing dates;
* invalid date order;
* duplicated records;
* unexpected null rates;
* unexpected schema changes;
* negative values where impossible;
* percentage values outside valid bounds;
* impossible phase codes;
* unexpected scenario codes;
* unknown units;
* country-code mismatches;
* geometry validity;
* empty API pages;
* incomplete pagination.

18.2 Schema drift

Store expected response schemas in version-controlled Pydantic models.

When unexpected fields appear:

* preserve them in raw data;
* log the change;
* do not fail solely because an additional field appears.

When required fields disappear or change type:

* fail the transformation;
* retain the raw response;
* create an actionable error message.

18.3 Revision detection

Where a previously retrieved record changes:

* retain both raw snapshots;
* calculate a record hash;
* mark the transformed record as revised;
* record the first-seen and last-seen timestamps;
* report the number and magnitude of revisions.

⸻

19. Command-line interface

Provide a CLI using Typer.

Suggested commands:

fewsnet-wia inspect-api
fewsnet-wia build-catalogue
fewsnet-wia extract classifications
fewsnet-wia extract populations
fewsnet-wia extract market-prices
fewsnet-wia extract geography
fewsnet-wia extract usgs-raster --product runoff
fewsnet-wia audit-coverage
fewsnet-wia build-crosswalk
fewsnet-wia validate-licences
fewsnet-wia generate-report
fewsnet-wia run-all

Commands should support:

--country
--start-date
--end-date
--config
--output-dir
--force
--dry-run
--log-level

The --dry-run option should display intended endpoints, parameters and output paths without downloading data.

⸻

20. Logging and reproducibility

Use structured logging.

Each run should have:

run_id
command
started_at
completed_at
git_commit
configuration_hash
dataset
country
endpoint
record_count
output_path
status
error

Create a run manifest:

outputs/manifests/{run_id}.json

Every final report should identify:

* repository commit;
* run identifier;
* data retrieval dates;
* configuration version;
* known limitations.

⸻

21. Testing requirements

21.1 Unit tests

Cover:

* authentication;
* token redaction;
* pagination;
* retry logic;
* date parsing;
* scenario mapping;
* unit preservation;
* licence decisions;
* geography matching;
* overlap calculations;
* duplicate detection.

21.2 Contract tests

Create tests against representative API responses to detect:

* missing required fields;
* changed pagination structure;
* changed authentication response;
* changed field types.

Live API contract tests should be optional and skipped unless explicitly enabled.

Example:

RUN_LIVE_API_TESTS=1 pytest tests/contract

21.3 Integration tests

Use small fixture datasets to test:

* complete extraction;
* raw snapshot writing;
* transformation;
* Parquet output;
* coverage reporting;
* crosswalk creation.

21.4 Test safeguards

Tests must not:

* expose credentials;
* commit live restricted data;
* make uncontrolled large downloads;
* rely on a production database.

⸻

22. Exploratory analyses

The project should produce the following analyses.

22.1 Dataset coverage matrix

Rows:

country × dataset

Columns:

available
earliest_date
latest_date
latest_collection_date
observation_count
geographic_unit_count
admin2_direct_coverage
admin2_spatial_coverage
licence_class
recommended_use

22.2 Food-security comparison

For at least three countries:

* retrieve current and projected phases;
* retrieve food-insecure population estimates;
* compare issue dates and forecast horizons;
* identify overlapping vintages;
* show how using only the latest reference period could produce errors.

Suggested pilot countries:

South Sudan
Burkina Faso
Afghanistan

22.3 Market-price assessment

For at least two countries:

* identify staple commodities;
* identify markets;
* calculate time-series completeness;
* calculate reporting delay;
* identify unit and currency changes;
* test mapping markets to Admin2;
* assess candidate indicators.

Suggested pilot countries:

Kenya
Mali

22.4 Geographic crosswalk

For at least one country with livelihood-zone or composite analysis areas:

* retrieve FEWS NET geography;
* overlay with WIA Admin2;
* calculate area-weighted overlap;
* calculate population-weighted overlap if population data are available;
* document ambiguous cases.

Suggested pilot:

South Sudan or Kenya

22.5 Environmental raster test

For one country:

* download runoff or soil-moisture data;
* aggregate to WIA Admin2;
* calculate a simple anomaly or percentile metric if sufficient historical data are available;
* compare operational complexity with direct use of CHIRPS or ERA5-Land;
* document suitability for the proposed hydrological-drought indicator.

Suggested pilot:

Kenya

⸻

23. Relevance assessment framework

For each dataset, score the following dimensions from 0 to 3.

0 = unsuitable
1 = weak
2 = usable with limitations
3 = strong

Dimensions:

* construct relevance;
* geographic coverage;
* temporal coverage;
* update regularity;
* subnational resolution;
* methodological consistency;
* API accessibility;
* licensing clarity;
* geographic interoperability;
* operational maintainability.

Calculate an unweighted total but do not use the total as the sole basis for recommendation.

Recommendation categories:

adopt
pilot further
contextual use only
defer
reject

Each recommendation must include a written rationale.

⸻

24. Acceptance criteria

The exploratory project is complete when all of the following are true.

API and catalogue

* The live API has been inspected.
* At least four structured endpoint families have been tested.
* Public versus authenticated behaviour is documented.
* Pagination and field filtering are working.
* A machine-readable catalogue has been produced.

Coverage

* Coverage has been audited for all configured countries.
* Earliest and latest dates have been calculated.
* Geographic-unit counts have been calculated.
* Direct and potential Admin2 coverage have been estimated.

Ingestion

* Working pipelines exist for classifications, population estimates, market prices and geography.
* At least one environmental raster product has been downloaded and processed.
* Raw and transformed outputs are reproducible.

Geography

* A FEWS NET-to-WIA crosswalk has been produced for at least one pilot country.
* Ambiguous matches are flagged.
* The allocation method is documented.

Licensing

* A licensing register exists.
* Every assessed dataset has a licence status.
* Unknown or restricted datasets are prevented from publication by default.

Documentation

* The README contains complete setup and execution instructions.
* The feasibility report answers the core research questions.
* Known limitations and unresolved questions are documented.
* The repository passes tests, linting and type checks.

⸻

25. Out of scope

The following are outside the initial exploratory project:

* production deployment;
* development of a final WIA indicator scoring methodology;
* automated publication to the WIA platform;
* currency conversion for market prices;
* market catchment modelling;
* final validation of a hydrological-drought indicator;
* negotiation of data-sharing agreements;
* redistribution of restricted datasets;
* global processing of all historical raster products;
* replacement of existing WIA population datasets;
* creation of operational dashboards.

The project may make recommendations on these issues.

⸻

26. Risks and mitigation

Mixed licensing

Risk: FEWS NET contains data from multiple providers with different conditions.

Mitigation: Implement dataset-level licensing records and fail-closed publication rules.

Uneven coverage

Risk: Some countries or periods may appear available but be too incomplete for WIA use.

Mitigation: Quantify temporal and geographic completeness rather than recording only presence or absence.

Geographic mismatch

Risk: FEWS NET analysis areas may not align with Admin2.

Mitigation: Build a formal crosswalk and compare area-weighted and population-weighted approaches.

Forecast-vintage confusion

Risk: Current and projected values may refer to overlapping periods.

Mitigation: Preserve scenario, issue date, collection date and reference period.

Hidden temporal aggregation

Risk: The API may aggregate records to monthly values by default.

Mitigation: Set the schedule explicitly and compare raw versus default responses.

Schema change

Risk: API changes may break ingestion.

Mitigation: Use contract tests, schema validation and raw-response preservation.

Raster access instability

Risk: USGS raster URLs or catalogue structures may not be designed as a stable API.

Mitigation: Separate product-specific download adapters and record observed URL conventions.

Third-party population rights

Risk: FEWS NET-linked demographic values may derive from restricted sources.

Mitigation: Use the existing WIA population dataset unless rights are confirmed.

⸻

27. Implementation phases

Phase 1: repository and API discovery

Tasks:

* initialise repository;
* configure Python environment;
* create configuration files;
* implement logging;
* inspect API root and candidate endpoints;
* document authentication;
* save sanitised fixtures;
* create initial endpoint catalogue.

Completion condition:

* the API client can retrieve and paginate at least one public endpoint.

Phase 2: structured data extraction

Tasks:

* implement classifications extraction;
* implement population extraction;
* implement market-price extraction;
* investigate trade and additional datasets;
* build canonical transformations;
* save raw snapshots and Parquet outputs.

Completion condition:

* three structured datasets can be extracted reproducibly for selected countries.

Phase 3: coverage audit

Tasks:

* enumerate series and source documents;
* calculate country coverage;
* calculate date ranges;
* calculate geographic-unit coverage;
* identify stale and incomplete series;
* produce coverage matrix.

Completion condition:

* all configured countries have dataset-level coverage records.

Phase 4: geographic harmonisation

Tasks:

* retrieve FEWS NET geographic units;
* load WIA Admin2 boundaries;
* implement matching hierarchy;
* build pilot crosswalk;
* test overlap methods;
* document unresolved mappings.

Completion condition:

* at least one country has a validated prototype crosswalk.

Phase 5: licensing

Tasks:

* extract source and policy metadata;
* create licensing register;
* classify datasets;
* implement publication safeguards;
* identify questions for FEWS NET.

Completion condition:

* no assessed dataset remains without an explicit licence status, including unknown.

Phase 6: environmental raster pilot

Tasks:

* identify download method;
* retrieve sample runoff or soil-moisture files;
* inspect raster metadata;
* aggregate to Admin2;
* assess historical processing requirements;
* compare with current WIA drought data sources.

Completion condition:

* one raster product has been processed end to end.

Phase 7: synthesis

Tasks:

* generate tables and figures;
* score datasets;
* write feasibility report;
* identify recommended operational integrations;
* document required follow-up with FEWS NET or USGS.

Completion condition:

* all acceptance criteria are met.

⸻

28. Codex working instructions

Codex should follow these instructions throughout the project.

General approach

* Begin by inspecting the repository and existing WIA conventions.
* Do not overwrite existing project configuration without checking its purpose.
* Prefer small, reviewable commits.
* Keep exploratory notebooks separate from reusable library code.
* Move stable logic from notebooks into src/.
* Document assumptions as they are introduced.
* Record major design decisions in docs/decisions/.
* Do not treat undocumented API behaviour as guaranteed.
* Verify endpoint fields against live responses.
* Preserve raw source data before transformation.
* Do not publish or commit restricted data.
* Do not commit credentials.
* Do not infer that access implies redistribution permission.
* Fail clearly when required configuration is missing.
* Keep the implementation usable without a production database.

Before coding

Codex should:

1. read this specification;
2. inspect the repository;
3. identify existing linting, testing and packaging conventions;
4. identify whether WIA Admin2 boundaries are already present;
5. create a short implementation plan in docs/implementation-plan.md;
6. list assumptions and blockers;
7. begin with API discovery rather than writing transformations based on guessed schemas.

During implementation

After each phase, Codex should:

* run tests;
* run linting;
* run type checks;
* update documentation;
* summarise findings in the relevant Markdown file;
* record unresolved issues;
* avoid continuing to later phases if a foundational assumption is invalid.

Commit structure

Suggested commits:

chore: initialise FEWS NET exploration project
feat: add FEWS NET API client and authentication
feat: add endpoint discovery and metadata catalogue
feat: add food security classification ingestion
feat: add food insecure population ingestion
feat: add market price ingestion
feat: add FEWS NET geography extraction
feat: add country coverage audit
feat: add geographic crosswalk prototype
feat: add licensing registry and safeguards
feat: add USGS raster download prototype
docs: add feasibility report and recommendations

⸻

29. Initial Codex task prompt

Use the following prompt to start implementation:

Implement the FEWS NET Data Integration Feasibility Study described in
docs/project-specification.md.
Begin with Phase 1 only.
Your first tasks are:
1. Inspect the repository and identify existing Python, testing, linting,
   configuration and data-storage conventions.
2. Create docs/implementation-plan.md summarising:
   - the current repository structure;
   - assumptions;
   - dependencies;
   - proposed implementation sequence;
   - any missing inputs;
   - risks that may affect the design.
3. Initialise the project structure required for the FEWS NET exploration,
   adapting it to existing repository conventions rather than duplicating
   existing infrastructure.
4. Implement a reusable FEWS NET API client with:
   - optional JWT authentication;
   - pagination using the API-provided next URL;
   - retries with exponential backoff;
   - explicit timeouts;
   - structured logging;
   - token and credential redaction;
   - configurable base URLs and page size.
5. Implement an API discovery command that:
   - tests the configured candidate endpoints;
   - records authentication requirements;
   - records response fields and pagination structure;
   - tests field and country filters where supported;
   - stores sanitised response fixtures;
   - writes outputs/catalogue/api_endpoint_discovery.csv;
   - updates docs/api-notes.md.
6. Add unit tests and mocked contract tests.
7. Add a README section explaining setup, credentials and discovery commands.
Do not implement later extraction phases until the live API schema has been
inspected and documented.
Do not guess endpoint fields. Query the live API, preserve representative raw
responses, and update config/datasets.yml based on observed behaviour.
Never commit credentials, JWTs, cookies, restricted data or large raw files.
At completion, provide:
- a summary of files added or changed;
- commands run;
- test results;
- API findings;
- unresolved questions;
- a recommendation for the next implementation phase.

⸻

30. Questions likely to require external clarification

The feasibility report should identify whether written clarification is needed from FEWS NET or USGS on:

1. permitted frequency and volume of automated API requests;
2. stability expectations for API endpoints;
3. bulk extraction of historical data;
4. publication of transformed Admin2 indicators;
5. redistribution of FEWS NET-derived versus third-party values;
6. required attribution wording;
7. licensing of LandScan-derived population fields;
8. access to restricted source documents;
9. interpretation of analytical-framework fields;
10. automation of USGS FEWS NET raster downloads;
11. notification of schema or product changes;
12. availability of a formal data catalogue or OpenAPI schema.

⸻

31. Expected final recommendation structure

The final report should classify candidate integrations as follows.

Recommended for operational integration

Datasets with:

* strong WIA relevance;
* adequate coverage;
* stable machine access;
* clear licensing;
* feasible Admin2 harmonisation.

Recommended for further pilot testing

Datasets with potential value but unresolved methodological, geographic or licensing issues.

Recommended for contextual use only

Datasets useful for interpretation but unsuitable as formal WIA indicators.

Deferred

Datasets with insufficient access, documentation or coverage.

Rejected

Datasets with unacceptable licensing, methodological inconsistency, weak construct relevance or infeasible geographic harmonisation.

Each decision must be supported by evidence generated during the project.

The first implementation pass should stop after live API discovery and schema validation; that will prevent later Codex tasks from embedding incorrect endpoint or field assumptions.