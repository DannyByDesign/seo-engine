"""Explicit synthetic operator permissions for offline fixtures."""
from scripts.lib import content


def approved(root, content_id, research=None, items=None):
    data = {
        'topic': 'Synthetic fixture topic', 'reader_intent': 'Exercise an offline content workflow.',
        'demand_evidence': 'Synthetic fixture; not real demand evidence.',
        'competing_pages': [{'url': 'https://fixture.test/guide', 'coverage': 'Synthetic baseline', 'gap': 'Synthetic missing example'}],
        'unresolved': 'The actual implementation is verified by the test.',
        'interview_summary': 'Fixture operator explicitly permits the synthetic test material.',
        'contribution': 'A testable fixture for the existing workflow.',
        'constraints': ['No claims of real customer outcomes.'],
        'mode': 'firsthand' if items else 'external_only', 'items': items or [],
        'research_digest': content.research_digest(research) if research is not None else '',
    }
    record = content.prepare(root, content_id, data)
    return content.confirm(root, content_id, record['digest'], 'Synthetic operator', 'Approved for this offline test only.')


def article_permission(meta, root, slug):
    meta['slug'] = slug
    meta['content_brief'] = approved(root.parents[1], content.publication_id(root, slug), meta['research'])
