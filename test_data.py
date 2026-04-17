import json
import os
import pytest

DATA_PATH = os.path.join(os.path.dirname(__file__), "train.json")

EXPECTED_CUISINES = {
    "brazilian", "british", "cajun_creole", "chinese", "filipino",
    "french", "greek", "indian", "irish", "italian", "jamaican",
    "japanese", "korean", "mexican", "moroccan", "russian",
    "southern_us", "spanish", "thai", "vietnamese",
}

REQUIRED_FIELDS = {"id", "cuisine", "ingredients"}


@pytest.fixture(scope="module")
def raw_data():
    with open(DATA_PATH) as f:
        return json.load(f)


class TestDataFilePresence:
    def test_file_exists(self):
        assert os.path.isfile(DATA_PATH), f"Data file not found at {DATA_PATH}"

    def test_file_is_valid_json(self):
        with open(DATA_PATH) as f:
            data = json.load(f)
        assert isinstance(data, list), "Top-level JSON should be a list of records"

    def test_file_not_empty(self, raw_data):
        assert len(raw_data) > 0, "Data file is empty"


class TestDataSchema:
    def test_required_fields_present(self, raw_data):
        for i, record in enumerate(raw_data[:50]):
            missing = REQUIRED_FIELDS - record.keys()
            assert not missing, f"Record {i} missing fields: {missing}"

    def test_id_is_integer(self, raw_data):
        for i, record in enumerate(raw_data[:50]):
            assert isinstance(record["id"], int), f"Record {i} id is not an int"

    def test_cuisine_is_string(self, raw_data):
        for record in raw_data[:50]:
            assert isinstance(record["cuisine"], str)

    def test_ingredients_is_list_of_strings(self, raw_data):
        for i, record in enumerate(raw_data[:50]):
            assert isinstance(record["ingredients"], list), (
                f"Record {i} ingredients is not a list"
            )
            for ing in record["ingredients"]:
                assert isinstance(ing, str), (
                    f"Record {i} has non-string ingredient: {ing}"
                )


class TestDataQuality:
    def test_no_empty_ingredients(self, raw_data):
        for i, record in enumerate(raw_data):
            assert len(record["ingredients"]) > 0, (
                f"Record {i} (id={record['id']}) has no ingredients"
            )

    def test_no_blank_ingredient_strings(self, raw_data):
        for i, record in enumerate(raw_data):
            for ing in record["ingredients"]:
                assert ing.strip(), (
                    f"Record {i} (id={record['id']}) has a blank ingredient"
                )

    def test_cuisine_values_are_known(self, raw_data):
        found = {r["cuisine"] for r in raw_data}
        unknown = found - EXPECTED_CUISINES
        assert not unknown, f"Unexpected cuisine labels: {unknown}"

    def test_expected_cuisines_all_present(self, raw_data):
        found = {r["cuisine"] for r in raw_data}
        missing = EXPECTED_CUISINES - found
        assert not missing, f"Missing expected cuisines: {missing}"

    def test_ids_are_unique(self, raw_data):
        ids = [r["id"] for r in raw_data]
        assert len(ids) == len(set(ids)), "Duplicate ids found"

    def test_minimum_record_count(self, raw_data):
        assert len(raw_data) >= 1000, (
            f"Expected at least 1000 recipes, got {len(raw_data)}"
        )
