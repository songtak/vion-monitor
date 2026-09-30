import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials

BASE = 'https://sheets.googleapis.com/v4/spreadsheets'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


class SheetStore:
    def __init__(self):
        raw = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        spreadsheet_id = os.environ.get('GOOGLE_SPREADSHEET_ID')
        if not raw or not spreadsheet_id:
            raise RuntimeError('GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_SPREADSHEET_ID 설정 필요')
        creds = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        self.http = AuthorizedSession(creds)
        self.id = spreadsheet_id
        self.root = f'{BASE}/{self.id}'

    def request(self, method, path, **kwargs):
        res = self.http.request(method, self.root + path, timeout=45, **kwargs)
        res.raise_for_status()
        return res.json() if res.content else {}

    def values(self, tab):
        name = quote(f"'{tab}'!A:Q", safe='')
        return self.request('GET', f'/values/{name}').get('values', [])

    def ensure_tabs(self, names):
        existing = {s['properties']['title'] for s in self.request('GET', '').get('sheets', [])}
        requests = [{'addSheet': {'properties': {'title': name}}} for name in names if name not in existing]
        if requests: self.request('POST', ':batchUpdate', json={'requests': requests})

    def append(self, tab, rows):
        if not rows: return
        name = quote(f"'{tab}'!A1", safe='')
        self.request('POST', f'/values/{name}:append',
                     params={'valueInputOption': 'RAW', 'insertDataOption': 'INSERT_ROWS'},
                     json={'values': rows})

    def replace_row(self, tab, row_number, values):
        name = quote(f"'{tab}'!A{row_number}", safe='')
        self.request('PUT', f'/values/{name}', params={'valueInputOption': 'RAW'},
                     json={'values': [values]})

    def products(self, name):
        rows = self.values(name)
        if not rows: raise RuntimeError(f'{name} 시트가 비어 있음')
        # Header can be below a title row.
        index = next((n for n,r in enumerate(rows) if '제품 ID' in r and '공식 상품 상세' in r), None)
        if index is None: raise RuntimeError('제품 ID / 공식 상품 상세 헤더를 찾지 못함')
        headers = [v.strip() for v in rows[index]]
        required = ('제품 ID', '제품명', '브랜드명', '가격(원)', '용량', '전성분', '공식 상품 상세')
        missing = [key for key in required if key not in headers]
        if missing: raise RuntimeError('필수 헤더 누락: ' + ', '.join(missing))
        def get(row, key):
            j = headers.index(key)
            return row[j].strip() if j < len(row) else ''
        result = []
        for row in rows[index + 1:]:
            if not row or not get(row, '제품 ID'): continue
            result.append({'id': get(row,'제품 ID'), 'name': get(row,'제품명'),
                           'brand': get(row,'브랜드명'), 'volume': get(row,'용량'),
                           'price': get(row,'가격(원)'), 'ingredients': get(row,'전성분'),
                           'url': get(row,'공식 상품 상세')})
        ids = [x['id'] for x in result]
        if len(ids) != len(set(ids)): raise RuntimeError('제품 ID 중복')
        return result

    def previous(self):
        rows = self.values('수집상태')
        result = {}
        for n, row in enumerate(rows[1:], 2):
            if len(row) >= 2 and row[0]:
                try: result[row[0]] = (n, json.loads(row[1]))
                except json.JSONDecodeError: raise RuntimeError(f'수집상태 {n}행 JSON 오류')
        return result

    def save_snapshot(self, product_id, data, previous):
        stamp = datetime.now(timezone.utc).isoformat()
        row = [product_id, json.dumps(data, ensure_ascii=False), stamp]
        if product_id in previous:
            self.replace_row('수집상태', previous[product_id][0], row)
            previous[product_id] = (previous[product_id][0], data)
        else:
            # Account for blank rows in a sheet edited by a person.
            number = len(self.values('수집상태')) + 1
            self.replace_row('수집상태', number, row)
            previous[product_id] = (number, data)

    def last_run(self):
        for row in self.values('실행설정')[1:]:
            if row and row[0] == 'last_run_utc' and len(row) > 1:
                return datetime.fromisoformat(row[1])
        return None

    def mark_run(self):
        rows = self.values('실행설정')
        for i, row in enumerate(rows, 1):
            if row and row[0] == 'last_run_utc':
                self.replace_row('실행설정', i, ['last_run_utc', datetime.now(timezone.utc).isoformat()])
                return
        self.append('실행설정', [['last_run_utc', datetime.now(timezone.utc).isoformat()]])
