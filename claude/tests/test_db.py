"""
tests/test_db.py
-----------------
Tests that the schema and seed data are correctly set up.
These are foundational — if these fail, nothing else will work.
"""

import pytest
from inventory.db import get_db
from tests.conftest import get_category_id, get_location_id


class TestSchema:

    def test_tables_exist(self, db):
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        expected = {
            'location', 'super_category', 'mid_category',
            'category', 'box', 'box_item', 'box_item_log'
        }
        assert expected.issubset(tables)

    def test_foreign_keys_enabled(self, db):
        result = db.execute("PRAGMA foreign_keys").fetchone()[0]
        assert result == 1


class TestSuperCategories:

    def test_all_super_categories_seeded(self, db):
        rows = db.execute("SELECT name FROM super_category").fetchall()
        names = {r['name'] for r in rows}
        expected = {
            'Food', 'Clothing', 'Sports', 'Electronics',
            'Stationery', 'Media, Collections & Keepsakes',
            'Cleaning', 'Tools', 'Bedding & Linen',
        }
        assert expected == names

    def test_super_category_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM super_category").fetchone()[0]
        assert count == 9


class TestMidCategories:

    def test_tools_mid_categories(self, db):
        tools_id = db.execute(
            "SELECT id FROM super_category WHERE name = 'Tools'"
        ).fetchone()['id']
        rows = db.execute(
            "SELECT name FROM mid_category WHERE super_category_id = ?", (tools_id,)
        ).fetchall()
        names = {r['name'] for r in rows}
        expected = {
            'Power tools', 'Hand tools', 'Woodworking',
            'Plumbing & electrical', 'Decorating & masonry', 'Repair & fixing',
        }
        assert expected == names

    def test_media_mid_categories(self, db):
        sc_id = db.execute(
            "SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes'"
        ).fetchone()['id']
        rows = db.execute(
            "SELECT name FROM mid_category WHERE super_category_id = ?", (sc_id,)
        ).fetchall()
        names = {r['name'] for r in rows}
        assert names == {'Media', 'Collections', 'Keepsakes'}

    def test_flat_super_cats_have_no_mid_categories(self, db):
        flat_super_cats = ['Food', 'Clothing', 'Sports', 'Electronics',
                           'Stationery', 'Cleaning', 'Bedding & Linen']
        for sc_name in flat_super_cats:
            sc_id = db.execute(
                "SELECT id FROM super_category WHERE name = ?", (sc_name,)
            ).fetchone()['id']
            count = db.execute(
                "SELECT COUNT(*) FROM mid_category WHERE super_category_id = ?",
                (sc_id,)
            ).fetchone()[0]
            assert count == 0, f"{sc_name} should be flat but has mid-categories"


class TestLeafCategories:

    def test_leaf_category_total_count(self, db):
        count = db.execute("SELECT COUNT(*) FROM category").fetchone()[0]
        assert count == 32

    def test_tools_leaf_categories(self, db):
        tools_id = db.execute(
            "SELECT id FROM super_category WHERE name = 'Tools'"
        ).fetchone()['id']
        rows = db.execute(
            "SELECT name FROM category WHERE super_category_id = ?", (tools_id,)
        ).fetchall()
        names = {r['name'] for r in rows}
        expected = {
            'Power tools', 'General hand tools', 'Measuring & marking',
            'Woodworking', 'Plumbing', 'Electrical',
            'Decorating', 'Masonry', 'Sewing & repairs', 'Adhesives & fixings',
        }
        assert expected == names

    def test_repair_fixing_categories(self, db):
        mc = db.execute(
            "SELECT id FROM mid_category WHERE name = 'Repair & fixing'"
        ).fetchone()
        rows = db.execute(
            "SELECT name FROM category WHERE mid_category_id = ?", (mc['id'],)
        ).fetchall()
        names = {r['name'] for r in rows}
        assert names == {'Sewing & repairs', 'Adhesives & fixings'}

    def test_bedding_linen_categories(self, db):
        sc_id = db.execute(
            "SELECT id FROM super_category WHERE name = 'Bedding & Linen'"
        ).fetchone()['id']
        rows = db.execute(
            "SELECT name FROM category WHERE super_category_id = ?", (sc_id,)
        ).fetchall()
        names = {r['name'] for r in rows}
        assert names == {
            'Duvets & pillows', 'Bed linen',
            'Towels & bathroom linen', 'Soft furnishings'
        }


class TestLocations:

    def test_rooms_seeded(self, db):
        rooms = db.execute(
            "SELECT name FROM location WHERE level = 'ROOM'"
        ).fetchall()
        names = {r['name'] for r in rooms}
        assert {'Kitchen', 'Study', 'Garage'}.issubset(names)

    def test_location_hierarchy_intact(self, db):
        # KIT-C2-S2 should have parent KIT-C2 which has parent KIT
        shelf = db.execute(
            "SELECT * FROM location WHERE code = 'KIT-C2-S2'"
        ).fetchone()
        assert shelf is not None
        furn = db.execute(
            "SELECT * FROM location WHERE id = ?", (shelf['parent_id'],)
        ).fetchone()
        assert furn['code'] == 'KIT-C2'
        room = db.execute(
            "SELECT * FROM location WHERE id = ?", (furn['parent_id'],)
        ).fetchone()
        assert room['code'] == 'KIT'
