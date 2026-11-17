import asyncio
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.main import app
from app.service import create_campaign, distribute, prepare_offer_draft


class FakeKeitaro:
    def __init__(self):
        self.stream = {"id": 11, "schema": "landings", "updated_at": "v1", "offers": [
            {"offer_id": 1, "state": "active", "share": 50},
            {"offer_id": 2, "state": "active", "share": 50},
        ]}
        self.writes = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def get(self, path, **kwargs):
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

    def test_create_has_expected_order_and_filter(self):
        tracker = FakeKeitaro()
        asyncio.run(create_campaign(tracker, "New", "ru", 2, 3, 4, 5))
        self.assertEqual([path for path, _ in tracker.writes], ["campaigns", "streams", "streams"])
        self.assertEqual(tracker.writes[1][1]["filters"], [{"name": "country", "mode": "accept", "payload": ["RU"]}])


if __name__ == "__main__":
    unittest.main()
