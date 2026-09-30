import json
import logging
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests
import yaml
from playwright.sync_api import sync_playwright

from .extract import FIELDS, extract, site_for
from .compare import FIELD_NAMES, compare_product, diff
from .selection import select_products
from .sheets import SheetStore

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger(__name__)


def send_slack(webhook, messages):
    if not messages: return
    if not webhook: raise RuntimeError('SLACK_WEBHOOK_URL 설정 필요')
    # Keep Slack payload under the platform size limit.
    for offset in range(0, len(messages), 15):
        body = '\n\n'.join(messages[offset:offset + 15])[:35000]
        res = requests.post(webhook, json={'text': body}, timeout=25)
        res.raise_for_status()
        if res.text.strip() != 'ok': raise RuntimeError(f'Slack 응답 오류: {res.status_code}')


def fetch(browser, url, render=False):
    candidate = None
    try:
        res = requests.get(url, timeout=15, headers={'User-Agent':'Mozilla/5.0 (compatible; VIONProductMonitor/1.0)'})
        if res.status_code == 200 and len(res.content) > 1200:
            try: text = res.content.decode('utf-8')
            except UnicodeDecodeError:
                res.encoding = res.apparent_encoding
                text = res.text
            candidate = text
            # Static product markup saves browser time; empty SPA shells fall through.
            if not render and (('application/ld+json' in text and ('Product' in text or 'ProductGroup' in text)) or '전성분' in text):
                return text
    except requests.RequestException:
        pass
    page = browser.new_page(locale='ko-KR', viewport={'width': 1360, 'height': 900})
    try:
        res = page.goto(url, wait_until='domcontentloaded', timeout=35000)
        page.wait_for_timeout(2500 if render else 900)
        if not res or res.status >= 400:
            raise RuntimeError(f'HTTP {res.status if res else "no response"}')
        html = page.content()
        if len(html) < 1000 or 'captcha' in page.title().lower():
            raise RuntimeError('페이지 접근 제한 또는 빈 응답')
        return html
    except Exception:
        if candidate is not None: return candidate
        raise
    finally:
        page.close()


def main():
    sites = yaml.safe_load(Path('sites.yaml').read_text(encoding='utf-8'))['sites']
    store = SheetStore()
    store.ensure_tabs(['수집상태','실행설정','변경이력'])
    if not store.values('수집상태'): store.append('수집상태', [['제품 ID','수집 JSON','확인 시각 UTC']])
    if not store.values('실행설정'): store.append('실행설정', [['항목','값']])
    if not store.values('변경이력'): store.append('변경이력', [['확인 시각 UTC','제품 ID','제품명','변경 항목','변경 내용','공식 URL','시트 값 JSON','공식 값 JSON']])
    last = store.last_run()
    if last and os.environ.get('FORCE_RUN','false').lower() != 'true':
        if datetime.now(timezone.utc) - last < timedelta(hours=1):
            LOG.info('1시간 미경과: 이번 실행 건너뜀')
            return 0
    products = select_products(store.products(os.environ.get('PRODUCT_SHEET_NAME','제품 데이터')))
    LOG.info('이번 실행 대상: %s개 (브랜드 %s개)', len(products), len({p['brand'] for p in products}))
    previous = store.previous()
    webhook = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook: raise RuntimeError('SLACK_WEBHOOK_URL 설정 필요')
    errors = []
    change_count = 0
    covered = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for p in products:
                if not p['url']: continue
                key, cfg = site_for(p['url'], sites)
                if not cfg:
                    errors.append(f"{p['id']} {p['name']}: 지원하지 않는 공식 URL {p['url']}")
                    continue
                covered += 1
                try:
                    html = fetch(browser, p['url'], render=cfg.get('render', False))
                    current, warnings = extract(html,p['url'],cfg,p['name'],p['volume'])
                    saved = previous.get(p['id'], (None, {}))[1]
                    before, changes, state, comparison_warnings = compare_product(p, current, saved)
                    warnings += comparison_warnings
                    if warnings:
                        errors.append(f"{p['id']} {p['name']} ({key}): {', '.join(warnings)}")
                    if changes:
                        stamp = datetime.now(timezone.utc).isoformat()
                        # Durable history before notification and deduplication state.
                        # Failure retries the alert; a successful baseline can never erase the history.
                        histories = [[stamp, p['id'], p['name'], FIELD_NAMES[f], summary, p['url'],
                                      json.dumps(before[f], ensure_ascii=False),
                                      json.dumps(current[f], ensure_ascii=False)] for f, summary in changes]
                        store.append('변경이력', histories)
                        summary = '\n'.join(f'• {FIELD_NAMES[f]}: {v[:1800]}' for f, v in changes)
                        message = f"🔎 시트와 공식 페이지 차이 | #{p['id']} {p['name']}\n{summary}\n{p['url']}"
                        send_slack(webhook, [message])
                        change_count += len(changes)
                    store.save_snapshot(p['id'], state, previous)
                except Exception as exc:
                    errors.append(f"{p['id']} {p['name']} ({key}): {type(exc).__name__} {str(exc)[:130]}")
                time.sleep(1.2)  # Polite rate limit per page.
        finally:
            browser.close()
    for error in errors: LOG.warning('%s', error)
    if errors: send_slack(webhook,['⚠️ VION 수집 검수 필요\n'+'\n'.join(errors[:25])]+(['추가 오류 '+str(len(errors)-25)+'건: 실행 로그 확인'] if len(errors)>25 else []))
    store.mark_run()
    LOG.info('Done: %s products, %s with URL, %s changes, %s warnings',len(products),covered,change_count,len(errors))
    return 0 if not errors else 2


if __name__ == '__main__':
    try: sys.exit(main())
    except Exception:
        LOG.exception('전체 실행 실패')
        sys.exit(1)
