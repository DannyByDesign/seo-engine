import copy
import pytest
from scripts.lib import traffic


def fixture(start, end, sessions):
    return {'property': 'fixture', 'timezone': 'UTC', 'site_url': 'https://fixture.test',
            'exporter': 'synthetic-unit-fixture', 'complete': True, 'synthetic': True,
            'start': start, 'end': end, 'rows': [
                {'date': start, 'page': '/guide', 'source': 'google', 'medium': 'organic', 'sessions': sessions, 'key_events': 1},
                {'date': start, 'page': '/guide', 'source': 'chatgpt.com', 'medium': 'referral', 'sessions': 1, 'key_events': 0}]}


def test_channels_and_honest_comparison():
    assert traffic.channel('chatgpt.com.evil.test', 'referral') == 'other'
    assert traffic.channel('chatgpt.com', 'cpc') == 'other'
    assert traffic.channel('google', 'cpc') == 'other'
    a, b = fixture('2026-01-05','2026-02-01',100), fixture('2026-02-09','2026-03-08',150)
    result = traffic.compare(a,b,['/guide'],'2026-02-04')
    assert result['channels']['google_organic']['session_delta'] == 50
    assert result['channels']['google_organic']['causal_lift'] is None
    assert result['channels']['chatgpt_referral']['decision'] == 'insufficient_sample'
    assert result['synthetic'] is True


@pytest.mark.parametrize('change', [{'complete': False}, {'sampled': True}, {'thresholded': True}, {'synthetic': None}, {'end': '2099-01-01'}])
def test_reject_unknown_or_incomplete_exports(change):
    data = fixture('2026-01-05','2026-02-01',100); data.update(change)
    with pytest.raises(ValueError): traffic.validate(data)


def test_comparison_rejects_different_properties_windows_and_duplicates():
    a, b = fixture('2026-01-05','2026-02-01',100), fixture('2026-02-09','2026-03-08',150)
    for patch in ({'property': 'different'}, {'filters': {'country': 'US'}}, {'start': '2026-02-10'}):
        changed = {**b, **patch}
        with pytest.raises(ValueError): traffic.compare(a,changed,['/guide'],'2026-02-04')
    a['rows'].append(copy.deepcopy(a['rows'][0]))
    with pytest.raises(ValueError): traffic.validate(a)


def test_ga4_export_retains_coverage_and_actual_source(monkeypatch, tmp_path, fake_transport):
    import json
    from scripts.lib import ga4
    from scripts.lib.config import Config
    class Credentials:
        token = 'unit-token'
        def with_scopes(self, scopes):
            assert scopes == ['https://www.googleapis.com/auth/analytics.readonly']
            return self
        def refresh(self, request): pass
    monkeypatch.setattr(ga4.gsc, '_credentials', lambda cfg: Credentials())
    payload = {'rowCount': 2, 'metadata': {'timeZone': 'America/Los_Angeles'}, 'rows': [
        {'dimensionValues': [{'value': v} for v in ['20260105','/guide','chatgpt.com','referral']],
         'metricValues': [{'value': '2'}, {'value': '1'}]}]}
    fake_transport.route('POST', 'https://analyticsdata.googleapis.com/v1beta/properties/123:runReport', {'body': json.dumps(payload)})
    cfg = Config(repo_root=tmp_path, env={'GA4_PROPERTY_ID': '123'}, site={'site_url': 'https://testsite.test'})
    result = ga4.export(cfg, '2026-01-05', '2026-02-01', max_rows=1)
    assert result['complete'] is False and result['synthetic'] is False
    assert result['rows'][0]['source'] == 'chatgpt.com'
    with pytest.raises(ValueError): traffic.validate(result)


def test_ga4_pagination_preserves_any_page_threshold_warning(monkeypatch,tmp_path,fake_transport):
    import json
    from scripts.lib import ga4
    from scripts.lib.config import Config
    class Credentials:
        token='unit-token'
        def with_scopes(self,scopes): return self
        def refresh(self,request): pass
    monkeypatch.setattr(ga4.gsc,'_credentials',lambda cfg:Credentials())
    def page(day,limited):
        return {'body':json.dumps({'rowCount':2,'metadata':{'timeZone':'UTC','subjectToThresholding':limited},'rows':[
            {'dimensionValues':[{'value':v} for v in [day,'/guide','google','organic']], 'metricValues':[{'value':'2'},{'value':'0'}]}]})}
    fake_transport.route('POST','https://analyticsdata.googleapis.com/v1beta/properties/123:runReport',page('20260105',True),page('20260106',False))
    cfg=Config(repo_root=tmp_path,env={'GA4_PROPERTY_ID':'123'},site={'site_url':'https://fixture.test'})
    result=ga4.export(cfg,'2026-01-05','2026-02-01')
    assert result['complete'] and result['thresholded'] and len(result['rows'])==2
    with pytest.raises(ValueError): traffic.validate(result)
