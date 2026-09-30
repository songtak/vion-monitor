"""Select a bounded, brand-diverse product set for test runs."""
import os


def select_products(products, limit=None, distinct_brands=None):
    products = [product for product in products if product.get('url')]
    if limit is None:
        raw_limit = os.environ.get('TEST_PRODUCT_LIMIT', '').strip()
        limit = int(raw_limit) if raw_limit else None
    if distinct_brands is None:
        distinct_brands = os.environ.get('TEST_DISTINCT_BRANDS', 'false').lower() == 'true'
    if not limit or limit >= len(products):
        return products
    if not distinct_brands:
        return products[:limit]

    selected = []
    selected_ids = set()
    seen_brands = set()
    for product in products:
        brand = product.get('brand', '').strip().casefold()
        if not brand or brand in seen_brands:
            continue
        selected.append(product)
        selected_ids.add(product['id'])
        seen_brands.add(brand)
        if len(selected) == limit:
            return selected

    # If the inventory has fewer unique brands than requested, fill the rest
    # deterministically instead of silently processing fewer products.
    for product in products:
        if product['id'] in selected_ids:
            continue
        selected.append(product)
        if len(selected) == limit:
            break
    return selected
