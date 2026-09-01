"""
tests/test_facet_catalogue_loader.py
-------------------------------------
`load_catalogue`: reading a `FacetCatalogue` from a JSON file.

Validation itself (unique keys, no TEXT, bounded scales) is already covered
in tests/test_privacy_invariants.py and tests/test_community_founding.py via
the constructors this function calls -- what is new here is the file-reading
seam: a missing file, invalid JSON, and a malformed entry, each of which
should fail as a `FacetCatalogueError`, not as whatever exception `json` or
`pathlib` happens to raise.
"""

import json
from pathlib import Path

import pytest

from app.domain.facet_catalogue import FacetCatalogueError, load_catalogue


def _write(tmp_path: Path, content: object) -> str:
    path = tmp_path / "catalogue.json"
    path.write_text(json.dumps(content))
    return str(path)


def test_a_valid_catalogue_loads(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            {
                "key": "body",
                "name": "Body",
                "value_type": "NUMERIC",
                "scale_min": 0.0,
                "scale_max": 10.0,
            },
            {"key": "organic", "name": "Organic", "value_type": "BOOLEAN"},
        ],
    )

    catalogue = load_catalogue(path)

    assert catalogue.keys == frozenset({"body", "organic"})


def test_a_missing_file_is_a_facet_catalogue_error(tmp_path: Path) -> None:
    with pytest.raises(FacetCatalogueError, match="not found"):
        load_catalogue(str(tmp_path / "does-not-exist.json"))


def test_invalid_json_is_a_facet_catalogue_error(tmp_path: Path) -> None:
    path = tmp_path / "catalogue.json"
    path.write_text("{ not json")

    with pytest.raises(FacetCatalogueError, match="not valid JSON"):
        load_catalogue(str(path))


def test_an_entry_missing_a_required_field_is_a_facet_catalogue_error(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path, [{"key": "body", "value_type": "NUMERIC"}])  # no name

    with pytest.raises(FacetCatalogueError, match="missing"):
        load_catalogue(path)


def test_an_unknown_value_type_is_a_facet_catalogue_error(tmp_path: Path) -> None:
    path = _write(tmp_path, [{"key": "body", "name": "Body", "value_type": "COLOUR"}])

    with pytest.raises(FacetCatalogueError, match="value_type"):
        load_catalogue(path)


def test_a_text_facet_in_the_file_is_still_refused(tmp_path: Path) -> None:
    """The file-loading seam does not bypass the same rule the constructor enforces."""
    path = _write(tmp_path, [{"key": "notes", "name": "Notes", "value_type": "TEXT"}])

    with pytest.raises(FacetCatalogueError):
        load_catalogue(path)


def test_an_empty_catalogue_file_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, [])

    with pytest.raises(FacetCatalogueError, match="found nothing"):
        load_catalogue(path)
