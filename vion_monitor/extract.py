import json
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup

FIELDS = ('name', 'list_price', 'sale_price', 'volume', 'ingredients', 'status')
ENGINES = {
    'cafe24': {
        'name': ['.prdDetail .headingArea h2', '.xans-product-detail .headingArea h2', '.prdDetail h2', 'h1'],
        'sale_price': ['#span_product_price_text', '#span_product_price_sale', '.price', '[class*=salePrice]'],
    },
    'godomall': {
        'name': ['.item_detail_tit h3', '.item_detail_tit', 'h1'],
        'sale_price': ['.item_price .price', '.item_price'],
    },
    'makeshop': {
        'name': ['.prdName', '.goods_title', '.itemname', 'h1'],
        'sale_price': ['.price .sell', '.sellprice', '.price'],
    },
    'custom': {'name': ['h1'], 'sale_price': []},
}
LABELS = {
    'ingredients': ('전성분', '전체 성분', '모든 성분', 'ingredients', 'ingredient list'),
    'volume': ('용량 또는 중량', '용량/중량', '용량', '내용량', '중량'),
    'list_price': ('정가', '소비자가', '판매가'),
    'sale_price': ('할인판매가', '할인가', '최종 판매가', '판매가격'),
}


def clean(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or ''))).strip()


def money(value):
    m = re.search(r'(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,8})\s*원?', clean(value))
    return int(m.group(1).replace(',', '')) if m else None


def volume(value):
    m = re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*(ml|mL|g|kg|L)(?!\w)', clean(value), re.I)
    return f'{m.group(1)}{m.group(2).lower()}' if m else None


def ingredients(value):
    value = clean(value)
    value = re.sub(r'^(전성분|전체\s*성분|ingredients)\s*[:：]?\s*', '', value, flags=re.I)
    value = re.split(r'\s*(?:사용할 때 주의사항|사용 시 주의사항|소비자상담|품질보증기준|제조국)\s*[:：]?', value)[0]
    parts = [clean(s).strip('* ') for s in re.split(r'[,，、]', value)]
    return parts if len(parts) >= 5 and len(parts) <= 250 and len(value) < 9000 else None


def site_for(url, sites):
    parsed = urlparse(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        return None, None
    host = parsed.hostname.lower().removeprefix('www.').removeprefix('m.')
    for key, cfg in sites.items():
        if host in cfg['domains'] and any(parsed.path.startswith(p) for p in cfg['paths']):
            return key, cfg
    return None, None


def structured_products(soup):
    products = []
    for element in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(element.string or element.get_text())
        except (ValueError, TypeError):
            continue
        def visit(node):
            if isinstance(node, list):
                for item in node: visit(item)
            elif isinstance(node, dict):
                typ = node.get('@type', '')
                if typ in ('Product', 'ProductGroup') or (isinstance(typ, list) and ('Product' in typ or 'ProductGroup' in typ)):
                    products.append(node)
                for nested in node.values():
                    if isinstance(nested, (list, dict)): visit(nested)
        visit(data)
    return products


def label_value(soup, labels):
    # Only paired label/value rows; never take the entire product-description block.
    for row in soup.select('tr, dl, li, .product-info-row'):
        label = row.select_one('th, dt, .label, .title')
        val = row.select_one('td, dd, .value, .content')
        if label and val and any(clean(label.get_text()).lower().startswith(x.lower()) for x in labels):
            return clean(val.get_text(' ', strip=True))
    return None


def selector_value(soup, selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            val = clean(node.get_text(' ', strip=True) or node.get('content'))
            if val: return val
    return None


def extract(html, url, cfg, expected_name='', expected_volume=''):
    soup = BeautifulSoup(html, 'html.parser')
    engine = ENGINES[cfg['engine']]
    products = structured_products(soup)
    # Many pages expose related products in JSON-LD. Prefer the primary exact match.
    matched = [p for p in products if clean(expected_name).replace(' ', '') in clean(p.get('name')).replace(' ', '')]
    matched = sorted(matched, key=lambda p: p.get('inLanguage') not in ('ko-KR', 'ko', None))
    product = (matched or products or [{}])[0]
    offers = product.get('offers', {})
    if isinstance(offers, list): offers = offers[0] if offers else {}
    if not isinstance(offers, dict): offers = {}
    name = selector_value(soup, cfg.get('name', []) + engine['name']) or clean(product.get('name'))
    if not name:
        name = selector_value(soup, ['meta[property="og:title"]', 'title'])
    raw_price = selector_value(soup, cfg.get('price', []) + engine['sale_price'])
    sale = money(raw_price) or money(offers.get('price'))
    specification = offers.get('priceSpecification') or {}
    if isinstance(specification, list): specification = specification[0] if specification else {}
    listed = money(label_value(soup, LABELS['list_price'])) or money(specification.get('price'))
    if listed == sale: listed = None
    raw_volume = label_value(soup, LABELS['volume']) or name
    size = volume(raw_volume)
    raw_ing = label_value(soup, LABELS['ingredients'])
    if not raw_ing:
        props = product.get('additionalProperty') or []
        if isinstance(props, dict): props = [props]
        for prop in props:
            if isinstance(prop, dict) and any(label in clean(prop.get('name')).lower() for label in ('성분', 'ingredients')):
                raw_ing = prop.get('value')
                break
    if not raw_ing:
        raw_ing = selector_value(soup, cfg.get('ingredients', []))
    parsed_ing = ingredients(raw_ing) if raw_ing else None
    availability = str(offers.get('availability') or '').lower()
    status = None
    if 'outofstock' in availability: status = '품절'
    elif 'instock' in availability: status = '판매중'
    # Avoid inferring status from promotional/related-product text.
    primary_button = selector_value(soup, ['.item_detail_list .btn_add_cart', '.xans-product-action .btnSubmit', '.btn_buy', '[class*=buyButton]'])
    if primary_button and ('품절' in primary_button or '구매 불가' in primary_button): status = '품절/구매불가'
    if primary_button and ('구매하기' in primary_button or '바로구매' in primary_button) and status is None: status = '판매중'
    result = {'name': name or None, 'list_price': listed, 'sale_price': sale,
              'volume': size, 'ingredients': parsed_ing, 'status': status}
    warnings = []
    if not name or not sale: warnings.append('제품명 또는 판매가 추출 실패')
    if not parsed_ing: warnings.append('전성분 추출 불가: 상세 이미지 등 확인 필요')
    expected_size = volume(expected_volume) or (f'{clean(expected_volume)}ml' if clean(expected_volume).isdigit() else None)
    if expected_size and size and size != expected_size:
        warnings.append(f'용량 불일치: 시트 {expected_volume} / 페이지 {size}')
        result['volume'] = None
    # A related or redirected page must not silently become another product.
    tokens = [t.lower() for t in clean(expected_name).split() if len(t) > 1]
    overlap = sum(t in clean(name).lower() for t in tokens) / max(len(tokens), 1)
    if tokens and overlap < 0.5:
        warnings.append('제품명 불일치: 다른 제품/리뉴얼 페이지 여부 확인')
        result = {field: None for field in FIELDS}
    return result, warnings
