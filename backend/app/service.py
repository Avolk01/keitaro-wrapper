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


def distribute(offers: list[dict], locked_shares: dict[int, int] | None = None) -> list[dict]:
    """Keep locked shares and divide the remaining whole percentage points."""
    locked_shares = locked_shares or {}
    active = [o for o in offers if o.get("state", "active") == "active"]
    locked = [o for o in active if o["offer_id"] in locked_shares]
    unlocked = [o for o in active if o["offer_id"] not in locked_shares]
    locked_total = sum(locked_shares[o["offer_id"]] for o in locked)
    if locked_total > 100:
        raise HTTPException(409, "Сумма закреплённых долей превышает 100%")
    if active and not unlocked and locked_total != 100:
        raise HTTPException(409, "Нельзя изменить поток: для остатка трафика нет незакреплённого оффера")
    for offer in locked:
        offer["share"] = locked_shares[offer["offer_id"]]
    if unlocked:
        q, rem = divmod(100 - locked_total, len(unlocked))
        for i, offer in enumerate(unlocked):
            offer["share"] = q + (1 if i < rem else 0)
    for offer in offers:
        if offer.get("state") != "active":
            offer["share"] = 0
    return offers


async def campaign_details(client, campaign_id: int) -> dict:
    campaign = await client.get(f"campaigns/{campaign_id}")
    streams = await client.get(f"campaigns/{campaign_id}/streams")
    return {"campaign": campaign, "streams": streams}


async def prepare_offer_draft(client, campaign_id: int, stream_id: int, offers: list[dict],
                              expected_updated_at: str | None,
                              archived_ids: set[int] | None = None) -> tuple[list[dict], dict[int, int]]:
    archived_ids = archived_ids or set()
    streams = await client.get(f"campaigns/{campaign_id}/streams")
    stream = next((s for s in streams if s["id"] == stream_id), None)
    if not stream:
        raise HTTPException(404, "Поток не найден в кампании")
    if stream.get("schema") != "landings":
        raise HTTPException(422, "Офферы можно менять только в потоке лендингов и офферов")
    if expected_updated_at and stream.get("updated_at") != expected_updated_at:
        raise HTTPException(409, "Поток изменился в Keitaro. Обновите данные перед отправкой")
    submitted_ids = [offer["offer_id"] for offer in offers]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise HTTPException(422, "Оффер указан в потоке несколько раз")
    existing_ids = {offer["offer_id"] for offer in stream.get("offers", [])}
    if not existing_ids.issubset(submitted_ids):
        raise HTTPException(422, "Черновик должен содержать все существующие офферы потока")
    for offer in offers:
        if offer["offer_id"] not in existing_ids and offer["state"] == "active":
            if offer["offer_id"] in archived_ids:
                continue
            existing_offer = await client.get(f"offers/{offer['offer_id']}")
            if existing_offer.get("state") != "active":
                raise HTTPException(422, f"Оффер #{offer['offer_id']} недоступен")
    locked_shares = {offer["offer_id"]: offer["locked_share"] for offer in offers if offer["state"] == "active" and offer["locked"]}
    if any(value is None for value in locked_shares.values()):
        raise HTTPException(422, "Для закреплённого оффера нужна доля")
    # Missing rows are remembered locally for the editor, not sent back to Keitaro
    # until the user restores them. Archived offers cannot be included as disabled.
    payload = [
        {"offer_id": offer["offer_id"], "state": offer["state"], "share": offer["share"]}
        for offer in offers
        if offer["state"] == "active" or (offer["offer_id"] in existing_ids and offer["offer_id"] not in archived_ids)
    ]
    original = {offer["offer_id"]: offer for offer in stream.get("offers", [])}
    same_membership = {offer["offer_id"] for offer in payload} == set(original) and all(
        offer["state"] == original[offer["offer_id"]]["state"] for offer in payload
    )
    if same_membership:
        for offer in payload:
            offer["share"] = original[offer["offer_id"]]["share"]
        if any(offer["share"] != locked_shares[offer["offer_id"]] for offer in payload if offer["offer_id"] in locked_shares):
            raise HTTPException(422, "Закреплённая доля должна совпадать с текущей долей оффера")
        return payload, locked_shares
    return distribute(payload, locked_shares), locked_shares


async def create_campaign(client, name: str, geo: str, offer_id: int, domain_id: int, group_id: int, source_id: int) -> dict:
    geo = validate_geo(geo)
    # Validate references before creating the campaign.
    await client.get(f"offers/{offer_id}")
    await client.get(f"domains/{domain_id}")
    await client.get(f"traffic_sources/{source_id}")
    groups = await client.get("groups", params={"type": "campaigns"})
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
