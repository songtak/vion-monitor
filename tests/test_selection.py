import unittest

from vion_monitor.selection import select_products


class SelectionTests(unittest.TestCase):
    def test_selects_requested_count_with_distinct_brands(self):
        products = [
            {'id': str(i), 'brand': f'brand-{i}', 'url': f'https://example.com/{i}'}
            for i in range(35)
        ]
        selected = select_products(products, limit=30, distinct_brands=True)
        self.assertEqual(len(selected), 30)
        self.assertEqual(len({p['brand'] for p in selected}), 30)

    def test_skips_products_without_url(self):
        products = [
            {'id': '1', 'brand': 'a', 'url': ''},
            {'id': '2', 'brand': 'b', 'url': 'https://example.com/2'},
        ]
        self.assertEqual([p['id'] for p in select_products(products)], ['2'])

    def test_fills_remaining_slots_if_brands_repeat(self):
        products = [
            {'id': '1', 'brand': 'a', 'url': 'https://example.com/1'},
            {'id': '2', 'brand': 'a', 'url': 'https://example.com/2'},
            {'id': '3', 'brand': 'b', 'url': 'https://example.com/3'},
        ]
        selected = select_products(products, limit=3, distinct_brands=True)
        self.assertEqual({p['id'] for p in selected}, {'1', '2', '3'})


if __name__ == '__main__':
    unittest.main()
