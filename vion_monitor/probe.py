"""Validate site rules against the URL inventory without touching Sheets or Slack."""
import csv
import json
import time
from collections import Counter
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

from .__main__ import fetch
from .extract import FIELDS, extract, site_for


def main():
    sites = yaml.safe_load(Path('sites.yaml').read_text(encoding='utf8'))['sites']
    products = list(csv.DictReader(Path('products.csv').open(encoding='utf8')))
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for product in products:
                url = product['공식 상품 상세']
                if not url: continue
                key, cfg = site_for(url, sites)
                row = {'제품 ID':product['제품 ID'],'사이트':key or '미지원','URL':url}
                try:
                    if not cfg: raise RuntimeError('지원 규칙 없음')
                    html = fetch(browser,url)
                    data,warnings = extract(html,url,cfg,product['제품명'],product['용량'])
                    row.update({field: '확인' if data[field] is not None else '미수집' for field in FIELDS})
                    row['검수 사유'] = '; '.join(warnings)
                except Exception as exc:
                    row.update({field:'오류' for field in FIELDS})
                    row['검수 사유'] = str(exc)[:250]
                rows.append(row)
                print(product['제품 ID'],key,row['검수 사유'],flush=True)
                time.sleep(1.2)
        finally: browser.close()
    Path('local-output').mkdir(exist_ok=True)
    columns = ['제품 ID','사이트',*FIELDS,'검수 사유','URL']
    with Path('local-output/수집검증.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader();writer.writerows(rows)
    print('검증 완료:',len(rows),'개; 항목별 미수집/오류:',{k:sum(r[k] != '확인' for r in rows) for k in FIELDS})


if __name__ == '__main__': main()
