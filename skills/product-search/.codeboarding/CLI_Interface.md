```mermaid
graph LR
    Core_Service_Orchestration["Core Service Orchestration"]
    CLI_Entry_Persistence["CLI Entry & Persistence"]
    CLI_Entry_Persistence -- "Command dispatch into orchestration pipeline" --> Core_Service_Orchestration
    Core_Service_Orchestration -- "Run and vendor registry persistence" --> CLI_Entry_Persistence
```

[![CodeBoarding](https://img.shields.io/badge/Generated%20by-CodeBoarding-9cf?style=flat-square)](https://github.com/CodeBoarding/CodeBoarding)[![Web platform](https://img.shields.io/badge/Open%20in-Web%20platform-2563EB?style=flat-square)](https://app.codeboarding.org)[![Demo](https://img.shields.io/badge/Try%20our-Demo-blue?style=flat-square)](https://www.codeboarding.org/diagrams)[![Contact](https://img.shields.io/badge/Contact%20us%20-%20contact@codeboarding.org-lightgrey?style=flat-square)](mailto:contact@codeboarding.org)

## Details

Provides the command-line entry point (search, product, quote, images, config), argument parsing, and JSON output/error formatting for the toolset.

### Core Service Orchestration
The central service facade and data-model layer that implements the toolset's core pipeline. `Storefront` exposes the `search`, `product`, `quote`, and `images_for` operations, grouping inputs by store origin and fanning work out across a bounded `ThreadPoolExecutor` worker pool. It relies on core helpers (`_item_array`, `_item_identity`, `_cache_store`, `_metadata`, `_append_variant`) and the `core` module's data-model utilities (`adapter_items`, `canonical_ref`, `description`, `money_amount`, `public_detection`) to normalize inputs, build cacheable store records, and assemble run metadata. This component is the orchestration heart that the CLI dispatches into.


**Related Classes/Methods**:

- `storefront.src.storefront.service.Storefront`:55-612
- `storefront.src.storefront.service.Storefront._parallel`:214-232
- `storefront.src.storefront.service._item_array`:775-778
- `storefront.src.storefront.service._item_identity`:741-749
- `storefront.src.storefront.service._cache_store`:737-738


### CLI Entry & Persistence
The command-line front-end and its persistence backing. `main()` is the process entry point that parses arguments, dispatches to the `Storefront` service or `_config()`, serializes results to compact JSON on stdout, and maps `api_error` presence to the exit code. `_parser()` and `_common()` define the subcommand grammar and shared flags; `_json()` and `_has_api_error()` handle input decoding and recursive error detection. On the persistence side, `DataStore` manages settings, the vendor registry, run history, and image storage under a user data directory, while `validate_destination` enforces destination shape. The `images_for` flow (with `_image_range`/`_image_suffix` helpers) downloads and caches product images through this component.


**Related Classes/Methods**:

- `storefront.src.storefront.cli.main`:14-37
- `storefront.src.storefront.cli._parser`:40-66
- `storefront.src.storefront.cli._json`:93-97
- `storefront.src.storefront.storage.DataStore`:21-190
- `storefront.src.storefront.service.Storefront.images_for`:186-212




### [FAQ](https://github.com/CodeBoarding/GeneratedOnBoardings/tree/main?tab=readme-ov-file#faq)