import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import notion_http  # noqa: E402


class NotionHttpReadRecordsTests(unittest.TestCase):
    def test_read_records_uses_get_record_values_for_workflow(self) -> None:
        with mock.patch.object(
            notion_http,
            "_post",
            return_value={"results": [{"value": {"id": "wf-1", "data": {}}}]},
        ) as post_mock:
            records = notion_http.read_records("workflow", ["wf-1"], "token", "user-1")

        self.assertEqual(records["wf-1"]["id"], "wf-1")
        endpoint, payload, token, user_id = post_mock.call_args.args[:4]
        self.assertEqual(endpoint, "getRecordValues")
        self.assertEqual(payload, {"requests": [{"id": "wf-1", "table": "workflow"}]})
        self.assertEqual(token, "token")
        self.assertEqual(user_id, "user-1")

    def test_read_records_uses_space_pointer_for_workflow_artifact(self) -> None:
        response = {
            "recordMap": {
                "__version__": 3,
                "workflow_artifact": {
                    "artifact-1": {
                        "value": {
                            "value": {
                                "id": "artifact-1",
                                "created_at": 123,
                                "data": {"publishTime": 123},
                            }
                        }
                    }
                },
            }
        }
        with mock.patch.object(notion_http, "_post", return_value=response) as post_mock:
            records = notion_http.read_records(
                "workflow_artifact",
                ["artifact-1"],
                "token",
                "user-1",
                space_id="space-1",
            )

        self.assertEqual(records["artifact-1"]["id"], "artifact-1")
        endpoint, payload, token, user_id = post_mock.call_args.args[:4]
        self.assertEqual(endpoint, "syncRecordValuesSpaceInitial")
        self.assertEqual(
            payload,
            {
                "requests": [
                    {
                        "pointer": {
                            "table": "workflow_artifact",
                            "id": "artifact-1",
                            "spaceId": "space-1",
                        },
                        "version": -1,
                    }
                ]
            },
        )
        self.assertEqual(token, "token")
        self.assertEqual(user_id, "user-1")

    def test_read_records_requires_space_id_for_workflow_artifact(self) -> None:
        with self.assertRaisesRegex(ValueError, "space_id is required"):
            notion_http.read_records("workflow_artifact", ["artifact-1"], "token", "user-1")

    def test_read_records_retries_missing_workflow_artifact_records_individually(self) -> None:
        batch_response = {"recordMap": {"__version__": 3}}
        single_response = {
            "recordMap": {
                "__version__": 3,
                "workflow_artifact": {
                    "artifact-1": {
                        "value": {
                            "value": {
                                "id": "artifact-1",
                                "created_at": 123,
                                "data": {"publishTime": 123},
                            }
                        }
                    }
                },
            }
        }
        with mock.patch.object(
            notion_http,
            "_post",
            side_effect=[batch_response, single_response],
        ) as post_mock:
            records = notion_http.read_records(
                "workflow_artifact",
                ["artifact-1"],
                "token",
                "user-1",
                space_id="space-1",
            )

        self.assertEqual(records["artifact-1"]["id"], "artifact-1")
        self.assertEqual(post_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
