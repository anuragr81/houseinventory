"""
tests/test_coordinates.py
--------------------------
Tests for the (wall, i, j) coordinate system.
Uses 'db' fixture directly — no app_context() wrappers needed.
"""

import pytest
from inventory import models
from tests.conftest import get_box_id, get_category_id, get_location_id


class TestCoordDict:

    def _row(self, wall, i, j):
        return {'wall': wall, 'i': i, 'j': j}

    def test_all_none_returns_null_label(self):
        r = models.coord_dict(self._row(None, None, None))
        assert r['wall'] is None and r['label'] is None

    def test_partial_coord_returns_null_label(self):
        assert models.coord_dict(self._row(1, None, None))['label'] is None

    def test_full_coord_top_left(self):
        assert models.coord_dict(self._row(1, 1, 1))['label'] == 'W1 · top row · left column'

    def test_full_coord_middle_centre(self):
        assert models.coord_dict(self._row(2, 2, 2))['label'] == 'W2 · middle row · centre column'

    def test_full_coord_bottom_right(self):
        assert models.coord_dict(self._row(3, 3, 3))['label'] == 'W3 · bottom row · right column'

    def test_wall_4(self):
        assert models.coord_dict(self._row(4, 1, 3))['label'] == 'W4 · top row · right column'

    def test_values_preserved(self):
        r = models.coord_dict(self._row(2, 3, 1))
        assert r['wall'] == 2 and r['i'] == 3 and r['j'] == 1


class TestBoxCoordinates:

    def test_save_box_with_coordinate(self, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        action, box = models.save_box(
            db, 'Spices box', loc_id, '', 'Anurag', wall=1, i=2, j=3
        )
        assert action == 'created'
        assert box['coord']['wall']  == 1
        assert box['coord']['i']     == 2
        assert box['coord']['j']     == 3
        assert box['coord']['label'] == 'W1 · middle row · right column'

    def test_save_box_without_coordinate(self, db):
        loc_id = get_location_id(db, 'KIT-C1-S2')
        _, box = models.save_box(db, 'No coord box', loc_id, '', 'Anurag')
        assert box['coord']['wall']  is None
        assert box['coord']['label'] is None

    def test_update_box_adds_coordinate(self, db):
        loc_id = get_location_id(db, 'KIT-C2-S2')
        models.save_box(db, 'Chickpeas & Pulses', loc_id, '', 'Anurag')
        action, box = models.save_box(
            db, 'Chickpeas & Pulses', loc_id, '', 'Anurag', wall=1, i=1, j=2
        )
        assert action == 'updated'
        assert box['coord']['wall'] == 1
        assert box['coord']['i']    == 1

    def test_coordinate_persists_after_retrieval(self, db):
        loc_id = get_location_id(db, 'STU-BS1-S1')
        _, created = models.save_box(
            db, 'Coord test box', loc_id, '', 'Anurag', wall=2, i=3, j=1
        )
        fetched = models.get_box_by_id(db, created['id'])
        assert fetched['coord']['wall'] == 2
        assert fetched['coord']['i']    == 3
        assert fetched['coord']['j']    == 1

    def test_coordinate_in_search_results(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        models.save_box(db, 'Tagged spices', loc_id, '', 'Anurag', wall=1, i=2, j=2)
        data = client.get('/inventory/api/search?q=tagged spices').get_json()
        assert data[0]['coord']['label'] == 'W1 · middle row · centre column'


class TestBoxItemCoordinates:

    def test_add_item_with_coordinate(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Electronics')
        success, msg, item_id = models.add_box_item(
            db, box_id, cat_id, 'Anurag', wall=1, i=1, j=3
        )
        assert success is True
        row = db.execute(
            "SELECT wall, i, j FROM box_item WHERE id = ?", (item_id,)
        ).fetchone()
        assert row['wall'] == 1 and row['i'] == 1 and row['j'] == 3

    def test_add_item_without_coordinate(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Electronics')
        success, msg, item_id = models.add_box_item(db, box_id, cat_id, 'Anurag')
        assert success is True
        row = db.execute(
            "SELECT wall, i, j FROM box_item WHERE id = ?", (item_id,)
        ).fetchone()
        assert row['wall'] is None and row['i'] is None

    def test_item_coordinate_in_box_categories(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Electronics')
        models.add_box_item(db, box_id, cat_id, 'Anurag', wall=1, i=2, j=1)
        box    = models.get_box_by_id(db, box_id)
        elec   = next(c for c in box['categories'] if c['category'] == 'Electronics')
        assert elec['coord']['label'] == 'W1 · middle row · left column'

    def test_reinstate_item_updates_coordinate(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        models.remove_box_item(db, box_id, item['id'], 'test', 'consumed')
        success, msg, new_id = models.add_box_item(
            db, box_id, cat_id, 'Anurag', wall=2, i=3, j=2
        )
        assert success is True
        row = db.execute(
            "SELECT wall, i, j FROM box_item WHERE id = ?", (new_id,)
        ).fetchone()
        assert row['wall'] == 2 and row['i'] == 3 and row['j'] == 2


class TestCoordinateRouteValidation:

    def test_valid_coordinate_accepted(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Coord route test', 'location_id': loc_id,
            'updated_by': 'Anurag', 'wall': 1, 'i': 2, 'j': 3,
        })
        assert resp.status_code == 201
        assert resp.get_json()['box']['coord']['wall'] == 1

    def test_wall_out_of_range_rejected(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Bad wall', 'location_id': loc_id,
            'updated_by': 'Anurag', 'wall': 5,
        })
        assert resp.status_code == 400

    def test_i_out_of_range_rejected(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Bad i', 'location_id': loc_id,
            'updated_by': 'Anurag', 'wall': 1, 'i': 4,
        })
        assert resp.status_code == 400

    def test_j_zero_rejected(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Bad j', 'location_id': loc_id,
            'updated_by': 'Anurag', 'wall': 1, 'i': 1, 'j': 0,
        })
        assert resp.status_code == 400

    def test_null_coordinate_accepted(self, client, db):
        loc_id = get_location_id(db, 'KIT-C1-S2')
        resp   = client.post('/inventory/api/box', json={
            'label': 'Null coord', 'location_id': loc_id, 'updated_by': 'Anurag',
        })
        assert resp.status_code == 201
        assert resp.get_json()['box']['coord']['label'] is None

    def test_coordinate_returned_in_search(self, client, db):
        loc_id = get_location_id(db, 'GAR-SH-S1')
        client.post('/inventory/api/box', json={
            'label': 'Drill bits', 'location_id': loc_id,
            'updated_by': 'Anurag', 'wall': 1, 'i': 3, 'j': 2,
        })
        data = client.get('/inventory/api/search?q=drill bits').get_json()
        assert data[0]['coord']['label'] == 'W1 · bottom row · centre column'
