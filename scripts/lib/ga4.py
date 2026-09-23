"""Read actual GA4 landing-page referrals using the existing Google credentials."""
from __future__ import annotations
from datetime import datetime
from urllib.parse import urlsplit
from . import gsc, http_util


def export(cfg, start, end, *, max_rows=100000):
    property_id = cfg.require('GA4_PROPERTY_ID', 'Set the numeric GA4 property ID and grant the service account Viewer access.')
    if not property_id.isdigit():
        raise ValueError('GA4_PROPERTY_ID must be numeric')
    credentials = gsc._credentials(cfg).with_scopes(['https://www.googleapis.com/auth/analytics.readonly'])
    from google.auth.transport.requests import Request
    credentials.refresh(Request())
    host = urlsplit(cfg.site_url).hostname
    dimensions = ['date', 'landingPagePlusQueryString', 'sessionSource', 'sessionMedium']
    rows, metadata, expected = [], {}, None
    limited, sampled, stable, row_count = False, False, True, None
    while len(rows) < max_rows:
        request = {'dateRanges': [{'startDate': start, 'endDate': end}],
                   'dimensions': [{'name': d} for d in dimensions],
                   'metrics': [{'name': 'sessions'}, {'name': 'keyEvents'}],
                   'dimensionFilter': {'filter': {'fieldName': 'hostName', 'stringFilter': {'matchType': 'EXACT', 'value': host}}},
                   'orderBys': [{'dimension': {'dimensionName': d}} for d in dimensions],
                   'offset': str(len(rows)), 'limit': str(min(10000, max_rows-len(rows)))}
        resp = http_util.request('POST', f'https://analyticsdata.googleapis.com/v1beta/properties/{property_id}:runReport',
                                 headers={'Authorization': 'Bearer ' + credentials.token}, json_body=request, retry='idempotent')
        http_util.raise_for_status(resp)
        payload = resp.json()
        expected = int(payload.get('rowCount', 0))
        page_metadata=payload.get('metadata') or {}
        limited=limited or bool(page_metadata.get('subjectToThresholding') or page_metadata.get('dataLossFromOtherRow'))
        sampled=sampled or bool(page_metadata.get('samplingMetadatas'))
        if row_count is not None and row_count!=expected: stable=False
        row_count=expected
        if metadata.get('timeZone') and page_metadata.get('timeZone') and metadata['timeZone']!=page_metadata['timeZone']: stable=False
        metadata.update(page_metadata)
        batch = payload.get('rows') or []
        for row in batch:
            d = [v.get('value', '') for v in row['dimensionValues']]
            m = [float(v['value']) for v in row['metricValues']]
            rows.append({'date': datetime.strptime(d[0], '%Y%m%d').date().isoformat(), 'page': d[1],
                         'source': d[2], 'medium': d[3], 'sessions': m[0], 'key_events': m[1]})
        if len(rows) >= expected or not batch:
            break
    data = {'property': 'ga4:' + property_id, 'timezone': metadata.get('timeZone', ''),
            'exporter': 'ga4-data-api-v1beta', 'site_url': cfg.site_url, 'start': start, 'end': end,
            'filters': {'hostName': host}, 'complete': stable and len(rows) == expected,
            'sampled': sampled, 'thresholded': limited,
            'synthetic': False, 'rows': rows, 'metadata': metadata}
    if any(not r['page'].startswith('/') for r in rows):
        data['complete'] = False
        data['coverage_note'] = 'Some sessions have no attributable landing page.'
    return data
