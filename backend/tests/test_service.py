import asyncio
import unittest

from fastapi import HTTPException

from app.service import create_campaign, distribute, update_offer


class FakeKeitaro:
    def __init__(self):
        self.stream = {"id": 11, "schema": "landings", "offers": [
            {"offer_id": 1, "state": "active", "share": 50},
            {"offer_id": 2, "state": "active", "share": 50},
        ]}
        self.writes = []

    async def get(self, path):
        if path == "campaigns/7/streams":
            return [self.stream]
        if path == "campaigns/7":
            return {"id": 7, "name": "Test"}
        if path == "groups":
            return [{"id": 4, "type": "campaigns"}]
        return {"id": int(path.split("/")[-1])}

    async def post(self, path, data):
        self.writes.append((path, data))
        return {"id": 7} if path == "campaigns" else {"id": 11}

    async def put(self, path, data):
        self.writes.append((path, data))
        self.stream["offers"] = data["offers"]
        return self.stream


class ServiceTest(unittest.TestCase):
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
