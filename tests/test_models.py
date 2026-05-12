"""
tests/test_models.py
---------------------
Tests for model functions called directly — no HTTP involved.
All tests receive 'db' which is the same persistent connection the app uses.
"""

import pytest
from inventory import models
from tests.conftest import get_box_id, get_category_id, get_location_id


class TestLocationPath:

    def test_full_path_three_levels(self, db):
        loc_id = get_location_id(db, 'KIT-C2-S2')
        path   = models.location_path(db, loc_id)
        assert path == 'Kitchen > Cupboard Top Right > Middle shelf'

    def test_room_only_path(self, db):
        loc_id = get_location_id(db, 'KIT')
        path   = models.location_path(db, loc_id)
        assert path == 'Kitchen'

    def test_furniture_path(self, db):
        loc_id = get_location_id(db, 'STU-BS1')
        path   = models.location_path(db, loc_id)
        assert path == 'Study > Bookshelf 1'


class TestLocationHierarchy:

    def test_returns_rooms(self, db):
        hierarchy = models.get_location_hierarchy(db)
        names = [r['name'] for r in hierarchy]
        assert 'Kitchen' in names

    def test_rooms_have_furniture(self, db):
        hierarchy = models.get_location_hierarchy(db)
        kitchen   = next(r for r in hierarchy if r['name'] == 'Kitchen')
        furn_names = [f['name'] for f in kitchen['furniture']]
        assert 'Cupboard Top Left' in furn_names
        assert 'Cupboard Top Right' in furn_names

    def test_furniture_has_shelves(self, db):
        hierarchy = models.get_location_hierarchy(db)
        kitchen   = next(r for r in hierarchy if r['name'] == 'Kitchen')
        c2        = next(f for f in kitchen['furniture'] if f['name'] == 'Cupboard Top Right')
        shelf_names = [s['name'] for s in c2['shelves']]
        assert 'Middle shelf' in shelf_names


class TestCategoryHierarchy:

    def test_flat_super_cat_has_flat_true(self, db):
        hierarchy = models.get_category_hierarchy(db)
        food = next(sc for sc in hierarchy if sc['name'] == 'Food')
        assert food['flat'] is True
        assert 'categories' in food

    def test_threelevel_super_cat_has_flat_false(self, db):
        hierarchy = models.get_category_hierarchy(db)
        tools = next(sc for sc in hierarchy if sc['name'] == 'Tools')
        assert tools['flat'] is False
        assert 'mid_categories' in tools

    def test_tools_mid_categories_present(self, db):
        hierarchy  = models.get_category_hierarchy(db)
        tools      = next(sc for sc in hierarchy if sc['name'] == 'Tools')
        mid_names  = [mc['name'] for mc in tools['mid_categories']]
        assert 'Repair & fixing' in mid_names
        assert 'Power tools' in mid_names

    def test_repair_fixing_has_correct_leaf_cats(self, db):
        hierarchy = models.get_category_hierarchy(db)
        tools     = next(sc for sc in hierarchy if sc['name'] == 'Tools')
        repair    = next(mc for mc in tools['mid_categories'] if mc['name'] == 'Repair & fixing')
        cat_names = [c['name'] for c in repair['categories']]
        assert set(cat_names) == {'Sewing & repairs', 'Adhesives & fixings'}


class TestSearchBoxes:

    def test_search_by_label(self, db):
        results = models.search_boxes(db, 'chickpeas')
        assert len(results) == 1
        assert results[0]['label'] == 'Chickpeas & Pulses'

    def test_search_by_partial_label(self, db):
        results = models.search_boxes(db, 'pasta')
        assert len(results) == 1
        assert results[0]['label'] == 'Pasta & Rice'

    def test_search_by_notes(self, db):
        results = models.search_boxes(db, '3 tins')
        assert len(results) == 1
        assert results[0]['label'] == 'Chickpeas & Pulses'

    def test_search_by_category(self, db):
        results = models.search_boxes(db, 'dry food')
        labels  = [r['label'] for r in results]
        assert 'Chickpeas & Pulses' in labels
        assert 'Pasta & Rice' in labels

    def test_search_case_insensitive(self, db):
        results = models.search_boxes(db, 'CHICKPEAS')
        assert len(results) == 1

    def test_search_no_results(self, db):
        results = models.search_boxes(db, 'zzznomatch')
        assert results == []

    def test_search_excludes_deleted_boxes(self, db):
        box_id = get_box_id(db, 'Chickpeas & Pulses')
        models.delete_box(db, box_id, 'test')
        results = models.search_boxes(db, 'chickpeas')
        assert results == []


class TestSaveBox:

    def test_create_new_box(self, db):
        loc_id = get_location_id(db, 'KIT-C1-S2')
        action, box = models.save_box(db, 'New spices box', loc_id, 'cumin, turmeric', 'Anurag')
        assert action == 'created'
        assert box['label'] == 'New spices box'
        assert box['location'] == 'Kitchen > Cupboard Top Left > Middle shelf'

    def test_update_existing_box_location(self, db):
        new_loc_id = get_location_id(db, 'KIT-C1-S3')
        action, box = models.save_box(db, 'Chickpeas & Pulses', new_loc_id, '', 'Anurag')
        assert action == 'updated'
        assert 'Bottom shelf' in box['location']

    def test_box_to_dict_includes_categories(self, db):
        loc_id = get_location_id(db, 'KIT-C2-S2')
        action, box = models.save_box(db, 'Chickpeas & Pulses', loc_id, '', 'test')
        assert any(c['category'] == 'Dry food items' for c in box['categories'])

    def test_empty_label_creates_box_with_empty_string(self, db):
        loc_id = get_location_id(db, 'KIT-C1-S1')

        action, box = models.save_box(db, "", loc_id, "", "test")
        assert action == "created"  # empty label allowed at model layer; route enforces non-empty


class TestDeleteBox:

    def test_soft_delete_returns_label(self, db):
        box_id = get_box_id(db, 'Stationery')
        label  = models.delete_box(db, box_id, 'Anurag')
        assert label == 'Stationery'

    def test_deleted_box_not_in_search(self, db):
        box_id = get_box_id(db, 'Stationery')
        models.delete_box(db, box_id, 'Anurag')
        results = models.search_boxes(db, 'stationery')
        assert results == []

    def test_deleted_box_not_in_location_list(self, db):
        box_id = get_box_id(db, 'Stationery')
        loc_id = get_location_id(db, 'STU-BS1-S3')
        models.delete_box(db, box_id, 'Anurag')
        boxes  = models.get_boxes_at_location(db, loc_id)
        labels = [b['label'] for b in boxes]
        assert 'Stationery' not in labels

    def test_delete_nonexistent_box_returns_none(self, db):
        result = models.delete_box(db, 99999, 'test')
        assert result is None


class TestAddBoxItem:

    def test_add_new_category_success(self, db):
        box_id  = get_box_id(db, 'Stationery')
        cat_id  = get_category_id(db, 'Electronics')
        success, msg, item_id = models.add_box_item(db, box_id, cat_id, 'Anurag')
        assert success is True
        assert item_id is not None

    def test_add_duplicate_category_fails(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        success, msg, item_id = models.add_box_item(db, box_id, cat_id, 'Anurag')
        assert success is False
        assert 'already active' in msg

    def test_add_item_to_nonexistent_box_fails(self, db):
        cat_id = get_category_id(db, 'Stationery')
        success, msg, item_id = models.add_box_item(db, 99999, cat_id, 'test')
        assert success is False
        assert 'not found' in msg.lower()

    def test_add_nonexistent_category_fails(self, db):
        box_id = get_box_id(db, 'Stationery')
        success, msg, item_id = models.add_box_item(db, box_id, 99999, 'test')
        assert success is False

    def test_removed_item_can_be_reinstated(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        models.remove_box_item(db, box_id, item['id'], 'test', 'consumed')
        success, msg, new_item_id = models.add_box_item(db, box_id, cat_id, 'test')
        assert success is True


class TestRemoveBoxItem:

    def test_remove_item_success(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        success, msg = models.remove_box_item(db, box_id, item['id'], 'Anurag', 'consumed')
        assert success is True

    def test_removed_item_marked_in_db(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        models.remove_box_item(db, box_id, item['id'], 'Anurag', 'consumed')
        after = db.execute(
            "SELECT is_removed, reason FROM box_item WHERE id = ?", (item['id'],)
        ).fetchone()
        assert after['is_removed'] == 1
        assert after['reason'] == 'consumed'

    def test_remove_nonexistent_item_fails(self, db):
        box_id = get_box_id(db, 'Stationery')
        success, msg = models.remove_box_item(db, box_id, 99999, 'test', 'consumed')
        assert success is False

    def test_remove_with_invalid_reason_defaults_to_consumed(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        models.remove_box_item(db, box_id, item['id'], 'test', 'nonsense_reason')
        after = db.execute(
            "SELECT reason FROM box_item WHERE id = ?", (item['id'],)
        ).fetchone()
        assert after['reason'] == 'consumed'

    def test_audit_log_entry_created(self, db):
        box_id = get_box_id(db, 'Stationery')
        cat_id = get_category_id(db, 'Stationery')
        item   = db.execute(
            "SELECT id FROM box_item WHERE box_id = ? AND category_id = ?",
            (box_id, cat_id)
        ).fetchone()
        before_count = db.execute(
            "SELECT COUNT(*) FROM box_item_log WHERE box_id = ?", (box_id,)
        ).fetchone()[0]
        models.remove_box_item(db, box_id, item['id'], 'Anurag', 'consumed')
        after_count = db.execute(
            "SELECT COUNT(*) FROM box_item_log WHERE box_id = ?", (box_id,)
        ).fetchone()[0]
        assert after_count == before_count + 1
