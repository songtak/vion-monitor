import unittest
import csv
import yaml

from vion_monitor.__main__ import diff
from vion_monitor.extract import FIELDS, extract, ingredients, site_for, volume


class ExtractTests(unittest.TestCase):
    def test_jsonld_prices_and_ingredients(self):
        html = '''<html><h1>아토베리어365 크림 80ml</h1>
        <script type="application/ld+json">{"@graph":[{"@type":"ProductGroup","name":"아토베리어365 크림","additionalProperty":[{"name":"성분","value":"정제수, 글리세린, 판테놀, 세라마이드엔피, 알란토인"}],"offers":{"price":28050,"priceSpecification":{"price":33000,"priceType":"https://schema.org/StrikethroughPrice"}}}]}</script></html>'''
        config = {'engine':'custom','name':['h1']}
        value, warnings = extract(html, 'https://www.amoremall.com/product', config, '아토베리어365 크림', '80')
        self.assertEqual(value['price'], 33000)
        self.assertEqual(value['volume'], '80ml')
        self.assertEqual(value['ingredients'][2], '판테놀')
        self.assertFalse(warnings)

    def test_failed_field_never_looks_like_change(self):
        old = {'name':'토너', 'ingredients':['정제수','판테놀'], 'price':20000}
        new = {'name':'토너', 'ingredients':None, 'price':None}
        self.assertEqual(diff(old,new), [])

    def test_ingredient_order_is_distinct_change(self):
        old = {'ingredients':['정제수','판테놀']}
        new = {'ingredients':['판테놀','정제수']}
        self.assertIn('순서 변경', diff(old,new)[0][1])

    def test_mismatched_product_rejected(self):
        value,warnings = extract('<h1>레드 립스틱 3g</h1>', 'https://example.com/a', {'engine':'custom'}, '아토베리어 크림', '80')
        self.assertTrue(all(value[f] is None for f in FIELDS))
        self.assertTrue(any('제품명 불일치' in w for w in warnings))

    def test_missing_ingredients_reports_detail_image_candidates(self):
        html = '''<html><h1>토너 300ml</h1><div id="prdDetail">
        <img data-original="/images/detail-info.jpg"></div></html>'''
        value, warnings = extract(html, 'https://example.com/product/1', {'engine':'custom'}, '토너', '300')
        self.assertEqual(value['_evidence']['image_urls'], ['https://example.com/images/detail-info.jpg'])
        self.assertEqual(value['_evidence']['sources']['ingredients'], '상세 이미지 후보 1개')
        self.assertTrue(any('상세 이미지 1개 확인' in warning for warning in warnings))

    def test_site_specific_ingredient_selector(self):
        html = '''<html><h1>토너 500ml</h1><div class="ingredients_cont">
        <div class="admin_msg">정제수, 글리세린, 판테놀</div></div></html>'''
        value, warnings = extract(html, 'https://example.com/product/1',
                                  {'engine':'custom','ingredients':['.ingredients_cont .admin_msg']},
                                  '토너', '500')
        self.assertEqual(value['ingredients'], ['정제수', '글리세린', '판테놀'])
        self.assertFalse(any('전성분 텍스트 미수집' in warning for warning in warnings))

    def test_config_hosts_are_unique_and_32(self):
        with open('sites.yaml',encoding='utf8') as f: sites = yaml.safe_load(f)['sites']
        self.assertEqual(len(sites),32)
        self.assertEqual(site_for('https://m.torriden.com/goods/goods_view.php?goodsNo=90',sites)[0],'torriden')
        with open('products.csv',encoding='utf8') as f:
            rows = list(csv.DictReader(f))
        registered = [row for row in rows if row['공식 상품 상세']]
        self.assertEqual(len(rows),90)
        self.assertEqual(len(registered),56)
        self.assertTrue(all(site_for(row['공식 상품 상세'],sites)[0] for row in registered))


if __name__ == '__main__': unittest.main()
