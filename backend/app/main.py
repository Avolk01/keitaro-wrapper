from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select

from .config import settings
from .db import ChangeLog, SessionLocal
from .keitaro import Keitaro
from .service import campaign_details, create_campaign, update_offer


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Keitaro Campaign Wrapper", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


class CampaignInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(min_length=2, max_length=2)
    offer_id: int = Field(gt=0)
    domain_id: int = Field(gt=0)
    group_id: int = Field(gt=0)
    source_id: int = Field(gt=0)


class OfferInput(BaseModel):
    offer_id: int = Field(gt=0)


def log_change(campaign_id: int, stream_id: int | None, action: str, offer_id: int | None):
    with SessionLocal() as db:
        db.add(ChangeLog(campaign_id=campaign_id, stream_id=stream_id, action=action, offer_id=offer_id))
        db.commit()


@app.get("/api/health")
def health():
    return {"ok": True, "configured": bool(settings.keitaro_api_key)}


@app.get("/api/options")
async def options():
    async with Keitaro() as client:
        domains = await client.get("domains")
        groups = await client.get("groups")
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
    return result


@app.get("/api/campaigns/{campaign_id}")
async def details(campaign_id: int):
    async with Keitaro() as client:
        return await campaign_details(client, campaign_id)


@app.post("/api/campaigns/{campaign_id}/streams/{stream_id}/offers")
async def add_offer(campaign_id: int, stream_id: int, data: OfferInput):
    async with Keitaro() as client:
        result = await update_offer(client, campaign_id, stream_id, data.offer_id, "add")
    log_change(campaign_id, stream_id, "add", data.offer_id)
    return result


@app.delete("/api/campaigns/{campaign_id}/streams/{stream_id}/offers/{offer_id}")
async def remove_offer(campaign_id: int, stream_id: int, offer_id: int):
    async with Keitaro() as client:
        result = await update_offer(client, campaign_id, stream_id, offer_id, "remove")
    log_change(campaign_id, stream_id, "remove", offer_id)
    return result


@app.get("/api/campaigns/{campaign_id}/history")
def history(campaign_id: int):
    with SessionLocal() as db:
        return [
            {"id": row.id, "action": row.action, "stream_id": row.stream_id, "offer_id": row.offer_id, "created_at": row.created_at.isoformat()}
            for row in db.scalars(select(ChangeLog).where(ChangeLog.campaign_id == campaign_id).order_by(ChangeLog.id.desc()).limit(50))
        ]
