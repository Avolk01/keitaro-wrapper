import re
import secrets

from fastapi import HTTPException


def make_alias() -> str:
    return "cw-" + secrets.token_hex(5)


def validate_geo(geo: str) -> str:
    geo = geo.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", geo):
        raise HTTPException(422, "Гео-код должен состоять из двух латинских букв")
    return geo


def distribute(offers: list[dict]) -> list[dict]:
    """Assign whole percentage points without losing or creating traffic."""
    active = [o for o in offers if o.get("state", "active") == "active"]
    if active:
        q, rem = divmod(100, len(active))
        for i, offer in enumerate(active):
            offer["share"] = q + (1 if i < rem else 0)
    for offer in offers:
        if offer.get("state") != "active":
            offer["share"] = 0
    return offers


def offers_for_update(stream: dict) -> list[dict]:
    return [
        {"offer_id": item["offer_id"], "state": item.get("state", "active"), "share": item.get("share", 0)}
        for item in stream.get("offers", [])
    ]


async def campaign_details(client, campaign_id: int) -> dict:
    campaign = await client.get(f"campaigns/{campaign_id}")
    streams = await client.get(f"campaigns/{campaign_id}/streams")
    return {"campaign": campaign, "streams": streams}


async def update_offer(client, campaign_id: int, stream_id: int, offer_id: int, action: str) -> dict:
    streams = await client.get(f"campaigns/{campaign_id}/streams")
    stream = next((s for s in streams if s["id"] == stream_id), None)
    if not stream:
        raise HTTPException(404, "Поток не найден в кампании")
    if stream.get("schema") != "landings":
        raise HTTPException(422, "Офферы можно менять только в потоке лендингов и офферов")
    offers = offers_for_update(stream)
    current = next((o for o in offers if o["offer_id"] == offer_id), None)
    if action == "add":
        if current and current["state"] == "active":
            raise HTTPException(409, "Оффер уже добавлен")
        if current:
            current["state"] = "active"
        else:
            await client.get(f"offers/{offer_id}")
            offers.append({"offer_id": offer_id, "state": "active", "share": 0})
    elif action == "remove":
        if not current or current["state"] != "active":
            raise HTTPException(404, "Активный оффер не найден")
        current["state"] = "disabled"
    else:
        raise ValueError(action)
    await client.put(f"streams/{stream_id}", {"offers": distribute(offers)})
    return await campaign_details(client, campaign_id)


async def create_campaign(client, name: str, geo: str, offer_id: int, domain_id: int, group_id: int, source_id: int) -> dict:
    geo = validate_geo(geo)
    # Validate references before creating the campaign.
    await client.get(f"offers/{offer_id}")
    await client.get(f"domains/{domain_id}")
    await client.get(f"traffic_sources/{source_id}")
    groups = await client.get("groups")
    if not any(g["id"] == group_id and g.get("type") == "campaigns" for g in groups):
        raise HTTPException(422, "Выберите группу кампаний")
    campaign = await client.post("campaigns", {
        "name": name.strip(), "alias": make_alias(), "domain_id": domain_id,
        "group_id": str(group_id), "traffic_source_id": source_id, "type": "position",
    })
    campaign_id = campaign["id"]
    try:
        await client.post("streams", {
            "campaign_id": campaign_id, "type": "regular", "name": f"{geo} → Google",
            "position": 1, "schema": "redirect", "action_type": "http",
            "action_payload": "https://www.google.com/", "collect_clicks": True,
            "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
        })
        await client.post("streams", {
            "campaign_id": campaign_id, "type": "default", "name": "Оффер",
            "position": 2, "schema": "landings", "action_type": "http",
            "collect_clicks": True, "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        })
    except HTTPException as exc:
        raise HTTPException(502, {"message": "Кампания создана, но потоки настроены не полностью", "campaign_id": campaign_id, "cause": exc.detail}) from exc
    return await campaign_details(client, campaign_id)
