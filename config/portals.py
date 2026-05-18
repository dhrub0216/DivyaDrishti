"""Portal URL constants for all government procurement portals."""

NIC_PORTALS = {
    # ── Central ─────────────────────────────────────────────────────────────
    "Central (CPPP)":  "https://eprocure.gov.in/eprocure/app",
    # ── States ──────────────────────────────────────────────────────────────
    # Bihar NIC (BSWAN domain is down; EPSV2 portal scraped separately via biharv2 source)
    "Bihar":           "https://biharetenders.gov.in/nicgep/app",
    "Uttar Pradesh":   "https://etender.up.nic.in/nicgep/app",
    "Maharashtra":     "https://mahatenders.gov.in/nicgep/app",
    "Karnataka":       "https://eproc.karnataka.gov.in/app",
    "Rajasthan":       "https://sppp.raj.nic.in/nicgep/app",
    "West Bengal":     "https://wbtenders.gov.in/nicgep/app",
    "Tamil Nadu":      "https://tntenders.gov.in/nicgep/app",
    "Gujarat":         "https://nprocure.com/nicgep/app",
    "Andhra Pradesh":  "https://tender.apeprocurement.gov.in/nicgep/app",
    "Telangana":       "https://tender.telangana.gov.in/nicgep/app",
    "Madhya Pradesh":  "https://mptenders.gov.in/nicgep/app",
    "Odisha":          "https://tendersodisha.gov.in/nicgep/app",
    "Punjab":          "https://eproc.punjab.gov.in/EPROC/app",
    "Haryana":         "https://etenders.hry.nic.in/nicgep/app",
    "Delhi":           "https://govtprocurement.delhi.gov.in/nicgep/app",
    "Assam":           "https://assamtenders.gov.in/nicgep/app",
    "Chhattisgarh":    "https://eproc.cgstate.gov.in/nicgep/app",
    "Himachal Pradesh":"https://hptenders.gov.in/nicgep/app",
    "Jharkhand":       "https://jharkhandtenders.gov.in/nicgep/app",
    "Jammu & Kashmir": "https://jktenders.gov.in/nicgep/app",
    "Kerala":          "https://etenders.kerala.gov.in/nicgep/app",
    "Manipur":         "https://manipurtenders.gov.in/nicgep/app",
    "Meghalaya":       "https://meghalayatenders.gov.in/nicgep/app",
    "Mizoram":         "https://mizoramtenders.gov.in/nicgep/app",
    "Nagaland":        "https://nagalandtenders.gov.in/nicgep/app",
    "Sikkim":          "https://sikkim.gov.in/e-tender/nicgep/app",
    "Tripura":         "https://tripuratenders.gov.in/nicgep/app",
    "Uttarakhand":     "https://uktenders.gov.in/nicgep/app",
    "Arunachal Pradesh":"https://arunachaltenders.gov.in/nicgep/app",
    # ── Union Territories ───────────────────────────────────────────────────
    "Puducherry":      "https://pudutenders.gov.in/nicgep/app",
    "Ladakh":          "https://tenders.ladakh.gov.in/nicgep/app",
    # Chandigarh uses Central CPPP — no separate NIC portal
    # Goa uses Enivida system (non-NIC) — not compatible with this scraper
}

GEM_URL           = "https://bidplus.gem.gov.in/all-bids"
DATAGOV_BASE      = "https://api.data.gov.in"
PMGSY_URL         = "https://www.pmgsytenders.gov.in/nicgep/app"
CGSTATE_CHEPS_URL = "https://eproc.cgstate.gov.in/CHEPS/business/getOpenRfqListAction.do"
BIHAR_EPSV2_BASE  = "https://eproc2.bihar.gov.in/EPSV2Web/openarea/tenderListingPage.action"

# ── Uttar Pradesh custom portals (not NIC GePNIC) ──────────────────────────
UPJN_BASE    = "https://jn.upsdc.gov.in"       # UP Jal Nigam — 7,500+ tenders, district-level
UPJN_LIST    = f"{UPJN_BASE}/en/tenders"
UPEIDA_BASE  = "https://upeida.up.gov.in"      # Expressways dev authority
UPEIDA_LIST  = f"{UPEIDA_BASE}/en/archivetenders"
UPSBC_LIST   = "https://bridgecorporationltd.com/tender.php"  # State Bridge Corp
PVVNL_LIST   = "https://pvvnl.org/Tenders-Notice"            # UP Western power distribution
MVVNL_BASE   = "https://mvvnl.in/en/tenders"                 # UP Central/Lucknow power distribution
ETENDER_UP   = "https://etender.up.nic.in/nicgep/app"        # UP state e-procurement (all depts)
UPMSC_LIST   = "https://upmsc.in/"                           # UP Medical Supplies Corp (Health)

# GePNIC NIC portals — identical structure, different base URLs
GEPNIC_STATES: dict = {
    # Already scraped
    "Uttar Pradesh":         "https://etender.up.nic.in/nicgep/app",
    "Rajasthan":             "https://eproc.rajasthan.gov.in/nicgep/app",
    "Madhya Pradesh":        "https://mptenders.gov.in/nicgep/app",
    "Maharashtra":           "https://mahatenders.gov.in/nicgep/app",
    "Odisha":                "https://tendersodisha.gov.in/nicgep/app",
    "Haryana":               "https://etenders.hry.nic.in/nicgep/app",
    "West Bengal":           "https://wbtenders.gov.in/nicgep/app",
    "Tamil Nadu":            "https://tntenders.gov.in/nicgep/app",
    "Central (CPPP)":        "https://eprocure.gov.in/eprocure/app",
    # North-east states
    "Arunachal Pradesh":     "https://arunachaltenders.gov.in/nicgep/app",
    "Assam":                 "https://www.assamtenders.gov.in/nicgep/app",
    "Manipur":               "https://manipurtenders.gov.in/nicgep/app",
    "Meghalaya":             "https://meghalayatenders.gov.in/nicgep/app",
    "Mizoram":               "https://mizoramtenders.gov.in/nicgep/app",
    "Nagaland":              "https://nagalandtenders.gov.in/nicgep/app",
    "Tripura":               "https://tripuratenders.gov.in/nicgep/app",
    # Other states
    "Goa":                   "https://eprocure.goa.gov.in/nicgep/app",
    "Himachal Pradesh":      "https://hptenders.gov.in/nicgep/app",
    "Jharkhand":             "https://jharkhandtenders.gov.in/nicgep/app",
    "Kerala":                "https://www.etenders.kerala.gov.in/nicgep/app",
    "Punjab":                "https://eproc.punjab.gov.in/nicgep/app",
    # Union Territories
    "Delhi":                 "https://govtprocurement.delhi.gov.in/nicgep/app",
    "Jammu & Kashmir":       "https://jktenders.gov.in/nicgep/app",
    "Chandigarh":            "https://etenders.chd.nic.in/nicgep/app",
    "Andaman & Nicobar":     "https://eprocure.andamannicobar.gov.in/nicgep/app",
    "Dadra & Nagar Haveli":  "https://dnhtenders.gov.in/nicgep/app",
    "Daman & Diu":           "https://ddtenders.gov.in/nicgep/app",
    "Puducherry":            "https://pudutenders.gov.in/nicgep/app",
    "Lakshadweep":           "https://tendersutl.gov.in/nicgep/app",
    "Uttarakhand":           "https://uktenders.gov.in/nicgep/app",
    "Sikkim":                "https://sikkimtender.gov.in/nicgep/app",
}

# data.gov.in dataset resource IDs for procurement/tender data
DATAGOV_RESOURCES = [
    # Central procurement notices (update IDs from data.gov.in as new datasets are published)
    "6176ee09-3d56-4a3b-8115-21841dde0418",  # NIC tender notices
    "9dc9c5c3-4b5e-4b5e-8b5e-4b5e8b5e4b5e",  # placeholder — search for current IDs
]

DATAGOV_DATASETS = {
    "central_procurement": "6176ee09-3d56-4a3b-8115-21841dde0418",
    "niti_expenditure":    "c2948e4d-2c3e-4b5e-8b5e-4b5e8b5e4b5e",
}
