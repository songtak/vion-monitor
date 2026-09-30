import unittest
from unittest.mock import patch, Mock
from datetime import datetime, timezone, timedelta

from vion_monitor.compare import baseline, compare_product
from vion_monitor.extract import extract, ingredients, label_value
from vion_monitor.sheets import SheetStore
from bs4 import BeautifulSoup


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.product = {'id':'1', 'name':'토너', 'brand':'브랜드', 'price':'15,300',
                        'volume':'500', 'ingredients':'정제수, 1,2-헥산다이올, 세라마이드엔피(5,000 ppb)',
                        'url':'https://example.com/product/1'}
        self.current = baseline(self.product)

    def test_initial_run_compares_sheet_and_deduplicates(self):
        self.current['price'] = 17000
        _, changes, saved, _ = compare_product(self.product, self.current)
        self.assertEqual(changes, [('price', '15300 → 17000')])
        self.assertEqual(compare_product(self.product, self.current, saved)[1], [])
        self.product['price'] = '16,000'
        self.assertEqual(compare_product(self.product, self.current, saved)[1], [('price', '16000 → 17000')])

    def test_manual_correction_clears_notification(self):
        self.current['price'] = 17000
        saved = compare_product(self.product, self.current)[2]
        self.product['price'] = '17000'
        _, changes, saved, _ = compare_product(self.product, self.current, saved)
        self.assertFalse(changes)
        self.assertNotIn('price', saved['_notified'])
        self.current['price'] = 18000
        self.assertTrue(compare_product(self.product, self.current, saved)[1])

    def test_missing_price_does_not_block_other_fields_or_erase_dedup(self):
        self.current['price'] = 17000
        saved = compare_product(self.product, self.current)[2]
        self.current.update(price=None, volume='400ml')
        _, changes, saved, _ = compare_product(self.product, self.current, saved)
        self.assertEqual([f for f, _ in changes], ['volume'])
        self.assertIn('price', saved['_notified'])
        self.current['price'] = 17000
        self.assertFalse(compare_product(self.product, self.current, saved)[1])

    def test_legacy_snapshot_does_not_suppress_sheet_differences(self):
        self.current['price'] = 17000
        self.assertTrue(compare_product(self.product, self.current, {'sale_price':17000})[1])

    def test_size_and_brand_in_title_are_compared_separately(self):
        self.current['name'] = '브랜드 토너 500ml'
        self.assertFalse(compare_product(self.product, self.current)[1])

    def test_english_ingredients_require_review(self):
        self.current['ingredients'] = ingredients('Water, Glycerin, 1,2-Hexanediol')
        _, changes, _, warnings = compare_product(self.product, self.current)
        self.assertFalse(changes)
        self.assertTrue(any('언어' in w for w in warnings))

    def test_chemical_commas_are_not_separators(self):
        self.assertEqual(ingredients('정제수, 1,2-헥산다이올, 세라마이드엔피(5,000 ppb)'),
                         ['정제수', '1,2-헥산다이올', '세라마이드엔피(5,000ppb)'])

    def test_discount_excluded_and_volume_change_preserved(self):
        html = '<h1>토너 400ml</h1><table><tr><th>소비자가</th><td>20,000원</td></tr><tr><th>판매가</th><td>15,000원</td></tr></table>'
        current, _ = extract(html, self.product['url'], {'engine':'custom'}, '토너', '500')
        self.assertEqual(current['price'], 20000)
        self.assertEqual(current['volume'], '400ml')
        self.assertIn('volume', [f for f, _ in compare_product(self.product,current)[1]])

    def test_grams_are_not_millilitres(self):
        current, warnings = extract('<h1>크림 80g</h1>', self.product['url'], {'engine':'custom'}, '크림', '80')
        self.assertIsNone(current['volume'])
        self.assertTrue(any('단위' in w for w in warnings))

    def test_discount_only_price_is_unavailable(self):
        current, _ = extract('<h1>토너</h1><table><tr><th>할인판매가</th><td>9,900원</td></tr></table>',
                             self.product['url'], {'engine':'custom'}, '토너')
        self.assertIsNone(current['price'])

    def test_disclosure_label_and_div_pairs(self):
        html='<h1>토너 300ml</h1><div class="info-row"><div class="info-label">화장품법에 따라 기재해야 하는 모든 성분</div><div class="info-content">정제수, 글리세린, 1,2-헥산다이올</div></div>'
        current, _ = extract(html, self.product['url'], {'engine':'custom'}, '토너')
        self.assertEqual(current['ingredients'], ['정제수','글리세린','1,2-헥산다이올'])

    def test_table_header_never_becomes_product_name(self):
        soup=BeautifulSoup('<table><tr><th>상품명</th><th>상품수</th><th>가격</th></tr></table>', 'html.parser')
        self.assertIsNone(label_value(soup, ('상품명',)))

    def test_read_sheet_price_and_ingredients_with_title_row(self):
        store=SheetStore.__new__(SheetStore)
        store.values=Mock(return_value=[['목록'],['제품 ID','제품명','가격(원)','브랜드명','용량','전성분','공식 상품 상세'],
                                      ['1','토너','15,300','브랜드','500','정제수, 판테놀',self.product['url']]])
        product=store.products('제품 데이터')[0]
        self.assertEqual(product['price'], '15,300')
        self.assertEqual(product['ingredients'], '정제수, 판테놀')


class MonitorOrderingTests(unittest.TestCase):
    def run_monitor(self, fail_history=False, fail_slack=False):
        import vion_monitor.__main__ as monitor
        product={'id':'1','name':'토너','brand':'브랜드','price':'10000','volume':'100',
                 'ingredients':'정제수, 글리세린','url':'https://example.com/product/1'}
        current=baseline(product);current['price']=12000
        events=[]
        store=Mock()
        store.values.return_value=[['header']];store.last_run.return_value=None
        store.products.return_value=[product];store.previous.return_value={}
        def append(tab, rows):
            events.append('history')
            if fail_history: raise RuntimeError('history failed')
        def slack(url, messages):
            events.append('slack')
            if fail_slack: raise RuntimeError('slack failed')
        store.append.side_effect=append
        store.save_snapshot.side_effect=lambda *args:events.append('snapshot')
        with patch.object(monitor,'SheetStore',return_value=store), \
             patch.object(monitor,'sync_playwright'), patch.object(monitor,'fetch',return_value='html'), \
             patch.object(monitor,'site_for',return_value=('test',{'engine':'custom'})), \
             patch.object(monitor,'extract',return_value=(current,[])), \
             patch.object(monitor,'send_slack',side_effect=slack), patch.object(monitor.time,'sleep'), \
             patch.dict(monitor.os.environ,{'SLACK_WEBHOOK_URL':'fake'}):
            try: monitor.main()
            except RuntimeError:
                if not fail_slack: raise
        return events

    def test_history_precedes_slack_and_snapshot(self):
        self.assertEqual(self.run_monitor(), ['history','slack','snapshot'])

    def test_history_failure_preserves_retry(self):
        events=self.run_monitor(fail_history=True)
        self.assertNotIn('snapshot',events)

    def test_slack_failure_preserves_retry(self):
        events=self.run_monitor(fail_slack=True)
        self.assertEqual(events[0],'history')
        self.assertNotIn('snapshot',events)


if __name__ == '__main__': unittest.main()
