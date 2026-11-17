import asyncio
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException

from app.main import app
from app.service import create_campaign, distribute, update_offer


class FakeKeitaro:
    def __init__(self):
        self.stream = {"id": 11, "schema": "landings", "offers": [
            {"offer_id": 1, "state": "active", "share": 50},
            {"offer_id": 2, "state": "active", "share": 50},
        ]}
        self.writes = []

    async def get(self, path, **kwargs):
        if path == "campaigns/7/streams":
            return [self.stream]
        if path == "campaigns/7":
            return {"id": 7, "name": "Test"}
        if path == "groups":
            self.assert_group_type(kwargs)
            return [{"id": 4, "type": "campaigns"}]
        return {"id": int(path.split("/")[-1])}

    @staticmethod
    def assert_group_type(kwargs):
        assert kwargs.get("params") == {"type": "campaigns"}

    async def post(self, path, data):
        self.writes.append((path, data))
        return {"id": 7} if path == "campaigns" else {"id": 11}

    async def put(self, path, data):
        self.writes.append((path, data))
        self.stream["offers"] = data["offers"]
        return self.stream


class ServiceTest(unittest.TestCase):
    def test_options_load_with_required_group_type(self):
        class OptionsKeitaro:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def get(self, path, **kwargs):
                if path == "groups":
                    if kwargs.get("params") != {"type": "campaigns"}:
                        raise HTTPException(400, "Param 'type' is required")
                    return [{"id": 2, "name": "Test group", "type": "campaigns"}]
                return [{"id": 1, "name": path, "state": "active"}]

        async def fetch():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                return await client.get("/api/options")

        with patch("app.main.Keitaro", OptionsKeitaro):
            response = asyncio.run(fetch())
        self.assertEqual(response.status_code, 200)
        self.assertEqual({key: len(items) for key, items in response.json().items()},
                         {"domains": 1, "groups": 1, "sources": 1, "offers": 1})

    def test_distribute_exactly_100(self):
        result = distribute([{"offer_id": n, "state": "active"} for n in range(3)])
        self.assertEqual([o["share"] for o in result], [34, 33, 33])

    def test_remove_then_restore(self):
        client = FakeKeitaro()
        asyncio.run(update_offer(client, 7, 11, 1, "remove"))
        self.assertEqual([o["share"] for o in client.stream["offers"]], [0, 100])
        self.assertEqual(client.stream["offers"][0]["state"], "disabled")
        asyncio.run(update_offer(client, 7, 11, 1, "add"))
        self.assertEqual([o["share"] for o in client.stream["offers"]], [50, 50])

    def test_create_has_expected_order_and_filter(self):
        client = FakeKeitaro()
        asyncio.run(create_campaign(client, "New", "ru", 2, 3, 4, 5))
        self.assertEqual([path for path, _ in client.writes], ["campaigns", "streams", "streams"])
        self.assertEqual(client.writes[1][1]["filters"], [{"name": "country", "mode": "accept", "payload": ["RU"]}])
        self.assertEqual(client.writes[2][1]["offers"][0]["share"], 100)

    def test_rejects_wrong_stream(self):
        client = FakeKeitaro()
        client.stream["schema"] = "redirect"
        with self.assertRaises(HTTPException):
            asyncio.run(update_offer(client, 7, 11, 3, "add"))


if __name__ == "__main__":
    unittest.main()
