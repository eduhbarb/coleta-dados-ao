"""Testes unitários para o cliente REST do Firebase Firestore."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import firebase_client  # noqa: E402
from firebase_client import (  # noqa: E402
    build_commit_payload,
    check_user_permission,
    from_firestore_value,
    merge_subjects_by_filter,
    to_firestore_value,
)


class FirebaseClientTests(unittest.TestCase):
    def test_firestore_value_roundtrip_types(self) -> None:
        sample = {
            "id": "FCEE01-14886",
            "period": 1,
            "subjectOfPeriod": True,
            "credits": 5,
            "emptyList": [],
            "classes": [{"classNumber": 1, "teachers": ["PROF A"]}],
            "note": None,
        }
        encoded = to_firestore_value(sample)
        self.assertEqual(encoded["mapValue"]["fields"]["subjectOfPeriod"], {"booleanValue": True})
        self.assertEqual(encoded["mapValue"]["fields"]["period"], {"integerValue": "1"})
        self.assertEqual(encoded["mapValue"]["fields"]["emptyList"], {"arrayValue": {}})
        self.assertEqual(from_firestore_value(encoded), sample)

    def test_merge_subjects_preserves_other_types(self) -> None:
        existing = [
            {"id": "SUB-1", "period": 1, "type": "MANDATORY", "name": "Old Mandatory"},
            {"id": "SUB-2", "period": 6, "type": "DEFINED", "name": "Existing Defined"},
        ]
        new_items = [
            {"id": "SUB-1", "period": 1, "type": "MANDATORY", "name": "Updated Mandatory"},
        ]
        merged = merge_subjects_by_filter(existing, new_items, "MANDATORY")
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["name"], "Updated Mandatory")
        self.assertEqual(merged[1]["name"], "Existing Defined")

    def test_build_commit_payload_uses_request_time_transforms(self) -> None:
        payload = build_commit_payload(
            project_id="meu-projeto",
            user_email="Teste@Exemplo.com",
            course="tads",
            period="2026.2",
            scraped_at="2026-11-24T19:00:00Z",
            source="aluno-online",
            final_subjects=[{"id": "SUB-1", "name": "Algo", "classes": []}],
            run_id="run123",
            done_count=1,
            log_lines=["ok"],
        )
        writes = payload["writes"]
        self.assertEqual(len(writes), 3)
        self.assertEqual(
            writes[0]["update"]["name"],
            "projects/meu-projeto/databases/(default)/documents/catalogs/tads/periods/2026.2",
        )
        self.assertEqual(
            writes[0]["updateTransforms"],
            [{"fieldPath": "updatedAt", "setToServerValue": "REQUEST_TIME"}],
        )
        self.assertEqual(writes[0]["update"]["fields"]["updatedBy"], {"stringValue": "teste@exemplo.com"})
        self.assertEqual(
            writes[2]["updateTransforms"],
            [{"fieldPath": "finishedAt", "setToServerValue": "REQUEST_TIME"}],
        )

    def test_check_user_permission_variants(self) -> None:
        with patch.object(
            firebase_client,
            "_http_json",
            return_value={
                "fields": {
                    "active": {"booleanValue": True},
                    "permissions": {
                        "mapValue": {
                            "fields": {"coleta_app": {"booleanValue": True}}
                        }
                    },
                }
            },
        ):
            res = check_user_permission("proj", "tok", "user@example.com")
            self.assertTrue(res["authorized"])

        with patch.object(
            firebase_client,
            "_http_json",
            return_value={
                "fields": {
                    "active": {"booleanValue": True},
                    "permissions": {
                        "mapValue": {
                            "fields": {"coleta_app": {"booleanValue": False}}
                        }
                    },
                }
            },
        ):
            res = check_user_permission("proj", "tok", "user@example.com")
            self.assertFalse(res["authorized"])

        with patch.object(
            firebase_client,
            "_http_json",
            return_value={
                "fields": {
                    "active": {"booleanValue": False},
                    "permissions": {
                        "mapValue": {
                            "fields": {"adm_manage": {"booleanValue": True}}
                        }
                    },
                }
            },
        ):
            res = check_user_permission("proj", "tok", "user@example.com")
            self.assertFalse(res["authorized"])


if __name__ == "__main__":
    unittest.main()
