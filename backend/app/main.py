from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .config import settings
from .db import ChangeLog, OfferWeightLock, SessionLocal
from .keitaro import Keitaro
from .service import campaign_details, create_campaign, prepare_offer_draft


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Keitaro Campaign Wrapper", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])


class CampaignInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(min_length=2, max_length=2)
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    source_id: int = Field(gt=0)


class DraftOffer(BaseModel):
    offer_id: int = Field(gt=0)
    state: Literal["active", "disabled"]
    share: int = Field(ge=0, le=100)
    locked: bool = False
    locked_share: int | None = Field(default=None, ge=0, le=100)


class StreamDraft(BaseModel):
    expected_updated_at: str | None = None
    offers: list[DraftOffer]


def log_change(campaign_id: int, stream_id: int | None, action: str, offer_id: int | None):
    with SessionLocal() as db:
        db.add(ChangeLog(campaign_id=campaign_id, stream_id=stream_id, action=action, offer_id=offer_id))
        db.commit()


def load_locks(campaign_id: int, stream_id: int | None = None) -> dict[tuple[int, int], int]:
    with SessionLocal() as db:
        query = select(OfferWeightLock).where(OfferWeightLock.campaign_id == campaign_id)
        if stream_id is not None:
            query = query.where(OfferWeightLock.stream_id == stream_id)
        return {(row.stream_id, row.offer_id): row.share for row in db.scalars(query)}


def enrich_details(result: dict) -> dict:
    locks = load_locks(result["campaign"]["id"])
    for stream in result["streams"]:
        for offer in stream.get("offers", []):
            locked_share = locks.get((stream["id"], offer["offer_id"]))
            offer["locked"] = locked_share is not None
            offer["locked_share"] = locked_share
    return result


@app.get("/api/health")
def health():
    return {"ok": True, "configured": bool(settings.keitaro_api_key)}


@app.get("/api/options")
async def options():
    async with Keitaro() as client:
        domains = await client.get("domains")
        groups = await client.get("groups", params={"type": "campaigns"})
        sources = await client.get("traffic_sources")
        offers = await client.get("offers")
    return {
        "domains": [d for d in domains if d.get("state") == "active"],
        "groups": [g for g in groups if g.get("type") == "campaigns"],
        "sources": [s for s in sources if s.get("state") == "active"],
        "offers": [o for o in offers if o.get("state") == "active"],
    }


@app.get("/api/campaigns")
async def campaigns():
    async with Keitaro() as client:
        items = await client.get("campaigns", params={"limit": 1000})
    return [c for c in items if c.get("state") != "deleted"]


@app.post("/api/campaigns", status_code=201)
async def create(data: CampaignInput):
    if not data.name.strip():
        raise HTTPException(422, "Название не может быть пустым")
    async with Keitaro() as client:
        result = await create_campaign(client, **data.model_dump())
    log_change(result["campaign"]["id"], None, "create", data.offer_id)
    return enrich_details(result)


@app.get("/api/campaigns/{campaign_id}")
async def details(campaign_id: int):
    async with Keitaro() as client:
        return enrich_details(await campaign_details(client, campaign_id))


@app.put("/api/campaigns/{campaign_id}/streams/{stream_id}/draft")
async def send_draft(campaign_id: int, stream_id: int, data: StreamDraft):
    async with Keitaro() as client:
        offers, locked_shares = await prepare_offer_draft(
            client, campaign_id, stream_id, [offer.model_dump() for offer in data.offers], data.expected_updated_at
        )
        await client.put(f"streams/{stream_id}", {"offers": offers})
    with SessionLocal() as db:
        db.execute(delete(OfferWeightLock).where(OfferWeightLock.campaign_id == campaign_id, OfferWeightLock.stream_id == stream_id))
        db.add_all(
            OfferWeightLock(campaign_id=campaign_id, stream_id=stream_id, offer_id=offer_id, share=share)
            for offer_id, share in locked_shares.items()
        )
        db.commit()
    log_change(campaign_id, stream_id, "save_draft", None)
    async with Keitaro() as client:
        return enrich_details(await campaign_details(client, campaign_id))


@app.get("/api/campaigns/{campaign_id}/history")
def history(campaign_id: int):
    with SessionLocal() as db:
        return [
            {"id": row.id, "action": row.action, "stream_id": row.stream_id, "offer_id": row.offer_id, "created_at": row.created_at.isoformat()}
            for row in db.scalars(select(ChangeLog).where(ChangeLog.campaign_id == campaign_id).order_by(ChangeLog.id.desc()).limit(50))
        ]
