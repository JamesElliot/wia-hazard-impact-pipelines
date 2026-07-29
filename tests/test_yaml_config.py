from __future__ import annotations

import unittest

from wia_pipelines.hazards._yaml_config import config_hash, merge_config


class YamlConfigTests(unittest.TestCase):
    def test_merge_config_deep_merges_nested_mappings(self) -> None:
        base = {"a": 1, "nested": {"x": 1, "y": 2}}
        override = {"nested": {"y": 20, "z": 30}}
        merged = merge_config(base, override)
        self.assertEqual(merged, {"a": 1, "nested": {"x": 1, "y": 20, "z": 30}})

    def test_merge_config_does_not_mutate_inputs(self) -> None:
        base = {"nested": {"x": 1}}
        override = {"nested": {"y": 2}}
        merge_config(base, override)
        self.assertEqual(base, {"nested": {"x": 1}})
        self.assertEqual(override, {"nested": {"y": 2}})

    def test_merge_config_override_replaces_non_mapping_values(self) -> None:
        base = {"list_field": [1, 2, 3]}
        override = {"list_field": [4]}
        merged = merge_config(base, override)
        self.assertEqual(merged["list_field"], [4])

    def test_config_hash_is_deterministic_and_order_independent(self) -> None:
        h1 = config_hash({"a": 1, "b": 2})
        h2 = config_hash({"b": 2, "a": 1})
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)

    def test_config_hash_changes_with_content(self) -> None:
        h1 = config_hash({"a": 1})
        h2 = config_hash({"a": 2})
        self.assertNotEqual(h1, h2)


if __name__ == "__main__":
    unittest.main()
