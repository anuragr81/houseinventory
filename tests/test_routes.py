"""
tests/test_routes.py
---------------------
HTTP-level tests via Flask test client.
Uses 'db' fixture directly for setup — no app_context() wrappers needed.
"""

import pytest
from tests.conftest import get_box_id, get_category_id, get_location_id
from inventory import models


class TestSearchRoute:

    def test_search_returns_200(self, client):
        resp = client.get('/inventory/api/search?q=chickpeas')
        assert resp.status_code == 200

    def test_search_returns_matching_box(self, client):
        data = client.get('/inventory/api/search?q=chickpeas').get_json()
        assert len(data) == 1
        assert data[0]['label'] == 'Chickpeas & Pulses'

    def test_search_returns_location_path(self, client):
        data = client.get('/inventory/api/search?q=chickpeas').get_json()
        assert 'Kitchen' in data[0]['location']
        assert 'Cupboard Top Right' in data[0]['location']

    def test_search_returns_categories(self, client):
        data = client.get('/inventory/api/search?q=chickpeas').get_json()
        cats = [c['category'] for c in data[0]['categories']]
        assert 'Dry food items' in cats

    def test_search_empty_query_returns_empty_list(self, client):
        assert client.get('/inventory/api/search?q=').get_json() == []

    def test_search_no_match_returns_empty_list(self, client):
        assert client.get('/inventory/api/search?q=zzznomatch').get_json() == []

    def test_search_matches_notes(self, client):
        data = client.get('/inventory/api/search?q=3 tins').get_json()
        assert any(b['label'] == 'Chickpeas & Pulses' for b in data)

    def test_search_matches_category_name(self, client):
        data   = client.get('/inventory/api/search?q=dry food').get_json()
        labels = [b['label'] for b in data]
        assert 'Chickpeas & Pulses' in labels
        assert 'Pasta & Rice' in labels


class TestLocationsRoute:

    def test_locations_returns_200(self, client):
        assert client.get('/inventory/api/locations').status_code == 200

    def test_locations_contains_rooms(self, client):
        data  = client.get('/inventory/api/locations').get_json()
        names = [r['name'] for r in data]
        assert 'Kitchen' in names

    def test_rooms_have_furniture(self, client):
        data    = client.get('/inventory/api/locations').get_json()
        kitchen = next(r for r in data if r['name'] == 'Kitchen')
        assert len(kitchen['furniture']) > 0

    def test_furniture_has_shelves(self, client):
        data    = client.get('/inventory/api/locations').get_json()
        kitchen = next(r for r in data if r['name'] == 'Kitchen')
        c2      = next(f for f in kitchen['furniture'] if f['name'] == 'Cupboard Top Right')
        assert len(c2['shelves']) > 0


class TestCategoriesRoute:

    def test_categories_returns_200(self, client):
        assert client.get('/inventory/api/categories').status_code == 200

    def test_flat_super_cat_structure(self, client):
        data = client.get('/inventory/api/categories').get_json()
        food = next(sc for sc in data if sc['name'] == 'Food')
        assert food['flat'] is True
        assert any(c['name'] == 'Dry food items' for c in food['categories'])

    def test_threelevel_super_cat_structure(self, client):
        data  = client.get('/inventory/api/categories').get_json()
        tools = next(sc for sc in data if sc['name'] == 'Tools')
        assert tools['flat'] is False
        assert 'mid_categories' in tools

    def test_tools_has_repair_fixing(self, client):
        data  = client.get('/inventory/api/categories').get_json()
        tools = next(sc for sc in data if sc['name'] == 'Tools')
        mid   = [mc['name'] for mc in tools['mid_categories']]
        assert 'Repair & fixing' in mid


class TestLocationBoxesRoute:

    def test_returns_boxes_at_location(self, client, db):
        loc_id = get_location_id(db, 'KIT-C2-S2')
        data   = client.get(f'/inventory/api/location/{loc_id}/boxes').get_json()
        assert any(b['label'] == 'Chickpeas & Pulses' for b in data)

    def test_returns_empty_for_empty_location(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S2')
        resp   = client.get(f'/inventory/api/location/{loc_id}/boxes')
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_returns_404_for_nonexistent_location(self, client):
        assert client.get('/inventory/api/location/99999/boxes').status_code == 404


class TestCategoryBoxesRoute:

    def test_returns_boxes_for_category(self, client, db):
        cat_id = get_category_id(db, 'Dry food items')
        data   = client.get(f'/inventory/api/category/{cat_id}/boxes').get_json()
        labels = [b['label'] for b in data]
        assert 'Chickpeas & Pulses' in labels
        assert 'Pasta & Rice' in labels

    def test_returns_404_for_nonexistent_category(self, client):
        assert client.get('/inventory/api/category/99999/boxes').status_code == 404


class TestSaveBoxRoute:

    def test_create_new_box_returns_201(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S2')
        resp   = client.post('/inventory/api/box', json={
            'label': 'New spices box', 'location_id': loc_id,
            'notes': 'cumin', 'updated_by': 'Anurag',
        })
        assert resp.status_code == 201
        assert resp.get_json()['action'] == 'created'

    def test_update_existing_box_returns_200(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S3')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Chickpeas & Pulses', 'location_id': loc_id,
            'notes': '', 'updated_by': 'Spouse',
        })
        assert resp.status_code == 200
        assert resp.get_json()['action'] == 'updated'

    def test_missing_label_returns_400(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': '', 'location_id': loc_id, 'updated_by': 'Anurag',
        })
        assert resp.status_code == 400

    def test_missing_location_returns_400(self, client):
        resp = client.post('/inventory/api/box', json={
            'label': 'Test box', 'updated_by': 'Anurag',
        })
        assert resp.status_code == 400

    def test_missing_updated_by_returns_400(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Test box', 'location_id': loc_id,
        })
        assert resp.status_code == 400

    def test_invalid_location_id_returns_400(self, client):
        resp = client.post('/inventory/api/box', json={
            'label': 'Test box', 'location_id': 99999, 'updated_by': 'Anurag',
        })
        assert resp.status_code == 400


class TestDeleteBoxRoute:

    def test_delete_returns_200(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        resp   = client.delete(f'/inventory/api/box/{box_id}',
                               json={'deleted_by': 'Anurag'})
        assert resp.status_code == 200
        assert resp.get_json()['action'] == 'deleted'

    def test_deleted_box_not_searchable(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        client.delete(f'/inventory/api/box/{box_id}', json={'deleted_by': 'Anurag'})
        assert client.get('/inventory/api/search?q=stationery').get_json() == []

    def test_delete_nonexistent_returns_404(self, client):
        assert client.delete('/inventory/api/box/99999',
                             json={'deleted_by': 'test'}).status_code == 404


class TestAddBoxItemRoute:

    def test_add_item_returns_201(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Electronics')
        resp   = client.post(f'/inventory/api/box/{box_id}/item',
                             json={'category_id': cat_id, 'added_by': 'Anurag'})
        assert resp.status_code == 201

    def test_duplicate_category_returns_409(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        resp   = client.post(f'/inventory/api/box/{box_id}/item',
                             json={'category_id': cat_id, 'added_by': 'Anurag'})
        assert resp.status_code == 409

    def test_missing_category_id_returns_400(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        resp   = client.post(f'/inventory/api/box/{box_id}/item',
                             json={'added_by': 'Anurag'})
        assert resp.status_code == 400

    def test_missing_added_by_returns_400(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Electronics')
        resp   = client.post(f'/inventory/api/box/{box_id}/item',
                             json={'category_id': cat_id})
        assert resp.status_code == 400

    def test_nonexistent_box_returns_404(self, client, db):
        cat_id = get_category_id(db, 'Stationery')
        resp   = client.post('/inventory/api/box/99999/item',
                             json={'category_id': cat_id, 'added_by': 'Anurag'})
        assert resp.status_code == 404


class TestRemoveBoxItemRoute:

    def _item_id(self, db, box_label, cat_name):
        box_id = get_box_id(db, box_label)
        cat_id = get_category_id(db, cat_name)
        row = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        return box_id, row['id'] if row else None

    def test_remove_returns_200(self, client, db):
        box_id, item_id = self._item_id(db, 'Stationery', 'Stationery')
        resp = client.delete(f'/inventory/api/box/{box_id}/item/{item_id}',
                             json={'removed_by': 'Anurag', 'reason': 'consumed'})
        assert resp.status_code == 200

    def test_removed_item_not_in_categories(self, client, db):
        box_id, item_id = self._item_id(db, 'Stationery', 'Stationery')
        client.delete(f'/inventory/api/box/{box_id}/item/{item_id}',
                      json={'removed_by': 'Anurag', 'reason': 'consumed'})
        box  = client.get(f'/inventory/api/box/{box_id}').get_json()
        cats = [c['category'] for c in box['categories']]
        assert 'Stationery' not in cats

    def test_remove_nonexistent_item_returns_404(self, client, db):
        box_id = get_box_id(db, 'Stationery')
        resp   = client.delete(f'/inventory/api/box/{box_id}/item/99999',
                               json={'removed_by': 'test', 'reason': 'consumed'})
        assert resp.status_code == 404


class TestAutocompleteRoute:

    def test_returns_matches(self, client):
        data = client.get('/inventory/api/autocomplete?q=chick').get_json()
        assert any(b['label'] == 'Chickpeas & Pulses' for b in data)

    def test_includes_location(self, client):
        data = client.get('/inventory/api/autocomplete?q=chick').get_json()
        box  = next(b for b in data if b['label'] == 'Chickpeas & Pulses')
        assert 'Kitchen' in box['location']

    def test_empty_query_returns_empty(self, client):
        assert client.get('/inventory/api/autocomplete?q=').get_json() == []

    def test_no_match_returns_empty(self, client):
        assert client.get('/inventory/api/autocomplete?q=zzznomatch').get_json() == []
