"""Read-only web medicine catalog. Independent of the AI catalog and E5 model."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TABLE = "drug_documents_v2"


class MedicineDatabaseUnavailable(Exception):
    pass


def database_settings() -> dict:
    # Read settings without mutating the AI process's environment.
    settings = {**dotenv_values(ROOT / '.env'),
                **dotenv_values(ROOT / 'config' / '.env'), **os.environ}
    if any(not settings.get(key) for key in ('PG_HOST', 'PG_USER', 'PG_PASSWORD')):
        raise MedicineDatabaseUnavailable('Missing database configuration')
    try:
        dsn = dict(host=settings['PG_HOST'], port=int(settings.get('PG_PORT') or 5433),
                   dbname=settings.get('VECTOR_DB') or 'drug_rag', user=settings['PG_USER'],
                   password=settings['PG_PASSWORD'],
                   connect_timeout=int(settings.get('PG_CONNECT_TIMEOUT') or 8),
                   options='-c statement_timeout=10000 -c default_transaction_read_only=on')
    except (ValueError, TypeError) as exc:
        raise MedicineDatabaseUnavailable('Invalid database configuration') from exc
    if settings.get('PGSSLMODE'):
        dsn['sslmode'] = settings['PGSSLMODE']
    if settings.get('PGSSLROOTCERT'):
        dsn['sslrootcert'] = settings['PGSSLROOTCERT']
    return dsn


@contextmanager
def medicine_repository():
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        connection = psycopg2.connect(**database_settings())
    except MedicineDatabaseUnavailable:
        raise
    except Exception as exc:
        raise MedicineDatabaseUnavailable(type(exc).__name__) from exc
    try:
        connection.autocommit = True
        yield MedicineRepository(connection, RealDictCursor)
    except psycopg2.Error as exc:
        # Do not turn HTTP 404 or request validation into a database failure.
        raise MedicineDatabaseUnavailable(type(exc).__name__) from exc
    finally:
        connection.close()


def product_summary(row: dict) -> dict:
    metadata = row.get('metadata') or {}
    return {
        'drug_id': row['item_seq'], 'name_ko': row.get('name') or row['item_seq'],
        'name_en': metadata.get('name_eng'),
        'company': row.get('manufacturer') or metadata.get('manufacturer'),
        'ingredient': metadata.get('main_ingr_raw') or '',
        'category': metadata.get('etc_otc'),
        'is_otc': row.get('is_otc'), 'is_active': row.get('is_active'),
        'data_version': row.get('data_version'),
    }


class MedicineRepository:
    def __init__(self, connection, cursor_factory=None):
        self.connection = connection
        self.cursor_factory = cursor_factory

    def _rows(self, sql, params):
        with self.connection.cursor(cursor_factory=self.cursor_factory) as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def search(self, query: str, limit: int, offset: int) -> dict:
        # Escape LIKE metacharacters: searches are literal and parameters are bound.
        escaped = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        pattern = f'%{escaped}%'
        rows = self._rows(f"""
            SELECT * FROM (
                SELECT DISTINCT ON (item_seq)
                    item_seq, name, manufacturer, metadata, is_otc, is_active, data_version
                FROM {TABLE}
                WHERE doc_type = 'drug_permit' AND section = 'summary'
                  AND is_active IS TRUE AND NULLIF(item_seq, '') IS NOT NULL
                  AND (%s = '' OR name ILIKE %s
                       OR metadata->>'main_ingr_raw' ILIKE %s OR item_seq = %s)
                ORDER BY item_seq, chunk_index, doc_id
            ) products
            ORDER BY name, item_seq LIMIT %s OFFSET %s
        """, (query, pattern, pattern, query, limit + 1, offset))
        return {'items': [product_summary(row) for row in rows[:limit]],
                'next_offset': offset + limit if len(rows) > limit else None,
                'data_sources': ['postgresql']}

    def detail(self, item_seq: str) -> dict | None:
        rows = self._rows(f"""
            SELECT doc_id, doc_type, section, chunk_index, item_seq, name, text,
                   manufacturer, metadata, is_otc, is_active, data_version,
                   source_name, source_url, item_url
            FROM {TABLE}
            WHERE item_seq = %s AND doc_type = ANY(%s)
            ORDER BY doc_type, section, source_name, chunk_index, doc_id
        """, (item_seq, ['drug_permit', 'drug_efficacy', 'drug_usage',
                        'drug_caution', 'drug_side_effect']))
        if not rows:
            return None
        base = next((r for r in rows if r['doc_type'] == 'drug_permit'
                     and r['section'] == 'summary'), rows[0])
        result = product_summary(base)
        # Keep documents from different sources separate; do not invent missing sections.
        documents = {}
        source_list = []
        for row in rows:
            section = row.get('section')
            if row['doc_type'] == 'drug_permit':
                section = {'summary': 'permit_summary', 'caution': 'permit_caution'}.get(section)
            else:
                section = {'drug_efficacy': 'efficacy', 'drug_usage': 'usage',
                           'drug_caution': 'caution', 'drug_side_effect': 'side_effect'}[row['doc_type']]
            source = {'name': row.get('source_name'), 'url': row.get('source_url'),
                      'item_url': row.get('item_url')}
            if source not in source_list:
                source_list.append(source)
            if not section or not row.get('text'):
                continue
            key = (section, row.get('source_name'), row.get('source_url'), row.get('item_url'))
            entry = documents.setdefault(key, {'section': section, 'source': source, 'chunks': []})
            entry['chunks'].append(row['text'])
        result['documents'] = [{'section': d['section'], 'source': d['source'],
                                'text': '\n\n'.join(d['chunks'])} for d in documents.values()]
        result['sources'] = source_list
        result['data_sources'] = ['postgresql']
        result['missing_sections'] = [s for s in ('efficacy', 'usage', 'caution', 'side_effect')
                                      if not any(d['section'] == s for d in result['documents'])]
        result['interaction_status'] = 'not_assessed'
        return result
