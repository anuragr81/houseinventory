"""
tests/test_house_xml.py
------------------------
Validates inventory/config/house.xml independently of the database.
These tests read the XML file directly — no Flask app or DB connection needed.
"""

import os
import pytest
import xml.etree.ElementTree as ET


XML_PATH = os.path.join(os.path.dirname(__file__), '..', 'inventory', 'config', 'house.xml')


@pytest.fixture(scope='module')
def root():
    return ET.parse(XML_PATH).getroot()


class TestWellFormed:

    def test_parses_without_error(self):
        ET.parse(XML_PATH)


class TestCodes:

    def test_all_codes_unique(self, root):
        seen = {}
        duplicates = []
        for el in root.iter():
            code = el.get('code')
            if code is None:
                continue
            if code in seen:
                duplicates.append(
                    f"'{code}' on <{el.tag}> (first seen on <{seen[code]}>)"
                )
            else:
                seen[code] = el.tag
        assert not duplicates, "Duplicate codes in house.xml:\n" + "\n".join(duplicates)

    def test_all_rooms_have_code(self, root):
        missing = [ET.tostring(el, encoding='unicode') for el in root.findall('room') if not el.get('code')]
        assert not missing, f"Rooms missing 'code': {missing}"

    def test_all_furniture_have_code(self, root):
        missing = [ET.tostring(el, encoding='unicode') for el in root.iter('furniture') if not el.get('code')]
        assert not missing, f"Furniture missing 'code': {missing}"

    def test_all_shelves_have_code(self, root):
        missing = [ET.tostring(el, encoding='unicode') for el in root.iter('shelf') if not el.get('code')]
        assert not missing, f"Shelves missing 'code': {missing}"


class TestNames:

    def test_all_rooms_have_name(self, root):
        missing = [el.get('code', '?') for el in root.findall('room') if not el.get('name')]
        assert not missing, f"Rooms missing 'name': {missing}"

    def test_all_furniture_have_name(self, root):
        missing = [el.get('code', '?') for el in root.iter('furniture') if not el.get('name')]
        assert not missing, f"Furniture missing 'name': {missing}"

    def test_all_shelves_have_name(self, root):
        missing = [el.get('code', '?') for el in root.iter('shelf') if not el.get('name')]
        assert not missing, f"Shelves missing 'name': {missing}"


class TestHierarchy:

    def test_at_least_one_room(self, root):
        assert root.findall('room'), "house.xml defines no rooms"

    def test_no_furniture_directly_under_house(self, root):
        assert not root.findall('furniture'), \
            "furniture elements must be nested inside a room, not directly under <house>"

    def test_no_shelf_directly_under_house(self, root):
        assert not root.findall('shelf'), \
            "shelf elements must be nested inside furniture, not directly under <house>"

    def test_no_shelf_directly_under_room(self, root):
        offenders = [
            room.get('code', '?')
            for room in root.findall('room')
            if room.findall('shelf')
        ]
        assert not offenders, \
            f"shelf elements found directly under rooms {offenders} — they must be inside furniture"

    def test_shelves_have_no_children(self, root):
        offenders = [
            shelf.get('code', '?')
            for shelf in root.iter('shelf')
            if len(shelf)
        ]
        assert not offenders, \
            f"Shelves must not contain child elements, but these do: {offenders}"
