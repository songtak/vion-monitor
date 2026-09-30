import json
import re
import unicodedata
from decimal import Decimal
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

FIELDS = ('name', 'price', 'volume', 'ingredients')
ENGINES = {
    'cafe24': {
        'name': ['.prdDetail .headingArea h2', '.xans-product-detail .headingArea h2', '.prd_name h2', '.detail_name', '.prdDetail h2'],
        'sale_price': ['#span_product_price_text', '#span_product_price_sale', '.price', '[class*=salePrice]'],
    },
    'godomall': {
        'name': ['.item_detail_tit h3', '.item_detail_tit', 'h1'],
        'sale_price': ['.item_price .price', '.item_price'],
    },
    'makeshop': {
        'name': ['.tit-prd', '.prdName', '.goods_title', '.itemname'],
        'sale_price': ['.price .sell', '.sellprice', '.price'],
    },
    'custom': {'name': [], 'sale_price': []},
}
LABELS = {
    'ingredients': ('전성분', '전체 성분', '모든 성분', '모든 원료성분', 'ingredients', 'ingredient list'),
    'volume': ('용량 또는 중량', '내용물의 용량 또는 중량', '용량/중량', '용량', '내용량', '중량'),
    'list_price': ('정가', '소비자가', '정상가', '소비자가격'),
    'price': ('판매가', '판매가격', '가격'),
}


def clean(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value or ''))).strip()


def money(value):
    m = re.search(r'(?<![\d.])(\d{1,3}(?:,\d{3})+|\d{1,8})(?:\.0+)?\s*(?:원|KRW)?', clean(value), re.I)
    return int(m.group(1).replace(',', '')) if m else None


def volume(value):
    m = re.search(r'(?<!\d)(\d+(?:\.\d+)?)\s*(ml|mL|g|kg|L)(?!\w)', clean(value), re.I)
    if not m: return None
    number, unit = Decimal(m.group(1)), m.group(2).lower()
    if unit == 'l': number, unit = number * 1000, 'ml'
    return f'{number.normalize():f}{unit}'


def sheet_volume(value):
    """Bare numbers in the product sheet are explicitly millilitres."""
    text = clean(value)
    return volume(text + 'ml') if re.fullmatch(r'\d+(?:\.\d+)?', text) else volume(text)


def ingredients(value):
    value = clean(value)
    value = re.sub(r'^(전성분|전체\s*성분|ingredients)\s*[:：]?\s*', '', value, flags=re.I)
    value = re.split(r'\s*(?:사용할 때 주의사항|사용 시 주의사항|소비자상담|품질보증기준|제조국)\s*[:：]?', value)[0]
    # Do not split chemical locants (1,2-Hexanediol) or amounts (5,000 ppm).
    parts, start, depth = [], 0, 0
    for i, char in enumerate(value):
        if char in '([': depth += 1
        elif char in ')]': depth = max(0, depth - 1)
        elif char in ',，、\n' and depth == 0:
            if char == ',' and i > 0 and i + 1 < len(value) and value[i-1].isdigit() and value[i+1].isdigit():
                continue
            parts.append(clean(value[start:i]).strip('* ')); start = i + 1
    parts.append(clean(value[start:]).strip('* '))
    parts = [re.sub(r'\s+', '', p).casefold() for p in parts if p]
    return parts if 2 <= len(parts) <= 250 and len(value) < 9000 else None


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


def label_matches(text, labels):
    text = re.sub(r'\s+', '', clean(text)).casefold().rstrip(':：')
    for label in labels:
        target = re.sub(r'\s+', '', label).casefold()
        if text == target: return True
        if target in ('모든성분', '모든원료성분') and text.endswith(target): return True
    return False


def label_value(soup, labels):
    # Adjacent pairs only: avoid a nested label being paired with another product's value.
    for label in soup.select('th, td:first-child, dt, li > h3, p, .clipboard-paste, li > strong, .label, .info-label, .product-notify-label'):
        if not label_matches(label.get_text(' ', strip=True), labels): continue
        val = label.find_next_sibling()
        if label.name in ('th', 'td') and (not val or val.name != 'td'): continue
        if val:
            text = clean(val.get_text(' ', strip=True))
            if text and text not in ('상세페이지 참조', '상세페이지 참고', '상품상세 참조', '-'): return text
    return None


def detail_images(html, url):
    """Evidence links, not a claim that an image contains an ingredient list."""
    soup = BeautifulSoup(html, 'html.parser')
    blocks = soup.select(
        '#prdDetail, .cont_detail, #detail, #detailView, #goodsDescription, '
        '.goods_description, .detail_cont, .detail-con, [class*="product-detail"], '
        '[class*="product_detail"], [class*="detail-content"]'
    )
    result = []
    for block in blocks:
        for img in block.select('img'):
            src = (img.get('data-src') or img.get('data-original') or img.get('data-lazy')
                   or img.get('ec-data-src') or img.get('src'))
            if not src:
                srcset = img.get('data-srcset') or img.get('srcset') or ''
                src = srcset.split(',')[-1].strip().split(' ')[0] if srcset else ''
            if not src or src.startswith('data:'): continue
            link = urljoin(url, src)
            if any(x in link for x in ('echosting', '/icon', '/btn_', '/medium/', '/small/')): continue
            if link not in result: result.append(link)
    return result


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
    matched = [p for p in products if clean(expected_name).replace(' ', '') in clean(p.get('name')).replace(' ', '')]
    matched = sorted(matched, key=lambda p: p.get('inLanguage') not in ('ko-KR', 'ko', None))
    product = (matched or products or [{}])[0]
    offers = product.get('offers') or {}
    if isinstance(offers, list): offers = offers[0] if offers else {}
    if not isinstance(offers, dict): offers = {}
    sources = {}
    name = (selector_value(soup, cfg.get('name', []))
            or label_value(soup, ('상품명', '제품명'))
            or selector_value(soup, engine['name']) or clean(product.get('name'))
            or selector_value(soup, ['meta[property="og:title"]', 'h1', 'title']))
    sources['name'] = '상품명 표기 / 구조화 데이터'

    # Ignore promotional prices. Explicit regular/MSRP wins over the sale field.
    regular = selector_value(soup, cfg.get('regular_price', [])) or label_value(soup, LABELS['list_price'])
    price = money(regular)
    if price: sources['price'] = '정상가/소비자가 (할인 전)'
    specs = offers.get('priceSpecification') or []
    if isinstance(specs, dict): specs = [specs]
    if not price:
        for spec in specs:
            if isinstance(spec, dict) and str(spec.get('priceType', '')).rsplit('/', 1)[-1] in ('StrikethroughPrice', 'ListPrice', 'MSRP'):
                price = money(spec.get('price'))
                if price:
                    sources['price'] = 'JSON-LD 할인 전 가격'; break
    if not price:
        base = selector_value(soup, cfg.get('base_price', [])) or label_value(soup, LABELS['price'])
        if not base and cfg['engine'] == 'cafe24':
            base = selector_value(soup, ['#span_product_price_text'])
        price = money(base)
        if price: sources['price'] = '기본 판매가 (쿠폰/추가 할인 제외)'
    if not price and cfg.get('jsonld_base_price'):
        price = money(offers.get('price'))
        if price: sources['price'] = '사이트 검증된 JSON-LD 기본 판매가'

    raw_volume = selector_value(soup, cfg.get('volume', [])) or label_value(soup, LABELS['volume']) or name
    size = volume(raw_volume)
    if not size:
        # Some structured groups keep the size only in their single variant name.
        variants = product.get('hasVariant') or []
        if isinstance(variants, dict): variants = [variants]
        sizes = {volume(v.get('name')) for v in variants if isinstance(v, dict)} - {None}
        if len(sizes) == 1: size = sizes.pop()
    raw_ing = selector_value(soup, cfg.get('ingredients', [])) or label_value(soup, LABELS['ingredients'])
    sources['ingredients'] = '상품정보 텍스트' if raw_ing else ''
    if not ingredients(raw_ing) and cfg.get('ingredient_labels'):
        raw_ing = label_value(soup, tuple(cfg['ingredient_labels']))
        if raw_ing: sources['ingredients'] = '사이트별 상품정보 표'
    if not ingredients(raw_ing):
        props = product.get('additionalProperty') or []
        if isinstance(props, dict): props = [props]
        for prop in props:
            if isinstance(prop, dict) and clean(prop.get('name')).lower() in ('성분', '전성분', 'ingredients'):
                raw_ing = prop.get('value')
                sources['ingredients'] = 'JSON-LD 성분'; break
    parsed_ing = ingredients(raw_ing) if raw_ing else None
    warnings = []
    if not name: warnings.append('제품명 미수집')
    if not price: warnings.append('할인 전 기본 가격 미수집: 할인가로 대체하지 않음')
    if not size: warnings.append('용량 미수집')
    elif not size.endswith('ml'):
        warnings.append(f'용량 단위 확인 필요: 시트는 ml / 페이지는 {size}; 자동 환산하지 않음')
        size = None
    image_urls = detail_images(html, url) if not parsed_ing else []
    if not parsed_ing:
        if image_urls:
            sources['ingredients'] = f'상세 이미지 후보 {len(image_urls)}개'
            warnings.append(f'전성분 텍스트 미수집: 상세 이미지 {len(image_urls)}개 확인, 이미지 검수 필요')
        else:
            warnings.append('전성분 텍스트 미수집: 렌더링 후에도 상세 이미지와 전성분 영역을 확인하지 못함')
    result = {'name': name or None, 'price': price, 'volume': size, 'ingredients': parsed_ing}
    # Preserve all observed values in evidence even when identity validation fails.
    observed = dict(result)
    tokens = [t.lower() for t in clean(expected_name).split() if len(t) > 1]
    overlap = sum(t in clean(name).lower() for t in tokens) / max(len(tokens), 1)
    if tokens and overlap < 0.5:
        warnings.append('제품명 불일치: 동일 제품 여부 수동 확인 필요')
        result = {field: None for field in FIELDS}
    result['_evidence'] = {'sources': sources, 'observed': observed,
                           'raw_volume': raw_volume, 'raw_ingredients': raw_ing,
                           'image_urls': image_urls}
    return result, warnings
