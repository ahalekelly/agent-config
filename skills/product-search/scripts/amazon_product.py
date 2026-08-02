# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "beautifulsoup4>=4.14,<5",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag

ORIGIN = "https://www.amazon.com"
AOD_PATH = "/gp/product/ajax/aodAjaxMain/ref=auto_load_aod"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
ASIN_PATTERN = re.compile(r"[A-Z0-9]{10}")
URL_ASIN_PATTERN = re.compile(
    r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", re.IGNORECASE
)
AMAZON_HOSTS = {"amazon.com", "us.amazon.com", "www.amazon.com"}


def parse_asin(product: str) -> str:
    value = product.strip()
    asin = value.upper()
    if ASIN_PATTERN.fullmatch(asin):
        return asin

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("product must be a US Amazon ASIN or product URL") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname not in AMAZON_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise ValueError("product must be a US Amazon ASIN or product URL")
    match = URL_ASIN_PATTERN.search(parsed.path + "/")
    if not match:
        raise ValueError("Amazon product URL has no /dp/ or /gp/product/ ASIN")
    return match.group(1).upper()


def fetch(asin: str, client: httpx.Client) -> dict[str, object]:
    if not ASIN_PATTERN.fullmatch(asin):
        raise ValueError("asin must contain exactly 10 uppercase letters or digits")

    bootstrap = client.get(ORIGIN + "/")
    if bootstrap.status_code not in {200, 202}:
        raise RuntimeError(
            f"Amazon anonymous-session bootstrap returned HTTP {bootstrap.status_code}"
        )

    response = client.get(
        ORIGIN + AOD_PATH,
        params={"asin": asin, "pc": "dp"},
        headers={
            "Accept": "text/html,*/*",
            "Referer": f"{ORIGIN}/dp/{asin}",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    if response.status_code == 404:
        return {
            "source": "Amazon all-offers display",
            "status": "aod_unavailable",
            "asin": asin,
            "product_url": f"{ORIGIN}/dp/{asin}",
            "retrieved_at": retrieved_at,
        }
    if response.status_code != 200:
        raise RuntimeError(
            f"Amazon all-offers endpoint returned HTTP {response.status_code}; "
            "do not retry or add a bypass"
        )
    return parse_product(asin, response.text, retrieved_at)


def parse_product(asin: str, html: str, retrieved_at: str) -> dict[str, object]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#aod-container") is None:
        raise RuntimeError(
            "Amazon all-offers response omitted #aod-container; blocked or schema changed"
        )

    title = _text(soup.select_one("#aod-asin-title-text"), "product title")
    image = soup.select_one("#aod-asin-image-id")
    if not isinstance(image, Tag):
        raise RuntimeError("Amazon all-offers response omitted the product image")
    image_url = image.get("src")
    if not isinstance(image_url, str) or not _is_https_url(image_url):
        raise RuntimeError("Amazon all-offers response had an invalid product image URL")

    count_node = soup.select_one("#aod-total-offer-count")
    if not isinstance(count_node, Tag):
        raise RuntimeError("Amazon all-offers response omitted the other-offer count")
    count_text = count_node.get("value")
    if not isinstance(count_text, str) or not count_text.isdigit():
        raise RuntimeError("Amazon all-offers response had an invalid other-offer count")
    reported_count = int(count_text)

    pinned = soup.select_one("#aod-pinned-offer")
    if not isinstance(pinned, Tag):
        raise RuntimeError("Amazon all-offers response omitted the featured-offer block")
    other_nodes = soup.select("#aod-offer")
    if reported_count < len(other_nodes):
        raise RuntimeError("Amazon returned more other offers than its reported count")

    featured_price = pinned.select_one(".apex-pricetopay-value")
    no_featured = "No featured offers available" in pinned.get_text(" ", strip=True)
    if featured_price is not None and no_featured:
        raise RuntimeError("Amazon returned conflicting featured-offer states")
    if featured_price is None and not no_featured:
        raise RuntimeError("Amazon featured-offer block had no price or unavailable state")

    other_offers = [_offer(node) for node in other_nodes]
    if featured_price is None and not other_offers:
        offers: dict[str, object] = {"status": "no_offers"}
    else:
        featured: dict[str, object]
        if featured_price is None:
            featured = {"status": "unavailable"}
        else:
            featured = {"status": "available", "offer": _offer(pinned)}
        offers = {
            "status": "offers",
            "featured": featured,
            "reported_other_offer_count": reported_count,
            "other_offers_complete": reported_count == len(other_offers),
            "other_offers": other_offers,
        }

    return {
        "source": "Amazon all-offers display",
        "status": "found",
        "asin": asin,
        "product_url": f"{ORIGIN}/dp/{asin}",
        "title": title,
        "image_url": image_url,
        "reviews": _reviews(soup),
        "offers": offers,
        "delivery_scope": "anonymous_default_location",
        "retrieved_at": retrieved_at,
    }


def _offer(node: Tag) -> dict[str, object]:
    condition = _text(node.select_one("#aod-offer-heading"), "offer condition")
    price_node = node.select_one(".apex-pricetopay-value")
    if not isinstance(price_node, Tag):
        raise RuntimeError("Amazon offer omitted its price")
    if node.select_one("form.AodAddToCart") is None:
        raise RuntimeError("Amazon priced offer had no add-to-cart form")

    sold_by = _party(node, "#aod-offer-soldBy", "seller")
    ships_from = _party(node, "#aod-offer-shipsFrom", "shipper")
    deliveries = [
        {
            "price_text": _attribute(delivery, "data-csa-c-delivery-price"),
            "time": _attribute(delivery, "data-csa-c-delivery-time"),
            "condition": _attribute(delivery, "data-csa-c-delivery-condition"),
            "text": _text(delivery, "delivery promise"),
        }
        for delivery in node.select("[data-csa-c-delivery-price]")
    ]
    return {
        "condition": condition,
        "price": _price(price_node),
        "ships_from": ships_from,
        "sold_by": sold_by,
        "delivery_promises": deliveries,
    }


def _price(node: Tag) -> dict[str, str]:
    symbol = _text(node.select_one(".a-price-symbol"), "price symbol")
    whole_text = _text(node.select_one(".a-price-whole"), "whole price")
    fraction = _text(node.select_one(".a-price-fraction"), "fractional price")
    whole = re.sub(r"[,.\s]", "", whole_text)
    if symbol != "$" or not whole.isdigit() or not re.fullmatch(r"\d{2}", fraction):
        raise RuntimeError("Amazon offer had an invalid USD price")
    return {"amount": f"{int(whole)}.{fraction}", "currency": "USD"}


def _party(node: Tag, selector: str, field: str) -> str:
    block = node.select_one(selector)
    if not isinstance(block, Tag):
        raise RuntimeError(f"Amazon offer omitted its {field}")
    value = block.select_one(".a-fixed-left-grid-col.a-col-right > a")
    if value is None:
        value = block.select_one(".a-fixed-left-grid-col.a-col-right > span")
    return _text(value, field)


def _reviews(soup: BeautifulSoup) -> dict[str, object]:
    star = soup.select_one("#aod-asin-reviews-star .a-icon-alt")
    count = soup.select_one("#aod-asin-reviews-count-title")
    if star is None and count is None:
        return {"status": "unrated"}
    if star is None or count is None:
        raise RuntimeError("Amazon returned an incomplete product-rating block")

    star_match = re.fullmatch(r"(\d(?:\.\d)?) out of 5 stars", _text(star, "rating"))
    count_match = re.fullmatch(r"([\d,]+) ratings", _text(count, "rating count"))
    if not star_match or not count_match:
        raise RuntimeError("Amazon returned an invalid product-rating block")
    rating = float(star_match.group(1))
    rating_count = int(count_match.group(1).replace(",", ""))
    if not 0 <= rating <= 5:
        raise RuntimeError("Amazon returned a product rating outside 0–5")
    return {"status": "rated", "rating": rating, "count": rating_count}


def _text(node: Tag | None, field: str) -> str:
    if not isinstance(node, Tag):
        raise RuntimeError(f"Amazon response omitted {field}")
    value = node.get_text(" ", strip=True)
    if not value:
        raise RuntimeError(f"Amazon response had an empty {field}")
    return value


def _attribute(node: Tag, name: str) -> str:
    value = node.get(name)
    if not isinstance(value, str):
        raise RuntimeError(f"Amazon delivery promise omitted {name}")
    return value.strip()


def _is_https_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and port in {None, 443}
    )


def lookup(product: str) -> dict[str, object]:
    asin = parse_asin(product)
    with httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=30,
        follow_redirects=False,
    ) as client:
        return fetch(asin, client)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read one US Amazon product and its current offer panel by ASIN."
    )
    parser.add_argument("product", help="ASIN or US Amazon /dp/ product URL")
    args = parser.parse_args()
    try:
        result = lookup(args.product)
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
