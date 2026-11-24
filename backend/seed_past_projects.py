"""
Seed script — AB Consultants past project mock data.
Run once: python seed_past_projects.py
Safe to re-run (skips if data already exists).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from db import engine, SessionLocal
from models import Base, PastProject

PAST_PROJECTS = [
    # ── VERY SIMILAR TO CURRENT PROJECT (road rehab + stormwater, illustrative drawings, high RFIs) ──
    {
        "project_name": "South Creek Drainage & Road Upgrade",
        "year": 2023,
        "client": "South Creek Municipal Council",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "stormwater", "traffic_management", "utilities"],
        "corridor_length_km": "2.1",
        "drawing_completeness": "illustrative",
        "rfi_count_at_tender": 7,
        "outcome": "won",
        "profit_margin_pct": "18",
        "complexity": "medium",
        "active_road": "yes",
        "notes": "Very similar scope — illustrative drawings, active public road, stormwater with catchpits and manholes. Issued 7 RFIs at tender; client responded to 5. Priced with contingency for unresolved drawings. Delivered on time, 18% margin achieved.",
    },
    # ── SIMILAR DISCIPLINE, COMPLETE DRAWINGS (lower risk) ──
    {
        "project_name": "Riverside Road Rehabilitation Stage 2",
        "year": 2022,
        "client": "Riverside City Council",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "traffic_management", "pedestrian"],
        "corridor_length_km": "3.5",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 3,
        "outcome": "won",
        "profit_margin_pct": "22",
        "complexity": "medium",
        "active_road": "yes",
        "notes": "Longer corridor but complete construction drawings provided. Low RFI count. Strong margin due to well-defined scope. Good reference for road rehab capability.",
    },
    # ── STORMWATER ONLY (partial discipline match) ──
    {
        "project_name": "Greenfield Industrial Stormwater Reticulation",
        "year": 2023,
        "client": "Greenfield Development Corp",
        "project_type": "stormwater",
        "disciplines": ["stormwater", "utilities"],
        "corridor_length_km": "N/A",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 2,
        "outcome": "won",
        "profit_margin_pct": "24",
        "complexity": "low",
        "active_road": "no",
        "notes": "Greenfield site — no active road, stormwater design and construction only. Good stormwater competency evidence but no road rehab component.",
    },
    # ── SIMILAR SCOPE BUT LOST (underbid risk from incomplete drawings) ──
    {
        "project_name": "North Industrial Estate Access Road",
        "year": 2023,
        "client": "North Regional Authority",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "stormwater", "traffic_management"],
        "corridor_length_km": "1.5",
        "drawing_completeness": "partial",
        "rfi_count_at_tender": 8,
        "outcome": "lost",
        "profit_margin_pct": "N/A",
        "complexity": "medium",
        "active_road": "yes",
        "notes": "Lost to lower bid. Competitor likely underbid given 8 unresolved RFIs. Post-tender analysis suggested our pricing was correct — competitor likely issued variations later. Lesson: do not lower price to win on incomplete drawing packages.",
    },
    # ── DECLINED — TOO MANY RFIs, DESIGN RISK TOO HIGH ──
    {
        "project_name": "Bay Road Stormwater Augmentation",
        "year": 2023,
        "client": "Bay City Infrastructure",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "stormwater", "utilities", "traffic_management"],
        "corridor_length_km": "1.0",
        "drawing_completeness": "illustrative",
        "rfi_count_at_tender": 11,
        "outcome": "declined",
        "profit_margin_pct": "N/A",
        "complexity": "high",
        "active_road": "yes",
        "notes": "Declined to submit. 11 HIGH RFIs with no client response within clarification period. Drawings showed no drainage design detail and coordinates were not confirmed. Senior management assessed design risk as unacceptable for a lump-sum price. Correct decision.",
    },
    # ── SIMILAR SCALE, ROAD + PEDESTRIAN + DRAINAGE ──
    {
        "project_name": "City Centre Precinct Streetscape Upgrade",
        "year": 2021,
        "client": "Metro City Council",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "pedestrian", "stormwater", "utilities"],
        "corridor_length_km": "0.8",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 4,
        "outcome": "won",
        "profit_margin_pct": "19",
        "complexity": "medium",
        "active_road": "yes",
        "notes": "CBD streetscape with live traffic — required detailed traffic staging. Complete drawings, manageable RFIs. Good demonstration of multi-discipline delivery.",
    },
    # ── LARGER SCALE, STRONG MARGIN ──
    {
        "project_name": "Clifton Heights Residential Roads & Drainage",
        "year": 2020,
        "client": "Clifton Heights Developer",
        "project_type": "road_rehabilitation",
        "disciplines": ["roadway", "stormwater", "pedestrian"],
        "corridor_length_km": "4.2",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 2,
        "outcome": "won",
        "profit_margin_pct": "21",
        "complexity": "low",
        "active_road": "no",
        "notes": "Greenfield residential roads — no live traffic. Largest corridor in history. Well-defined scope, excellent margin. Demonstrates scale capability but lower risk profile than active-road projects.",
    },
    # ── FOOTPATH + DRAINAGE (partial match) ──
    {
        "project_name": "Parklands Shared Path & Drainage Renewal",
        "year": 2022,
        "client": "Parklands Council",
        "project_type": "pedestrian_drainage",
        "disciplines": ["pedestrian", "stormwater"],
        "corridor_length_km": "1.2",
        "drawing_completeness": "partial",
        "rfi_count_at_tender": 5,
        "outcome": "won",
        "profit_margin_pct": "14",
        "complexity": "low",
        "active_road": "no",
        "notes": "Shared path renewal with minor drainage works. No road pavement or traffic management. Lower margin reflects simpler scope.",
    },
    # ── BRIDGE / STRUCTURAL (different discipline — low match) ──
    {
        "project_name": "Harbor Bridge Inspection & Bearing Replacement",
        "year": 2021,
        "client": "State Roads Authority",
        "project_type": "bridge",
        "disciplines": ["structural", "traffic_management"],
        "corridor_length_km": "N/A",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 1,
        "outcome": "won",
        "profit_margin_pct": "15",
        "complexity": "high",
        "active_road": "yes",
        "notes": "Structural bridge inspection and bearing replacement. Completely different discipline from road rehab / stormwater. Good traffic management record but no civil drainage component. Low relevance to current RFQ.",
    },
    # ── BUILDING (completely different — lowest match) ──
    {
        "project_name": "Heritage Building Facade Restoration",
        "year": 2022,
        "client": "Heritage Trust",
        "project_type": "building",
        "disciplines": ["structural", "architectural"],
        "corridor_length_km": "N/A",
        "drawing_completeness": "complete",
        "rfi_count_at_tender": 2,
        "outcome": "won",
        "profit_margin_pct": "20",
        "complexity": "medium",
        "active_road": "no",
        "notes": "Heritage facade — masonry and structural restoration. No civil infrastructure discipline overlap with road/stormwater RFQs. Included for completeness of firm history.",
    },
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(PastProject).count()
        if existing > 0:
            print(f"past_projects table already has {existing} rows — skipping seed.")
            return

        for data in PAST_PROJECTS:
            db.add(PastProject(**data))
        db.commit()
        print(f"Seeded {len(PAST_PROJECTS)} past projects into past_projects table.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
