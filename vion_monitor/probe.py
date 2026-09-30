"""Read-only collection review; never sends Slack or writes to Google Sheets."""
import argparse
import csv
import json
import os
import time
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from .__main__ import fetch
from .compare import baseline, compare_product
from .extract import FIELDS, extract, site_for
from .selection import select_products


def csv_products(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            yield {'id': row['제품 ID'], 'name': row['제품명'], 'brand': row['브랜드명'],
                   'volume': row['용량'], 'price': row.get('가격(원)', ''),
                   'ingredients': row.get('전성분', ''), 'url': row['공식 상품 상세']}


def report_row(product, key, data, warnings):
    before, changes, _, extra = compare_product(product, data)
    row = {'제품 ID': product['id'], '제품명': product['name'], '사이트': key, 'URL': product['url']}
    for field in FIELDS:
        row[field] = '추출' if data.get(field) is not None else '미수집'
        row[field + '_시트값'] = json.dumps(before[field], ensure_ascii=False) if isinstance(before[field], list) else before[field]
        row[field + '_수집값'] = json.dumps(data.get(field), ensure_ascii=False) if isinstance(data.get(field), list) else data.get(field)
    evidence = data.get('_evidence', {})
    row['시트와 다른 항목'] = ', '.join(f for f, _ in changes)
    row['검수 사유'] = '; '.join(warnings + extra)
    row['가격 근거'] = evidence.get('sources', {}).get('price', '')
    row['성분 근거'] = evidence.get('sources', {}).get('ingredients', '')
    row['페이지 용량 원문'] = evidence.get('raw_volume', '')
    row['성분 원문'] = evidence.get('raw_ingredients', '')
    row['상세 이미지 URL'] = '\n'.join(evidence.get('image_urls', []))
    row['거부 전 추출값'] = json.dumps(evidence.get('observed', {}), ensure_ascii=False)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', choices=['csv', 'sheets'], default='csv')
    parser.add_argument('--input', default='products.csv')
    parser.add_argument('--ids', help='Comma-separated product IDs for focused verification')
    args = parser.parse_args()
    if args.source == 'sheets':
        from .sheets import SheetStore
        products = SheetStore().products(os.environ.get('PRODUCT_SHEET_NAME', '제품 데이터'))
    else:
        products = list(csv_products(args.input))
    if args.ids:
        wanted = set(args.ids.split(',')); products = [p for p in products if p['id'] in wanted]
    else:
        products = select_products(products)
    sites = yaml.safe_load(Path('sites.yaml').read_text(encoding='utf8'))['sites']
    output = Path('local-output'); output.mkdir(exist_ok=True)
    evidence_dir = output / 'evidence'; evidence_dir.mkdir(exist_ok=True)
    columns = ['제품 ID', '제품명', '사이트', *FIELDS,
               *[field + suffix for field in FIELDS for suffix in ('_시트값', '_수집값')],
               '시트와 다른 항목', '검수 사유', '가격 근거', '성분 근거', '페이지 용량 원문',
               '성분 원문', '상세 이미지 URL', '거부 전 추출값', 'URL']
    rows = []
    with (output / '수집검증.csv').open('w', encoding='utf-8-sig', newline='') as f, sync_playwright() as pw:
        writer = csv.DictWriter(f, fieldnames=columns); writer.writeheader(); f.flush()
        browser = pw.chromium.launch(headless=True)
        try:
            for number, product in enumerate(products, 1):
                if not product['url']: continue
                key, cfg = site_for(product['url'], sites)
                try:
                    if not cfg: raise RuntimeError('지원 규칙 없음')
                    html = fetch(browser, product['url'], render=cfg.get('render', False),
                                 click=cfg.get('click'), wait_for=cfg.get('wait_for'),
                                 scroll=cfg.get('scroll', False))
                    # Numeric filenames are independent of user-supplied product IDs.
                    stem = f'{number:03d}'
                    (evidence_dir / f'{stem}.html').write_text(html, encoding='utf8')
                    data, warnings = extract(html, product['url'], cfg, product['name'], product['volume'])
                    (evidence_dir / f'{stem}.json').write_text(json.dumps(
                        {'product_id': product['id'], 'url': product['url'], 'data': data, 'warnings': warnings},
                        ensure_ascii=False, indent=2), encoding='utf8')
                    row = report_row(product, key, data, warnings)
                except Exception as exc:
                    row = {'제품 ID': product['id'], '제품명': product['name'], '사이트': key or '미지원',
                           'URL': product['url'], **{field: '오류' for field in FIELDS},
                           '검수 사유': f'{type(exc).__name__}: {str(exc)[:250]}'}
                rows.append(row); writer.writerow(row); f.flush()
                print(product['id'], key, row['검수 사유'], flush=True)
                time.sleep(1.2)
        finally:
            browser.close()
    print('검증 완료:', len(rows), '개; 항목별 미수집/오류:',
          {k: sum(r[k] != '추출' for r in rows) for k in FIELDS})


if __name__ == '__main__': main()
