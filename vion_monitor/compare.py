"""Compare official observations with the current, human-maintained product sheet."""
import json
import re
from collections import Counter

from .extract import FIELDS, clean, ingredients, money, sheet_volume

FIELD_NAMES = {'name': '제품명', 'price': '가격(할인 전)', 'volume': '용량(ml)', 'ingredients': '전성분'}


def baseline(product):
    return {'name': clean(product['name']) or None,
            'price': money(product.get('price')),
            'volume': sheet_volume(product.get('volume')),
            'ingredients': ingredients(product.get('ingredients'))}


def diff(old, new):
    result = []
    for field in FIELDS:
        before, after = old.get(field), new.get(field)
        if before is None or after is None or before == after: continue
        if field == 'ingredients':
            removed = list((Counter(before) - Counter(after)).elements())
            added = list((Counter(after) - Counter(before)).elements())
            summary = f'추가 {added} / 삭제 {removed}' if added or removed else '성분 표기 순서 변경'
        else:
            summary = f'{before} → {after}'
        result.append((field, summary))
    return result


def name_key(name, brand):
    # Size has its own comparison; a brand prefix is not a product-name change.
    text = clean(name)
    if brand and text.startswith(clean(brand)): text = text[len(clean(brand)):]
    text = re.sub(r'\d+(?:\.\d+)?\s*(?:ml|g|kg|l)(?![a-z])', '', text, flags=re.I)
    return re.sub(r'[\s™®]', '', text).strip()


def compare_product(product, current, saved=None):
    before = baseline(product)
    comparable = {f: current.get(f) for f in FIELDS}
    warnings = []
    for field in FIELDS:
        if before[field] is None: warnings.append(f'시트 {FIELD_NAMES[field]} 기준값 없음/형식 확인 필요')
    if name_key(before['name'], product.get('brand')) == name_key(comparable['name'], product.get('brand')):
        comparable['name'] = before['name']
    if before['ingredients'] and comparable['ingredients']:
        has_korean = lambda values: bool(re.search('[가-힣]', ' '.join(values)))
        if has_korean(before['ingredients']) != has_korean(comparable['ingredients']):
            warnings.append('전성분 표기 언어 다름: 번역/동의어 변환 없이 수동 대조 필요')
            comparable['ingredients'] = None
    changes = diff(before, comparable)
    saved = saved or {}
    notified = dict(saved.get('_notified', {})) if saved.get('_comparison_version') == 1 else {}
    pending = []
    for field in FIELDS:
        if before[field] is None or comparable[field] is None: continue
        if before[field] == comparable[field]: notified.pop(field, None)
    for field, summary in changes:
        signature = json.dumps([product['url'], before[field], comparable[field]], ensure_ascii=False, sort_keys=True)
        if notified.get(field) != signature: pending.append((field, summary))
        notified[field] = signature
    state = {f: current.get(f) for f in FIELDS}
    state.update(_comparison_version=1, _notified=notified)
    return before, pending, state, warnings
