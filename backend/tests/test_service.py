import asyncio
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.keitaro import Keitaro
from app.main import app
from app.service import create_campaign, distribute, prepare_offer_draft


class FakeKeitaro:
    def __init__(self):
        self.stream = {"id": 11, "schema": "landings", "updated_at": "v1", "offers": [
            {"offer_id": 1, "state": "active", "share": 50},
            {"offer_id": 2, "state": "active", "share": 50},
        ]}
        self.writes = []
        self.deleted_offers = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, path, **kwargs):
        if path == "offers/deleted":
            return self.deleted_offers
        if path == "campaigns/7/streams":
            return [self.stream]
        if path == "campaigns/7":
            return {"id": 7, "name": "Test"}
        if path == "groups":
            assert kwargs.get("params") == {"type": "campaigns"}
            return [{"id": 4, "type": "campaigns"}]
        return {"id": int(path.split("/")[-1]), "state": "active"}

    async def post(self, path, data):
        self.writes.append((path, data))
        if path.startswith("offers/") and path.endswith("/restore"):
            offer_id = int(path.split("/")[1])
            self.deleted_offers = [offer for offer in self.deleted_offers if offer["id"] != offer_id]
            return {"id": offer_id, "state": "active"}
        return {"id": 7} if path == "campaigns" else {"id": 11}

    async def put(self, path, data):
        self.writes.append((path, data))
        self.stream["offers"] = data["offers"]
        self.stream["updated_at"] = f"v{len(self.writes) + 1}"
        return self.stream


def draft_offer(offer_id, state="active", share=0, locked=False, locked_share=None):
    return {"offer_id": offer_id, "state": state, "share": share,
            "locked": locked, "locked_share": locked_share}


class ServiceTest(unittest.TestCase):
    def test_empty_restore_response_is_accepted(self):
        tracker = object.__new__(Keitaro)

        async def exercise():
            tracker.client = httpx.AsyncClient(
                base_url="http://test/",
                transport=httpx.MockTransport(lambda request: httpx.Response(201)),
            )
            try:
                return await tracker.post("offers/2/restore", {})
            finally:
                await tracker.client.aclose()

        self.assertEqual(asyncio.run(exercise()), {})

    def test_distribute_exactly_100_with_lock(self):
        items = [draft_offer(1, share=50), draft_offer(2), draft_offer(3)]
        self.assertEqual([item["share"] for item in distribute(items, {1: 50})], [50, 25, 25])

    def test_rejects_unallocatable_remainder(self):
        items = [draft_offer(1, share=50), draft_offer(2, "disabled")]
        with self.assertRaises(HTTPException) as raised:
            distribute(items, {1: 50})
        self.assertEqual(raised.exception.status_code, 409)

    def test_draft_validation_does_not_write(self):
        tracker = FakeKeitaro()
        submitted = [draft_offer(1, share=50, locked=True, locked_share=50), draft_offer(2, share=50)]
        offers, locks = asyncio.run(prepare_offer_draft(tracker, 7, 11, submitted, "v1"))
        self.assertEqual([item["share"] for item in offers], [50, 50])
        self.assertEqual(locks, {1: 50})
        self.assertEqual(tracker.writes, [])

    def test_rejects_stale_draft_without_write(self):
        tracker = FakeKeitaro()
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(prepare_offer_draft(tracker, 7, 11, [draft_offer(1), draft_offer(2)], "old"))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(tracker.writes, [])

    def test_send_draft_add_remove_restore_and_lock(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        tracker = FakeKeitaro()

        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                path = "/api/campaigns/7/streams/11/draft"
                initial = await client.get("/api/campaigns/7")
                add = await client.put(path, json={"expected_updated_at": "v1", "offers": [
                    draft_offer(1, share=50, locked=True, locked_share=50), draft_offer(2, share=50), draft_offer(3)]})
                after_add = add.json()["streams"][0]
                remove = await client.put(path, json={"expected_updated_at": after_add["updated_at"], "offers": [
                    draft_offer(1, share=50, locked=True, locked_share=50), draft_offer(2, "disabled"), draft_offer(3, share=25)]})
                after_remove = remove.json()["streams"][0]
                restore = await client.put(path, json={"expected_updated_at": after_remove["updated_at"], "offers": [
                    draft_offer(1, share=50, locked=True, locked_share=50), draft_offer(2), draft_offer(3)]})
                return initial, add, remove, restore

        with patch("app.main.Keitaro", lambda: tracker), patch("app.main.SessionLocal", sessionmaker(bind=engine)):
            initial, add, remove, restore = asyncio.run(exercise())
        self.assertEqual([response.status_code for response in (initial, add, remove, restore)], [200] * 4)
        self.assertFalse(initial.json()["streams"][0]["offers"][0]["locked"])
        self.assertEqual([item["share"] for item in add.json()["streams"][0]["offers"]], [50, 25, 25])
        self.assertTrue(add.json()["streams"][0]["offers"][0]["locked"])
        self.assertEqual([item["share"] for item in remove.json()["streams"][0]["offers"]], [50, 0, 50])
        self.assertEqual([item["share"] for item in restore.json()["streams"][0]["offers"]], [50, 25, 25])
        self.assertEqual(len(tracker.writes), 3)
        engine.dispose()

    def test_externally_deleted_offer_stays_visible_and_can_be_restored(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        tracker = FakeKeitaro()

        async def exercise():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                initial = await client.get("/api/campaigns/7")
                tracker.stream["offers"] = [draft_offer(1, share=100)]
                tracker.stream["updated_at"] = "v2"
                tracker.deleted_offers = [{"id": 2, "name": "Archived offer", "state": "deleted"}]
                after_delete = await client.get("/api/campaigns/7")
                writes_before_send = len(tracker.writes)
                path = "/api/campaigns/7/streams/11/draft"
                restore = await client.put(path, json={"expected_updated_at": "v2", "offers": [
                    draft_offer(1, share=50), draft_offer(2, share=50),
                ]})
                return initial, after_delete, restore, writes_before_send

        with patch("app.main.Keitaro", lambda: tracker), patch("app.main.SessionLocal", sessionmaker(bind=engine)):
            initial, after_delete, restore, writes_before_send = asyncio.run(exercise())
        self.assertEqual([response.status_code for response in (initial, after_delete, restore)], [200] * 3)
        deleted = after_delete.json()["streams"][0]["offers"]
        self.assertEqual([offer["offer_id"] for offer in deleted], [1, 2])
        self.assertEqual(deleted[1]["state"], "disabled")
        self.assertTrue(deleted[1]["archived_in_keitaro"])
        self.assertEqual(writes_before_send, 0)
        self.assertEqual(tracker.writes[0][0], "offers/2/restore")
        self.assertEqual(tracker.writes[1][0], "streams/11")
        self.assertEqual([offer["share"] for offer in restore.json()["streams"][0]["offers"]], [50, 50])
        engine.dispose()

    def test_archived_offer_is_omitted_when_saving_other_changes(self):
        tracker = FakeKeitaro()
        tracker.stream["offers"] = [draft_offer(1, share=50), draft_offer(2, share=50)]
        tracker.deleted_offers = [{"id": 2, "name": "Archived offer", "state": "deleted"}]
        submitted = [draft_offer(1, share=50), draft_offer(2, "disabled"), draft_offer(3, share=50)]
        offers, _ = asyncio.run(prepare_offer_draft(tracker, 7, 11, submitted, "v1", {2}))
        self.assertEqual([offer["offer_id"] for offer in offers], [1, 3])
        self.assertEqual([offer["share"] for offer in offers], [50, 50])
        self.assertEqual(tracker.writes, [])

    def test_create_has_expected_order_and_filter(self):
        tracker = FakeKeitaro()
        asyncio.run(create_campaign(tracker, "New", "ru", 2, 3, 4, 5))
        self.assertEqual([path for path, _ in tracker.writes], ["campaigns", "streams", "streams"])
        self.assertEqual(tracker.writes[1][1]["filters"], [{"name": "country", "mode": "accept", "payload": ["RU"]}])


if __name__ == "__main__":
    unittest.main()
