"""
cost_model.py
─────────────
Commercial layer on top of the technical cost tracking in cost_tracker.py.

Tracks:
  - Agencies (clients) - shared entity with the media library
  - Sales (agency + videos sold + price) - entered separately from jobs so the
    commercial model can stay fluid while pricing is still being tested
  - Investment ledger (the real money already spent) - drives break-even
  - Labour costs (seller commission: 20% of revenue on first commercial sale
    per agency; future: per-video executor fee)

Reporting answers three questions:
  1. Per job:    what did it cost, what did it earn, is it commercial/pilot/rnd
  2. Per agency: total cost, revenue, margin, commission
  3. Enterprise: cumulative revenue vs total investment -> runway to break-even

Design notes:
  - Reworks are NOT separate jobs commercially: their cost folds into the
    parent job (a rework is a cost of delivering that video, not a new sale).
  - Zero-revenue jobs are real and expected (pilots as sales cost, R&D).
    They are shown as investment, not as losses.
"""

import os
import json
import uuid
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent

AGENCIES_FILE   = BASE_DIR / "agencies.json"
PROPERTIES_FILE = BASE_DIR / "properties.json"
SALES_FILE      = BASE_DIR / "sales.json"
INVESTMENT_FILE = BASE_DIR / "investment.json"

# Seller commission: 20% of revenue on the FIRST commercial sale per agency
SELLER_COMMISSION_RATE = 0.20

# Future: per-video fee for the executor (dashboard operator). Zero for now.
EXECUTOR_FEE_PER_VIDEO = float(os.getenv("EXECUTOR_FEE_PER_VIDEO", "0"))

JOB_CLASSIFICATIONS = ["commercial", "pilot", "rnd"]


def _load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            return default
    return default


def _save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ── Agencies ──────────────────────────────────────────────────────────────

def list_agencies():
    return _load(AGENCIES_FILE, [])


def create_agency(name, notes=""):
    agencies = list_agencies()
    for a in agencies:
        if a["name"].strip().lower() == name.strip().lower():
            return a  # idempotent - don't create duplicates
    agency = {
        "agency_id": f"ag_{uuid.uuid4().hex[:8]}",
        "name": name.strip(),
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
        "logo_path": None,  # 2026-07-22: reserved for backlog item 7 (client
        # logo overlay on videos) -- field only, upload/overlay mechanism not
        # built yet. Read with .get("logo_path") since agencies created
        # before this change won't have the key at all.
    }
    agencies.append(agency)
    _save(AGENCIES_FILE, agencies)
    return agency


def get_agency(agency_id):
    return next((a for a in list_agencies() if a["agency_id"] == agency_id), None)


def set_agency_logo(agency_id, logo_path):
    """2026-07-22 (backlog item 7): persists the on-disk path to an
    agency's uploaded logo, for video overlay at assembly time."""
    agencies = list_agencies()
    for a in agencies:
        if a["agency_id"] == agency_id:
            a["logo_path"] = logo_path
    _save(AGENCIES_FILE, agencies)
    return get_agency(agency_id)


# ── Properties ────────────────────────────────────────────────────────
# Shared entity with the media library, same pattern as Agencies above
# (2026-07-22, backlog item 39). One property can have multiple
# independent jobs over time -- an original video plus a completely
# separate reshoot months later, not just in-place reworks of the same
# job (which already don't need a new job entry at all -- see the
# single-directory job model). A property's agency_id is its
# CURRENT/default client; an individual JOB's own agency_id can differ
# if that specific job was actually commissioned by a different agency
# (e.g. the property gets re-listed with a new agent) -- job_financials()
# always uses the job's own agency_id, never the property's, so this
# stays accurate even when they diverge.

def list_properties():
    return _load(PROPERTIES_FILE, [])


def create_property(name, agency_id=None, notes=""):
    """Idempotent within the same agency -- matches create_agency()'s
    existing pattern, so re-submitting the same property name for the
    same client returns the existing record instead of duplicating it.
    A different agency_id with the same name is treated as a distinct
    property (e.g. two different agencies both listing a "Via Roma 15"
    would be two separate records, which is correct -- they are not
    necessarily the same physical property)."""
    properties = list_properties()
    for p in properties:
        if p["name"].strip().lower() == name.strip().lower() and p.get("agency_id") == agency_id:
            return p
    prop = {
        "property_id": f"prop_{uuid.uuid4().hex[:8]}",
        "name": name.strip(),
        "agency_id": agency_id,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
    }
    properties.append(prop)
    _save(PROPERTIES_FILE, properties)
    return prop


def get_property(property_id):
    return next((p for p in list_properties() if p["property_id"] == property_id), None)


def update_property_agency(property_id, agency_id):
    """Reassigns a property to a different current/default client (e.g.
    re-listed with a new agent). Does NOT retroactively change agency_id
    on jobs already linked to this property -- each job's own agency_id
    reflects who actually commissioned that specific job, which must stay
    historically accurate for cost/revenue reporting."""
    properties = list_properties()
    for p in properties:
        if p["property_id"] == property_id:
            p["agency_id"] = agency_id
    _save(PROPERTIES_FILE, properties)
    return get_property(property_id)


# ── Sales ─────────────────────────────────────────────────────────────────

def list_sales():
    return _load(SALES_FILE, [])


def create_sale(agency_id, videos_sold, price_eur, description=""):
    sales = list_sales()
    sale = {
        "sale_id": f"sa_{uuid.uuid4().hex[:8]}",
        "agency_id": agency_id,
        "videos_sold": int(videos_sold),
        "price_eur": float(price_eur),
        "description": description,
        "created_at": datetime.utcnow().isoformat(),
    }
    sales.append(sale)
    _save(SALES_FILE, sales)
    return sale


def delete_sale(sale_id):
    sales = [s for s in list_sales() if s["sale_id"] != sale_id]
    _save(SALES_FILE, sales)


def revenue_per_video(agency_id):
    """Effective revenue per video for an agency, across all their sales.
    A 10-video package at EUR450 -> EUR45/video. Mixed sales blend correctly."""
    sales = [s for s in list_sales() if s["agency_id"] == agency_id]
    total_videos = sum(s["videos_sold"] for s in sales)
    total_revenue = sum(s["price_eur"] for s in sales)
    if total_videos == 0:
        return 0.0
    return total_revenue / total_videos


# ── Investment ledger ─────────────────────────────────────────────────────

def get_investment():
    return _load(INVESTMENT_FILE, {"entries": [], "total_eur": 0.0, "updated_at": None})


def set_investment(entries):
    """Replaces the whole ledger - this is what an XLS re-upload does."""
    total = sum(float(e.get("amount_eur", 0)) for e in entries)
    data = {
        "entries": entries,
        "total_eur": round(total, 2),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save(INVESTMENT_FILE, data)
    return data


# ── Labour ────────────────────────────────────────────────────────────────

def seller_commission_for_agency(agency_id):
    """20% of revenue on the FIRST commercial sale to this agency, one-off."""
    sales = sorted(
        [s for s in list_sales() if s["agency_id"] == agency_id],
        key=lambda s: s["created_at"],
    )
    if not sales:
        return 0.0
    return round(sales[0]["price_eur"] * SELLER_COMMISSION_RATE, 2)


# ── Reporting ─────────────────────────────────────────────────────────────

def job_financials(job):
    """Cost / revenue / margin for a single job.

    Rework costs fold into the parent job - the caller passes the job dict,
    which already accumulates rework cost in cost_actual.
    """
    classification = job.get("classification", "rnd")
    agency_id = job.get("agency_id")

    cost = job.get("cost_actual") or {}
    if isinstance(cost, dict):
        cost_eur = float(cost.get("grand_total_eur", 0) or 0)
    else:
        cost_eur = 0.0
    if cost_eur == 0:
        est = job.get("cost_estimate") or {}
        if isinstance(est, dict):
            cost_eur = float(est.get("grand_total_eur", 0) or 0)

    revenue_eur = 0.0
    if classification == "commercial" and agency_id:
        revenue_eur = revenue_per_video(agency_id)

    revenue_eur += 0.0
    # Claude API cost (scraping, photo ranking, narration, captions) - real
    # measured token usage, not an estimate. Invisible before July 2026.
    claude = job.get("claude_usage") or {}
    claude_eur = float(claude.get("cost_eur", 0) or 0)

    executor = EXECUTOR_FEE_PER_VIDEO
    total_cost = cost_eur + executor + claude_eur

    return {
        "job_id": job.get("job_id"),
        "classification": classification,
        "agency_id": agency_id,
        "cost_eur": round(total_cost, 3),
        "claude_eur": round(claude_eur, 4),
        "revenue_eur": round(revenue_eur, 2),
        "margin_eur": round(revenue_eur - total_cost, 2),
    }


def enterprise_report(jobs):
    """Cumulative revenue vs total investment -> runway to break-even.

    `jobs` is the list of job dicts from api_server.JOBS.values().
    """
    investment = get_investment()
    total_investment = investment["total_eur"]

    sales = list_sales()
    gross_revenue = sum(s["price_eur"] for s in sales)

    # Seller commission: one-off per agency, on their first sale
    agency_ids = {s["agency_id"] for s in sales}
    total_commission = sum(seller_commission_for_agency(aid) for aid in agency_ids)

    # Production cost across all jobs (commercial + pilot + rnd)
    per_job = [job_financials(j) for j in jobs]
    total_production_cost = sum(j["cost_eur"] for j in per_job)

    pilot_cost = sum(j["cost_eur"] for j in per_job if j["classification"] == "pilot")
    rnd_cost   = sum(j["cost_eur"] for j in per_job if j["classification"] == "rnd")

    net_revenue = gross_revenue - total_commission
    net_position = net_revenue - total_production_cost - total_investment

    return {
        "total_investment_eur": round(total_investment, 2),
        "gross_revenue_eur": round(gross_revenue, 2),
        "seller_commission_eur": round(total_commission, 2),
        "net_revenue_eur": round(net_revenue, 2),
        "production_cost_eur": round(total_production_cost, 2),
        "pilot_cost_eur": round(pilot_cost, 2),
        "rnd_cost_eur": round(rnd_cost, 2),
        "net_position_eur": round(net_position, 2),
        "break_even_remaining_eur": round(max(0.0, -net_position), 2),
        "jobs_total": len(per_job),
        "jobs_commercial": sum(1 for j in per_job if j["classification"] == "commercial"),
        "jobs_pilot": sum(1 for j in per_job if j["classification"] == "pilot"),
        "jobs_rnd": sum(1 for j in per_job if j["classification"] == "rnd"),
        "investment_updated_at": investment.get("updated_at"),
    }


def agency_report(jobs):
    """Per-agency cost / revenue / margin."""
    out = []
    for agency in list_agencies():
        aid = agency["agency_id"]
        a_jobs = [j for j in jobs if j.get("agency_id") == aid]
        fins = [job_financials(j) for j in a_jobs]

        sales = [s for s in list_sales() if s["agency_id"] == aid]
        revenue = sum(s["price_eur"] for s in sales)
        videos_sold = sum(s["videos_sold"] for s in sales)
        commission = seller_commission_for_agency(aid)
        cost = sum(f["cost_eur"] for f in fins)

        out.append({
            "agency_id": aid,
            "name": agency["name"],
            "videos_sold": videos_sold,
            "videos_delivered": len(a_jobs),
            "revenue_eur": round(revenue, 2),
            "seller_commission_eur": round(commission, 2),
            "production_cost_eur": round(cost, 2),
            "margin_eur": round(revenue - commission - cost, 2),
        })
    return out


def property_report(jobs):
    """Per-property cost rollup (2026-07-22, backlog item 39) -- the
    concrete link between "cost" and "library": shows total production
    cost across every job linked to a property, useful once a property
    has more than one job (an original video plus a later reshoot, for
    instance). Revenue is NOT attributed per-property -- revenue is a
    per-agency sales-package concept (list_sales()), not tied to
    individual properties -- so this reports cost only, plus which
    agency currently owns the property for display purposes.
    """
    out = []
    for prop in list_properties():
        pid = prop["property_id"]
        p_jobs = [j for j in jobs if j.get("property_id") == pid]
        fins = [job_financials(j) for j in p_jobs]
        cost = sum(f["cost_eur"] for f in fins)
        agency = get_agency(prop.get("agency_id")) if prop.get("agency_id") else None
        out.append({
            "property_id": pid,
            "name": prop["name"],
            "agency_id": prop.get("agency_id"),
            "agency_name": agency["name"] if agency else None,
            "jobs_total": len(p_jobs),
            "production_cost_eur": round(cost, 2),
        })
    return out
