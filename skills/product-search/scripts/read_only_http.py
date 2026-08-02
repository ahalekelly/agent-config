from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, assert_never
from urllib.parse import unquote_to_bytes, urlencode, urljoin, urlsplit, urlunsplit

import httpx

OperationKind = Literal[
    "bigcommerce_search",
    "discovered_product_page",
    "ecwid_products",
    "ecwid_script",
    "ecwid_initial_data",
    "magento_html_search",
    "magento_product_detail",
    "magento_probe",
    "magento_product_search",
    "sfcc_search",
    "shopify_probe",
    "shopify_product_search",
    "squarespace_product_json",
    "squarespace_search",
    "storefront_entry",
    "storefront_entry_replay",
    "wix_bootstrap",
    "wix_catalog_search",
    "woo_products",
]

GRAPHQL_DOCUMENT_SHA256_BY_OPERATION: Mapping[OperationKind, str] = MappingProxyType(
    {
        "shopify_probe": "d87467d81cf8b1001256a65ff79cf59a2002d2c31d46a049be787ef1c9802317",
        "shopify_product_search": "91925002933fd411af7716fb29789061aa2cc0bbdc49266202f145aab4ca93c2",
        "magento_probe": "05669fd6f813ee5655ecc2c6ea7222c9545255bea95693db853b29a45a6d7484",
        "magento_product_search": "d8747f3014cdf17ca45534785ae85f8db13390e033980f96b37ae8dc82d31152",
        "magento_product_detail": "de68697b3683d72184b1de3573528a98594a3f02a6da0519b8bace5b65203c3d",
    }
)


class ReadOnlyPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ReadOnlyOperation:
    operation_kind: OperationKind
    body_sha256: str
    document_sha256: str | None
    source_request_sha256: str | None = None
    source_response_sha256: str | None = None


RedirectPolicy = Literal["none", "entry", "same_origin"]


@dataclass(frozen=True)
class _StorefrontEntry:
    url: str
    origins: frozenset[str]


@dataclass(frozen=True)
class _StorefrontEntryReplay:
    url: str
    source_request_sha256: str
    source_response_sha256: str


@dataclass(frozen=True)
class _WooProducts:
    origin: str
    query: str
    limit: Literal[1, 20]


@dataclass(frozen=True)
class _BigCommerceSearch:
    origin: str
    query: str


@dataclass(frozen=True)
class _MagentoHtmlSearch:
    origin: str
    entry_url: str
    query: str


@dataclass(frozen=True)
class _SquarespaceSearch:
    origin: str
    query: str


@dataclass(frozen=True)
class _WixBootstrap:
    origin: str


@dataclass(frozen=True)
class _EcwidScript:
    store_id: int
    source_request_sha256: str
    source_response_sha256: str


@dataclass(frozen=True)
class _EcwidProducts:
    store_id: int
    token: str
    query: str
    source_request_sha256: str
    source_response_sha256: str


@dataclass(frozen=True)
class _SfccSearch:
    origin: str
    entry_url: str
    query: str


@dataclass(frozen=True)
class _DiscoveredProductPage:
    origin: str
    url: str
    source_request_sha256: str
    source_response_sha256: str


@dataclass(frozen=True)
class _SquarespaceProductJson:
    origin: str
    url: str
    source_request_sha256: str
    source_response_sha256: str


_ReadState = (
    _StorefrontEntry
    | _StorefrontEntryReplay
    | _WooProducts
    | _BigCommerceSearch
    | _MagentoHtmlSearch
    | _SquarespaceSearch
    | _WixBootstrap
    | _EcwidScript
    | _EcwidProducts
    | _SfccSearch
    | _DiscoveredProductPage
    | _SquarespaceProductJson
)
_READ_GET_SEAL = object()


@dataclass(frozen=True)
class ReadGet:
    _owner: object
    _state: _ReadState
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _READ_GET_SEAL:
            raise ReadOnlyPolicyError("ReadGet capabilities cannot be publicly forged")


@dataclass(frozen=True)
class AuthorizedGet:
    url: str
    operation: ReadOnlyOperation
    origin: str
    redirect_policy: RedirectPolicy
    redirects_remaining: int
    entry_origins: frozenset[str]


def mint_read_get(owner: object, state: _ReadState) -> ReadGet:
    return ReadGet(owner, state, _READ_GET_SEAL)


def authorize_read_get(read: ReadGet, owner: object) -> AuthorizedGet:
    if not isinstance(read, ReadGet) or read._seal is not _READ_GET_SEAL:
        raise ReadOnlyPolicyError("Http.get requires a sealed ReadGet capability")
    if read._owner is not owner:
        raise ReadOnlyPolicyError("ReadGet belongs to another Http instance")
    state = read._state
    source_request_sha256 = None
    source_response_sha256 = None
    redirect_policy: RedirectPolicy = "none"
    redirects_remaining = 0
    if isinstance(state, _StorefrontEntry):
        operation_kind: OperationKind = "storefront_entry"
        url = state.url
        origin = _origin(url)
        if not state.origins or origin not in state.origins:
            raise ReadOnlyPolicyError(
                "Storefront entry scope must contain its normalized input origin"
            )
        if any(_exact_origin(value) != value for value in state.origins):
            raise ReadOnlyPolicyError(
                "Storefront entry scope must contain exact HTTPS origins"
            )
        redirect_policy = "entry"
        redirects_remaining = 5
        entry_origins = state.origins
    elif isinstance(state, _StorefrontEntryReplay):
        operation_kind = "storefront_entry_replay"
        url = state.url
        origin = _origin(url)
        source_request_sha256 = state.source_request_sha256
        source_response_sha256 = state.source_response_sha256
    elif isinstance(state, _WooProducts):
        operation_kind = "woo_products"
        origin = _exact_origin(state.origin)
        if state.limit not in {1, 20}:
            raise ReadOnlyPolicyError("WooCommerce product limit must be 1 or 20")
        url = origin + "/wp-json/wc/store/v1/products?" + urlencode(
            {"search": _query(state.query), "per_page": state.limit}
        )
    elif isinstance(state, _BigCommerceSearch):
        operation_kind = "bigcommerce_search"
        origin = _exact_origin(state.origin)
        url = origin + "/search.php?" + urlencode(
            {"search_query": _query(state.query)}
        )
    elif isinstance(state, _MagentoHtmlSearch):
        operation_kind = "magento_html_search"
        origin = _exact_origin(state.origin)
        url = urljoin(_same_origin_url(state.entry_url, origin), "catalogsearch/result")
        url += "?" + urlencode({"q": _query(state.query)})
        redirect_policy = "same_origin"
        redirects_remaining = 1
    elif isinstance(state, _SquarespaceSearch):
        operation_kind = "squarespace_search"
        origin = _exact_origin(state.origin)
        url = origin + "/search?" + urlencode({"q": _query(state.query)})
    elif isinstance(state, _WixBootstrap):
        operation_kind = "wix_bootstrap"
        origin = _exact_origin(state.origin)
        url = origin + "/_api/v1/access-tokens"
    elif isinstance(state, _EcwidScript):
        if type(state.store_id) is not int or state.store_id <= 0:
            raise ReadOnlyPolicyError("Ecwid store ID must be a positive integer")
        operation_kind = "ecwid_script"
        origin = "https://app.ecwid.com"
        url = f"{origin}/script.js?{state.store_id}"
        source_request_sha256 = state.source_request_sha256
        source_response_sha256 = state.source_response_sha256
    elif isinstance(state, _EcwidProducts):
        if type(state.store_id) is not int or state.store_id <= 0 or not state.token:
            raise ReadOnlyPolicyError("Ecwid products require a store ID and token")
        operation_kind = "ecwid_products"
        origin = "https://app.ecwid.com"
        url = f"{origin}/api/v3/{state.store_id}/products?" + urlencode(
            {"token": state.token, "keyword": _query(state.query), "limit": 10}
        )
        source_request_sha256 = state.source_request_sha256
        source_response_sha256 = state.source_response_sha256
    elif isinstance(state, _SfccSearch):
        operation_kind = "sfcc_search"
        origin = _exact_origin(state.origin)
        route = urljoin(_same_origin_url(state.entry_url, origin), "search")
        url = route + "?" + urlencode({"q": _query(state.query)})
        redirect_policy = "same_origin"
        redirects_remaining = 5
    elif isinstance(state, _DiscoveredProductPage):
        operation_kind = "discovered_product_page"
        origin = _exact_origin(state.origin)
        url = _product_url(state.url, origin)
        source_request_sha256 = state.source_request_sha256
        source_response_sha256 = state.source_response_sha256
        redirect_policy = "same_origin"
        redirects_remaining = 5
    elif isinstance(state, _SquarespaceProductJson):
        operation_kind = "squarespace_product_json"
        origin = _exact_origin(state.origin)
        page = urlsplit(_product_url(state.url, origin))
        if page.query:
            raise ReadOnlyPolicyError("Squarespace product links must not have a query")
        url = urlunsplit((page.scheme, page.netloc, page.path, "format=json", ""))
        source_request_sha256 = state.source_request_sha256
        source_response_sha256 = state.source_response_sha256
        redirect_policy = "same_origin"
        redirects_remaining = 5
    else:
        assert_never(state)
    if not isinstance(state, _StorefrontEntry):
        entry_origins = frozenset()
    _https_url(url)
    return AuthorizedGet(
        url=url,
        operation=ReadOnlyOperation(
            operation_kind=operation_kind,
            body_sha256=hashlib.sha256(b"").hexdigest(),
            document_sha256=None,
            source_request_sha256=source_request_sha256,
            source_response_sha256=source_response_sha256,
        ),
        origin=origin,
        redirect_policy=redirect_policy,
        redirects_remaining=redirects_remaining,
        entry_origins=entry_origins,
    )


def authorize_redirect(
    parent: AuthorizedGet,
    location: str,
    source_request_sha256: str,
    source_response_sha256: str,
) -> AuthorizedGet:
    target = urljoin(parent.url, location)
    parts = urlsplit(target)
    _https_url(target)
    if parent.redirect_policy == "none":
        raise ReadOnlyPolicyError(
            f"{parent.operation.operation_kind} does not allow redirects"
        )
    if parent.redirects_remaining == 0:
        raise ReadOnlyPolicyError("ReadGet redirect chain exceeded its route limit")
    if parent.redirect_policy == "same_origin" and _origin(target) != parent.origin:
        raise ReadOnlyPolicyError("ReadGet redirect must stay on the same storefront origin")
    if _write_or_session_path(parts.path):
        raise ReadOnlyPolicyError("ReadGet redirect changed resource purpose")
    parent_parts = urlsplit(parent.url)
    if parent.operation.operation_kind == "discovered_product_page" and (
        parts.query or parts.path.rstrip("/") != parent_parts.path.rstrip("/")
    ):
        raise ReadOnlyPolicyError("Product redirect changed resource purpose")
    if parent.operation.operation_kind == "squarespace_product_json" and (
        parts.query != "format=json"
        or parts.path.rstrip("/") != parent_parts.path.rstrip("/")
    ):
        raise ReadOnlyPolicyError("Product JSON redirect changed resource purpose")
    if (
        parent.operation.operation_kind == "magento_html_search"
        and parts.query not in {parent_parts.query, ""}
    ):
        raise ReadOnlyPolicyError("Search redirect changed resource purpose")
    if parent.operation.operation_kind == "sfcc_search" and parts.query != parent_parts.query:
        raise ReadOnlyPolicyError("Search redirect changed resource purpose")
    if parent.redirect_policy == "entry":
        if _origin(target) not in parent.entry_origins:
            raise ReadOnlyPolicyError(
                "Storefront entry redirect left its preauthorized origin scope"
            )
        if parts.query:
            raise ReadOnlyPolicyError("Storefront entry redirect changed resource purpose")
    return AuthorizedGet(
        url=target,
        operation=ReadOnlyOperation(
            operation_kind=parent.operation.operation_kind,
            body_sha256=parent.operation.body_sha256,
            document_sha256=None,
            source_request_sha256=source_request_sha256,
            source_response_sha256=source_response_sha256,
        ),
        origin=parent.origin if parent.redirect_policy != "entry" else _origin(target),
        redirect_policy=parent.redirect_policy,
        redirects_remaining=parent.redirects_remaining - 1,
        entry_origins=parent.entry_origins,
    )


def _query(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReadOnlyPolicyError("ReadGet search query must be nonempty")
    return value


def _exact_origin(value: str) -> str:
    parts = urlsplit(value)
    _https_url(value)
    if parts.path or parts.query or parts.fragment:
        raise ReadOnlyPolicyError("ReadGet origin must not contain a path or query")
    return value


def _same_origin_url(value: str, origin: str) -> str:
    _https_url(value)
    if _origin(value) != origin:
        raise ReadOnlyPolicyError("ReadGet URL must stay on its storefront origin")
    return value


def _product_url(value: str, origin: str) -> str:
    url = _same_origin_url(value, origin)
    parts = urlsplit(url)
    if parts.query or _write_or_session_path(parts.path):
        raise ReadOnlyPolicyError("Discovered product URL changed resource purpose")
    return url


def _write_or_session_path(path: str) -> bool:
    segments = {
        segment.rsplit(".", 1)[0].casefold()
        for segment in _strict_unquote(path, plus_as_space=False).split("/")
        if segment
    }
    return bool(
        segments
        & {
            "add-to-cart",
            "address",
            "addresses",
            "basket",
            "cart",
            "carts",
            "checkout",
            "checkouts",
            "consignment",
            "consignments",
            "guest-carts",
            "login",
            "logout",
            "rate",
            "rates",
            "shipping",
            "session",
            "sessions",
            "wishlist",
            "wishlists",
        }
    )


def _origin(value: str) -> str:
    parts = urlsplit(value)
    _https_url(value)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _https_url(value: str) -> None:
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ReadOnlyPolicyError("ReadGet URL is invalid") from error
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in {None, 443}
    ):
        raise ReadOnlyPolicyError(
            "ReadGet requires HTTPS URLs without credentials or fragments"
        )


GRAPHQL_OPERATION = re.compile(r"(?:\ufeff)?(?:\s|,|#[^\r\n]*(?:\r?\n|$))*(\{|[_A-Za-z][_0-9A-Za-z]*)")
WIX_CATALOG_PATH = "/_api/catalog-reader-server/api/v1/products/query"
ECWID_INITIAL_DATA_PATH = re.compile(
    r"/storefront/api/v1/[1-9][0-9]*/initial-data"
)


def _strict_unquote(value: str, *, plus_as_space: bool) -> str:
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        raise ReadOnlyPolicyError("Read-only HTTP URL has malformed percent encoding")
    encoded = value.replace("+", " ") if plus_as_space else value
    try:
        return unquote_to_bytes(encoded).decode("utf-8")
    except UnicodeDecodeError as error:
        raise ReadOnlyPolicyError("Read-only HTTP URL is not valid UTF-8") from error


def authorize_read_only_request(request: httpx.Request) -> ReadOnlyOperation:
    parts = urlsplit(str(request.url))
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        raise ReadOnlyPolicyError(
            "Read-only HTTP requires HTTPS URLs without credentials"
        )
    if "x-http-method-override" in request.headers:
        raise ReadOnlyPolicyError("Read-only HTTP rejects method override headers")
    body = request.read()
    if request.method == "GET":
        raise ReadOnlyPolicyError(
            "Read-only HTTP GET requests require a sealed capability from Http.get"
        )
    if request.method != "POST":
        raise ReadOnlyPolicyError(f"Read-only HTTP rejects {request.method} requests")
    if parts.query:
        raise ReadOnlyPolicyError("Read-only HTTP rejects unclassified POST requests")

    try:
        payload = json.loads(body, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReadOnlyPolicyError("Read-only HTTP POST body must be JSON") from error
    body_sha256 = hashlib.sha256(body).hexdigest()
    if parts.path == WIX_CATALOG_PATH:
        if not _valid_wix_catalog_query(payload):
            raise ReadOnlyPolicyError(
                "Read-only HTTP rejects an unexpected Wix catalog query"
            )
        return ReadOnlyOperation(
            operation_kind="wix_catalog_search",
            body_sha256=body_sha256,
            document_sha256=None,
        )
    if (
        parts.hostname is not None
        and parts.hostname.endswith(".ecwid.com")
        and ECWID_INITIAL_DATA_PATH.fullmatch(parts.path)
        and payload == {"lang": "en"}
    ):
        return ReadOnlyOperation(
            operation_kind="ecwid_initial_data",
            body_sha256=body_sha256,
            document_sha256=None,
        )
    if parts.path not in {"/api/2026-07/graphql.json", "/graphql"}:
        raise ReadOnlyPolicyError("Read-only HTTP rejects unclassified POST requests")
    if not isinstance(payload, dict) or "query" not in payload:
        raise ReadOnlyPolicyError("Read-only HTTP rejects unclassified POST requests")
    document = payload["query"]
    if not isinstance(document, str):
        raise ReadOnlyPolicyError("Read-only HTTP GraphQL document must be a string")
    operation = GRAPHQL_OPERATION.match(document)
    if operation is None:
        raise ReadOnlyPolicyError("Read-only HTTP GraphQL document has no operation")
    operation_type = "query" if operation.group(1) == "{" else operation.group(1)
    if operation_type in {"mutation", "subscription"}:
        raise ReadOnlyPolicyError(
            f"Read-only HTTP rejects GraphQL {operation_type} operations"
        )
    if operation_type != "query":
        raise ReadOnlyPolicyError(
            "Read-only HTTP GraphQL document must contain a query operation"
        )
    document_sha256 = hashlib.sha256(document.encode()).hexdigest()
    if (
        parts.path == "/api/2026-07/graphql.json"
        and document_sha256 == GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["shopify_probe"]
        and set(payload) == {"query"}
    ):
        operation_kind: OperationKind = "shopify_probe"
    elif (
        parts.path == "/api/2026-07/graphql.json"
        and document_sha256
        == GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["shopify_product_search"]
        and set(payload) == {"query", "variables"}
        and isinstance(payload["variables"], dict)
        and set(payload["variables"]) == {"query"}
        and isinstance(payload["variables"]["query"], str)
        and payload["variables"]["query"]
    ):
        operation_kind = "shopify_product_search"
    elif (
        parts.path == "/graphql"
        and document_sha256 == GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["magento_probe"]
        and set(payload) == {"query", "variables"}
        and payload["variables"] == {}
    ):
        operation_kind = "magento_probe"
    elif (
        parts.path == "/graphql"
        and document_sha256
        == GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["magento_product_search"]
        and set(payload) == {"query", "variables"}
        and isinstance(payload["variables"], dict)
        and set(payload["variables"]) == {"search"}
        and isinstance(payload["variables"]["search"], str)
        and payload["variables"]["search"]
    ):
        operation_kind = "magento_product_search"
    elif (
        parts.path == "/graphql"
        and document_sha256
        == GRAPHQL_DOCUMENT_SHA256_BY_OPERATION["magento_product_detail"]
        and set(payload) == {"query", "variables"}
        and isinstance(payload["variables"], dict)
        and set(payload["variables"]) == {"sku"}
        and isinstance(payload["variables"]["sku"], str)
        and payload["variables"]["sku"]
    ):
        operation_kind = "magento_product_detail"
    else:
        raise ReadOnlyPolicyError("Read-only HTTP rejects unclassified GraphQL document")
    return ReadOnlyOperation(
        operation_kind=operation_kind,
        body_sha256=body_sha256,
        document_sha256=document_sha256,
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ReadOnlyPolicyError("Read-only HTTP rejects duplicate JSON keys")
        value[key] = item
    return value


def _valid_wix_catalog_query(payload: object) -> bool:
    if not isinstance(payload, dict) or set(payload) != {"query", "includeVariants"}:
        return False
    query = payload["query"]
    if payload["includeVariants"] is not True or not isinstance(query, dict):
        return False
    if set(query) != {"filter", "paging"} or not isinstance(query["paging"], dict):
        return False
    paging = query["paging"]
    if (
        set(paging) != {"limit", "offset"}
        or type(paging["limit"]) is not int
        or paging["limit"] != 10
        or type(paging["offset"]) is not int
        or paging["offset"] != 0
        or not isinstance(query["filter"], str)
    ):
        return False
    try:
        filter_value = json.loads(query["filter"], object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(filter_value, dict) or set(filter_value) != {"name"}:
        return False
    name = filter_value["name"]
    return (
        isinstance(name, dict)
        and set(name) == {"$contains"}
        and isinstance(name["$contains"], str)
        and bool(name["$contains"])
    )
