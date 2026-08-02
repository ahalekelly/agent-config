# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "beautifulsoup4>=4.14,<5",
#   "httpx>=0.28,<0.29",
# ]
# ///

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))

import amazon_product

RETRIEVED_AT = "2026-08-02T06:00:00Z"

PRODUCT_HTML = """
<div id="aod-container">
  <h5 id="aod-asin-title-text">Example magnetic battery</h5>
  <img id="aod-asin-image-id" src="https://m.media-amazon.com/images/I/example.jpg">
  <i id="aod-asin-reviews-star"><span class="a-icon-alt">4.2 out of 5 stars</span></i>
  <span id="aod-asin-reviews-count-title">3,285 ratings</span>
  <input id="aod-total-offer-count" value="3">
  <div id="aod-pinned-offer">
    <div id="aod-offer-heading">New</div>
    <span class="a-price apex-pricetopay-value">
      <span class="a-price-symbol">$</span>
      <span class="a-price-whole">34.</span>
      <span class="a-price-fraction">16</span>
    </span>
    <div id="aod-offer-shipsFrom">
      <div class="a-fixed-left-grid-col a-col-right"><span>Amazon.com</span></div>
    </div>
    <div id="aod-offer-soldBy">
      <div class="a-fixed-left-grid-col a-col-right"><a>Example Seller</a></div>
    </div>
    <span data-csa-c-delivery-price="FREE"
          data-csa-c-delivery-time="Thursday, August 6"
          data-csa-c-delivery-condition="on orders over $35">
      FREE delivery Thursday, August 6 on orders over $35
    </span>
    <form class="AodAddToCart">
      <input type="hidden" name="anti-csrftoken-a2z" value="secret-token">
    </form>
  </div>
  <div id="aod-offer">
    <div id="aod-offer-heading">Used - Very Good</div>
    <span class="a-price apex-pricetopay-value">
      <span class="a-price-symbol">$</span>
      <span class="a-price-whole">1,234.</span>
      <span class="a-price-fraction">05</span>
    </span>
    <div id="aod-offer-shipsFrom">
      <div class="a-fixed-left-grid-col a-col-right"><span>Marketplace warehouse</span></div>
    </div>
    <div id="aod-offer-soldBy">
      <div class="a-fixed-left-grid-col a-col-right"><span>Second Seller</span></div>
    </div>
    <span data-csa-c-delivery-price="fastest"
          data-csa-c-delivery-time="August 7 - 9"
          data-csa-c-delivery-condition="">Fastest delivery August 7 - 9</span>
    <form class="AodAddToCart"></form>
  </div>
</div>
"""

NO_OFFERS_HTML = """
<div id="aod-container">
  <h5 id="aod-asin-title-text">Unavailable example</h5>
  <img id="aod-asin-image-id" src="https://m.media-amazon.com/images/I/unavailable.jpg">
  <input id="aod-total-offer-count" value="0">
  <div id="aod-pinned-offer">No featured offers available</div>
</div>
"""


class AmazonProductTest(unittest.TestCase):
    def test_normalizes_product_and_offer_panel_without_session_material(self) -> None:
        result = amazon_product.parse_product(
            "B0CZP3CDSZ", PRODUCT_HTML, RETRIEVED_AT
        )

        self.assertEqual(result["status"], "found")
        self.assertEqual(result["title"], "Example magnetic battery")
        self.assertEqual(
            result["reviews"], {"status": "rated", "rating": 4.2, "count": 3285}
        )
        offers = result["offers"]
        self.assertEqual(offers["status"], "offers")
        self.assertEqual(
            offers["featured"],
            {
                "status": "available",
                "offer": {
                    "condition": "New",
                    "price": {"amount": "34.16", "currency": "USD"},
                    "ships_from": "Amazon.com",
                    "sold_by": "Example Seller",
                    "delivery_promises": [
                        {
                            "price_text": "FREE",
                            "time": "Thursday, August 6",
                            "condition": "on orders over $35",
                            "text": "FREE delivery Thursday, August 6 on orders over $35",
                        }
                    ],
                },
            },
        )
        self.assertEqual(offers["reported_other_offer_count"], 3)
        self.assertFalse(offers["other_offers_complete"])
        self.assertEqual(
            offers["other_offers"][0]["price"],
            {"amount": "1234.05", "currency": "USD"},
        )
        self.assertEqual(
            offers["other_offers"][0]["delivery_promises"][0]["price_text"],
            "fastest",
        )
        self.assertNotIn("secret-token", json.dumps(result))

    def test_models_no_offers_and_no_reviews_explicitly(self) -> None:
        result = amazon_product.parse_product(
            "B0BM4274QM", NO_OFFERS_HTML, RETRIEVED_AT
        )
        self.assertEqual(result["reviews"], {"status": "unrated"})
        self.assertEqual(result["offers"], {"status": "no_offers"})

    def test_models_other_offers_without_a_featured_offer(self) -> None:
        html = PRODUCT_HTML.replace(
            '<div id="aod-offer-heading">New</div>\n'
            '    <span class="a-price apex-pricetopay-value">',
            'No featured offers available\n    <span class="a-price removed-price">',
            1,
        ).replace(
            '<input id="aod-total-offer-count" value="3">',
            '<input id="aod-total-offer-count" value="1">',
        )
        result = amazon_product.parse_product("B0CZP3CDSZ", html, RETRIEVED_AT)
        self.assertEqual(
            result["offers"]["featured"], {"status": "unavailable"}
        )
        self.assertTrue(result["offers"]["other_offers_complete"])

    def test_rejects_an_offer_count_smaller_than_the_returned_page(self) -> None:
        html = PRODUCT_HTML.replace(
            '<input id="aod-total-offer-count" value="3">',
            '<input id="aod-total-offer-count" value="0">',
        )
        with self.assertRaisesRegex(RuntimeError, "more other offers"):
            amazon_product.parse_product("B0CZP3CDSZ", html, RETRIEVED_AT)

    def test_rejects_an_unknown_featured_offer_state(self) -> None:
        html = NO_OFFERS_HTML.replace("No featured offers available", "")
        with self.assertRaisesRegex(RuntimeError, "no price or unavailable"):
            amazon_product.parse_product("B0BM4274QM", html, RETRIEVED_AT)

    def test_fetch_uses_one_bootstrap_and_one_read_only_aod_request(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.content, b"")
            if request.url.path == "/":
                return httpx.Response(202, request=request)
            self.assertEqual(request.url.path, amazon_product.AOD_PATH)
            self.assertEqual(request.url.params["asin"], "B0CZP3CDSZ")
            self.assertEqual(request.url.params["pc"], "dp")
            self.assertEqual(request.headers["x-requested-with"], "XMLHttpRequest")
            return httpx.Response(200, text=PRODUCT_HTML, request=request)

        with httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": amazon_product.USER_AGENT},
        ) as client:
            result = amazon_product.fetch("B0CZP3CDSZ", client)

        self.assertEqual(result["status"], "found")
        self.assertEqual(len(requests), 2)

    def test_fetch_does_not_claim_that_aod_404_means_product_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            status = 200 if request.url.path == "/" else 404
            return httpx.Response(status, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            result = amazon_product.fetch("B000IB9QXI", client)

        self.assertEqual(result["status"], "aod_unavailable")
        self.assertNotIn("title", result)

    def test_fetch_fails_once_on_a_block_instead_of_retrying(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            status = 202 if request.url.path == "/" else 503
            return httpx.Response(status, request=request)

        with (
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
            self.assertRaisesRegex(RuntimeError, "do not retry or add a bypass"),
        ):
            amazon_product.fetch("B0CZP3CDSZ", client)
        self.assertEqual(len(requests), 2)

    def test_parses_only_us_amazon_asins_and_product_urls(self) -> None:
        self.assertEqual(amazon_product.parse_asin("b0czp3cdsz"), "B0CZP3CDSZ")
        self.assertEqual(
            amazon_product.parse_asin(
                "https://www.amazon.com/Example-Product/dp/B0CZP3CDSZ?th=1"
            ),
            "B0CZP3CDSZ",
        )
        self.assertEqual(
            amazon_product.parse_asin(
                "https://amazon.com/gp/product/B0CZP3CDSZ/ref=something"
            ),
            "B0CZP3CDSZ",
        )
        for value in (
            "",
            "not-an-asin",
            "https://www.amazon.co.uk/dp/B0CZP3CDSZ",
            "https://example.com/dp/B0CZP3CDSZ",
            "https://user@amazon.com/dp/B0CZP3CDSZ",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                amazon_product.parse_asin(value)


if __name__ == "__main__":
    unittest.main()
