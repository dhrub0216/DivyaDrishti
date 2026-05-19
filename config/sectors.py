"""
config/sectors.py — The 12 standard government procurement sectors.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHY WE HAVE SECTORS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Every government tender belongs to a programme area. Different ministries
use different naming conventions for the same type of work — a "road"
might appear as "Infrastructure", "PWD Works", or "Transport" on different
portals. We normalise all of them into 12 standard sectors so the dashboard
can group, filter, and compare spending across the entire country.

SECTOR_DEPARTMENTS: Which government departments typically issue tenders
                    in each sector. Used to:
                    - Auto-classify new tenders by their issuing department
                    - Populate the sidebar "Department" filter
                    - Generate realistic titles in synthetic seed data

SECTOR_COLORS:      One colour per sector for consistent chart colouring.
                    Used by the treemap, heatmap, bubble pack, sankey, and
                    map scatter — so "Health" is always blue, everywhere.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE 12 SECTORS EXPLAINED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Infrastructure     — Roads, bridges, buildings, airports, railways
  Health             — Hospitals, medical equipment, NHM programmes
  Education          — Schools, colleges, IIT/NIT construction
  Agriculture        — Irrigation, storage, ICAR research, PM-KUSUM
  MSME               — Small business support, industrial clusters
  Energy             — Power plants, solar, transmission lines, DISCOMs
  Water & Sanitation — Jal Jeevan Mission, sewage, Swachh Bharat
  Urban Development  — AMRUT, Smart Cities, metro rail, housing
  Rural Development  — PMGSY village roads, PMAY-G, MNREGA works
  Minority Affairs   — MSDP, minority welfare infrastructure
  Social Welfare     — SC/ST schemes, Anganwadi, women & child welfare
  Digital & IT       — BharatNet, data centres, e-governance systems
"""

from typing import Dict, List


# ── Which departments issue tenders in each sector ────────────────────────────
# Classifier (services/classifier.py) matches an incoming tender's department
# name against these lists to assign a sector label.

SECTOR_DEPARTMENTS: Dict[str, List[str]] = {
    "Infrastructure": [
        "NHAI (National Highway Authority)",       # national highways
        "CPWD (Central Public Works Dept)",        # central govt buildings
        "Border Roads Organisation (BRO)",         # border/strategic roads
        "State PWD",                               # state roads & bridges
        "Smart Cities Mission",                    # urban infrastructure
        "Airport Authority of India",              # AAI terminal works
        "Railways Infrastructure Div",             # rail track & stations
        "RRDA (Rural Road Dev Agency)",            # district road upgrades
    ],
    "Health": [
        "National Health Mission (NHM)",           # primary & community health centres
        "Ministry of Health & Family Welfare",     # central health schemes
        "AIIMS (All India Institute of Med Sci)",  # AIIMS campus construction
        "CGHS",                                    # central govt health service
        "Ayushman Bharat - PMJAY",                 # health insurance infra
        "State Health Dept",                       # state hospitals & clinics
        "National AIDS Control Org",               # NACO programme infra
    ],
    "Education": [
        "Samagra Shiksha Abhiyan",                 # school education mission
        "Ministry of Education",                   # central education works
        "UGC (Univ Grants Commission)",            # university infrastructure
        "Navodaya Vidyalaya Samiti",               # residential schools
        "IIT / NIT Infrastructure",                # technical institute campus
        "State Education Dept",                    # state school construction
        "CBSE School Infrastructure",              # CBSE-affiliated schools
    ],
    "Agriculture": [
        "Ministry of Agriculture & Farmers Welfare",
        "ICAR (Research Infrastructure)",          # agricultural research stations
        "FCI (Food Corporation of India)",         # grain storage & silos
        "NABARD Rural Infrastructure",             # agri & rural finance infra
        "State Agriculture Dept",                  # state-level agri works
        "PM-KUSUM Solar Pump Scheme",              # solar pumps for farmers
        "National Horticulture Board",             # horticulture processing
    ],
    "MSME": [
        "Ministry of MSME",
        "NSIC (National Small Industries Corp)",   # MSME support centres
        "SIDBI",                                   # small industry finance infra
        "Khadi & Village Industries Commission",   # KVI cluster development
        "State MSME Dept",
        "MSME Technology Centre",                  # common facility centres
    ],
    "Energy": [
        "NTPC Ltd",                                # thermal & hydro power plants
        "SECI (Solar Energy Corp of India)",       # solar park development
        "Power Grid Corporation",                  # inter-state transmission
        "State DISCOM",                            # last-mile electricity distribution
        "Ministry of New & Renewable Energy",      # wind/solar/hydro schemes
        "Rural Electrification Corp (REC)",        # village electrification
        "BHEL Infrastructure",                     # power equipment manufacture
    ],
    "Water & Sanitation": [
        "Jal Jeevan Mission",                      # tap water to every household
        "Swachh Bharat Mission (Urban)",           # urban sanitation
        "Swachh Bharat Mission (Rural)",           # rural ODF+ programme
        "Central Water Commission",                # dams & river management
        "State Irrigation Dept",                   # canals & irrigation
        "NMCG (Namami Gange)",                     # Ganga rejuvenation
        "National Water Development Agency",       # inter-linking rivers
    ],
    "Urban Development": [
        "AMRUT 2.0",                               # urban water/sewage services
        "PMAY - Urban Housing",                    # affordable urban housing
        "Smart Cities Mission",                    # city-level tech & infra
        "Municipal Corporation",                   # civic body works
        "State Housing Board",                     # state housing projects
        "Metro Rail Corporation",                  # metro construction
        "DUDA (District Urban Dev Authority)",     # district urban works
    ],
    "Rural Development": [
        "PMGSY (Pradhan Mantri Gram Sadak Yojana)",  # rural road connectivity
        "PMAY - Gramin",                             # rural housing
        "MNREGA Infrastructure Works",               # asset creation under MNREGA
        "National Rural Livelihood Mission",          # SHG & livelihood infra
        "State Rural Dev Dept",
        "DRDA (Dist Rural Dev Agency)",              # district-level rural works
    ],
    "Minority Affairs": [
        "Ministry of Minority Affairs",
        "MSDP (Multi-Sector Dev Programme)",       # infrastructure in minority areas
        "Waqf Board Infrastructure",               # waqf property development
        "State Minority Dev Corp",
        "National Minorities Dev & Finance Corp",
    ],
    "Social Welfare": [
        "Ministry of Social Justice & Empowerment",
        "Tribal Affairs Dept",                     # tribal area infrastructure
        "Women & Child Development",               # crèche & shelter homes
        "Anganwadi Infrastructure Programme",      # ICDS centre construction
        "SC/ST Development Corp",                  # welfare schemes
    ],
    "Digital & IT": [
        "MeitY (Ministry of Electronics & IT)",    # digital infrastructure
        "BharatNet Phase-3",                       # optical fibre to villages
        "Common Service Centre (CSC)",             # rural digital kiosks
        "NIC Infrastructure",                      # government data centres
        "State IT Dept",                           # state e-governance
        "CDAC Infrastructure",                     # computing research infra
    ],
}


# ── Chart colours — one per sector, used consistently across all charts ───────
# Chosen to be visually distinct and accessible on light backgrounds.

SECTOR_COLORS: Dict[str, str] = {
    "Infrastructure":     "#E74C3C",   # red     — roads, bridges (dominant, attention-grabbing)
    "Health":             "#3498DB",   # blue    — healthcare (trust, calming)
    "Education":          "#9B59B6",   # purple  — knowledge, wisdom
    "Agriculture":        "#27AE60",   # green   — farming, land
    "MSME":               "#E67E22",   # orange  — enterprise, industry
    "Energy":             "#F1C40F",   # yellow  — power, light
    "Water & Sanitation": "#1ABC9C",   # teal    — water, sanitation
    "Urban Development":  "#2C3E50",   # dark    — city, concrete
    "Rural Development":  "#7F8C8D",   # grey    — earth, rural
    "Minority Affairs":   "#D35400",   # burnt orange — distinctive
    "Social Welfare":     "#C0392B",   # crimson — welfare, care
    "Digital & IT":       "#2980B9",   # steel blue — technology
}
