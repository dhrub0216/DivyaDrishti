"""
pipeline.py — Data Engineering Layer
Pan-India Government Tender Tracker v3.0
"""

import logging
import json
import math
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ── Geometry helpers: stable hash + linear/point classifier ──────────────

def _stable_hash(s: str) -> int:
    """Process-stable hash (Python's built-in hash() is randomised per-run)."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


LINEAR_KEYWORDS = [
    # Roads
    "road", "highway", "expressway", "bypass", "four-lan", "bituminous", "resurfac",
    "widening", "ring road", "service road", "pmgsy",
    # Bridges
    "bridge", "flyover", "over-bridge", "over bridge", " rob ", "underpass",
    # Linear utilities
    "pipeline", "canal", "drain", "drainage", "sewage line", "sewer",
    "fibre", "ofc", "bharatnet",
    "transmission line", "power line", "11kv", "33kv",
    # Linear transport
    "metro corridor", "railway track", "track doubling",
]


def is_linear_title(title: str) -> bool:
    """True if the tender title describes linear infrastructure (line on map)."""
    if not title:
        return False
    t = title.lower()
    return any(kw in t for kw in LINEAR_KEYWORDS)


def linear_endpoints(
    start_lat: float, start_lon: float, tender_id: str,
    min_km: float = 1.5, max_km: float = 8.0,
) -> Tuple[float, float]:
    """
    Deterministically derive a line endpoint from a start coord + tender_id.
    Same tender_id always produces the same endpoint across runs.
    """
    h = _stable_hash(tender_id)
    angle = (h % 360) * math.pi / 180
    length_km = min_km + ((h >> 8) & 0xFF) / 255.0 * (max_km - min_km)
    lat_off = (length_km / 111.0) * math.sin(angle)
    lon_factor = max(0.5, math.cos(math.radians(start_lat)))
    lon_off = (length_km / (111.0 * lon_factor)) * math.cos(angle)
    return round(start_lat + lat_off, 6), round(start_lon + lon_off, 6)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tender_pipeline")

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

SECTOR_DEPARTMENTS: Dict[str, List[str]] = {
    "Infrastructure": [
        "NHAI (National Highway Authority)",
        "CPWD (Central Public Works Dept)",
        "Border Roads Organisation (BRO)",
        "State PWD",
        "Smart Cities Mission",
        "Airport Authority of India",
        "Railways Infrastructure Div",
        "RRDA (Rural Road Dev Agency)",
    ],
    "Health": [
        "National Health Mission (NHM)",
        "Ministry of Health & Family Welfare",
        "AIIMS (All India Institute of Med Sci)",
        "CGHS",
        "Ayushman Bharat - PMJAY",
        "State Health Dept",
        "National AIDS Control Org",
    ],
    "Education": [
        "Samagra Shiksha Abhiyan",
        "Ministry of Education",
        "UGC (Univ Grants Commission)",
        "Navodaya Vidyalaya Samiti",
        "IIT / NIT Infrastructure",
        "State Education Dept",
        "CBSE School Infrastructure",
    ],
    "Agriculture": [
        "Ministry of Agriculture & Farmers Welfare",
        "ICAR (Research Infrastructure)",
        "FCI (Food Corporation of India)",
        "NABARD Rural Infrastructure",
        "State Agriculture Dept",
        "PM-KUSUM Solar Pump Scheme",
        "National Horticulture Board",
    ],
    "MSME": [
        "Ministry of MSME",
        "NSIC (National Small Industries Corp)",
        "SIDBI",
        "Khadi & Village Industries Commission",
        "State MSME Dept",
        "MSME Technology Centre",
    ],
    "Energy": [
        "NTPC Ltd",
        "SECI (Solar Energy Corp of India)",
        "Power Grid Corporation",
        "State DISCOM",
        "Ministry of New & Renewable Energy",
        "Rural Electrification Corp (REC)",
        "BHEL Infrastructure",
    ],
    "Water & Sanitation": [
        "Jal Jeevan Mission",
        "Swachh Bharat Mission (Urban)",
        "Swachh Bharat Mission (Rural)",
        "Central Water Commission",
        "State Irrigation Dept",
        "NMCG (Namami Gange)",
        "National Water Development Agency",
    ],
    "Urban Development": [
        "AMRUT 2.0",
        "PMAY - Urban Housing",
        "Smart Cities Mission",
        "Municipal Corporation",
        "State Housing Board",
        "Metro Rail Corporation",
        "DUDA (District Urban Dev Authority)",
    ],
    "Rural Development": [
        "PMGSY (Pradhan Mantri Gram Sadak Yojana)",
        "PMAY - Gramin",
        "MNREGA Infrastructure Works",
        "National Rural Livelihood Mission",
        "State Rural Dev Dept",
        "DRDA (Dist Rural Dev Agency)",
    ],
    "Minority Affairs": [
        "Ministry of Minority Affairs",
        "MSDP (Multi-Sector Dev Programme)",
        "Waqf Board Infrastructure",
        "State Minority Dev Corp",
        "National Minorities Dev & Finance Corp",
    ],
    "Social Welfare": [
        "Ministry of Social Justice & Empowerment",
        "Tribal Affairs Dept",
        "Women & Child Development",
        "Anganwadi Infrastructure Programme",
        "SC/ST Development Corp",
    ],
    "Digital & IT": [
        "MeitY (Ministry of Electronics & IT)",
        "BharatNet Phase-3",
        "Common Service Centre (CSC)",
        "NIC Infrastructure",
        "State IT Dept",
        "CDAC Infrastructure",
    ],
}

SECTOR_COLORS: Dict[str, str] = {
    "Infrastructure":     "#E74C3C",
    "Health":             "#3498DB",
    "Education":          "#9B59B6",
    "Agriculture":        "#27AE60",
    "MSME":               "#E67E22",
    "Energy":             "#F1C40F",
    "Water & Sanitation": "#1ABC9C",
    "Urban Development":  "#2C3E50",
    "Rural Development":  "#7F8C8D",
    "Minority Affairs":   "#D35400",
    "Social Welfare":     "#C0392B",
    "Digital & IT":       "#2980B9",
}

# ---------------------------------------------------------------------------
# STATES_DATA
# ---------------------------------------------------------------------------

STATES_DATA: Dict[str, Dict[str, List[str]]] = {
    "Uttar Pradesh": {
        "Lucknow":    ["Sarojini Nagar", "Alambagh", "Chinhat", "Malihabad"],
        "Agra":       ["Tajganj", "Fatehabad", "Kiraoli", "Bah"],
        "Varanasi":   ["Kashi Vidyapeeth", "Arajiline", "Rohania", "Chiraigaon"],
        "Kanpur":     ["Nawabganj", "Kalyanpur", "Bilhaur", "Ghatampur"],
        "Prayagraj":  ["Phulpur", "Meja", "Soraon", "Handia"],
        "Gorakhpur":  ["Sahjanwa", "Campierganj", "Gola", "Khajni"],
    },
    "Maharashtra": {
        "Mumbai":     ["Worli", "Andheri East", "Borivali", "Kurla"],
        "Pune":       ["Hadapsar", "Kothrud", "Pimpri", "Bhor"],
        "Nagpur":     ["Butibori", "Kamptee", "Hingna", "Ramtek"],
        "Nashik":     ["Panchavati", "Satpur", "Igatpuri", "Sinnar"],
        "Aurangabad": ["Waluj", "Garkheda", "Phulambri", "Kannad"],
        "Solapur":    ["South Solapur", "Akkalkot", "Pandharpur", "Mohol"],
    },
    "Rajasthan": {
        "Jaipur":  ["Sanganer", "Amber", "Chaksu", "Jamwa Ramgarh"],
        "Jodhpur": ["Bilara", "Bhopalgarh", "Luni", "Mandore"],
        "Udaipur": ["Girwa", "Vallabhnagar", "Kherwara", "Salumbar"],
        "Kota":    ["Ladpura", "Ramganj Mandi", "Pipalda", "Baran"],
        "Ajmer":   ["Pisangan", "Masuda", "Kekri", "Nasirabad"],
        "Bikaner": ["Lunkaransar", "Kolayat", "Nokha", "Bajju"],
    },
    "Madhya Pradesh": {
        "Bhopal":   ["Huzur", "Berasia", "Phanda", "Sehore"],
        "Indore":   ["Rajendra Nagar", "Sanwer", "Depalpur", "Mhow"],
        "Jabalpur": ["Panagar", "Shahpura", "Sihora", "Kundam"],
        "Gwalior":  ["Morar", "Dabra", "Bhitarwar", "Murar"],
        "Rewa":     ["Rewa Urban", "Mauganj", "Sirmaur", "Teonthar"],
    },
    "Bihar": {
        "Patna":       ["Patliputra", "Phulwari Sharif", "Danapur", "Masaurhi"],
        "Samastipur":  ["Kalyanpur", "Rosera", "Patori", "Dalsinghsarai", "Warisnagar", "Singhia"],
        "Muzaffarpur": ["Motipur", "Kanti", "Sakra", "Aurai"],
        "Gaya":        ["Bodhgaya", "Sherghati", "Manpur", "Amas"],
        "Bhagalpur":   ["Naugachia", "Sultanganj", "Kahalgaon", "Banka"],
        "Darbhanga":   ["Bahera", "Keoti", "Jale", "Singhwara"],
    },
    "Karnataka": {
        "Bangalore Urban": ["Whitefield", "Yelahanka", "Bommanahalli", "Dasarahalli"],
        "Mysore":          ["Hunsur", "Krishnarajanagara", "Nanjangud", "Periyapatna"],
        "Hubli-Dharwad":   ["Dharwad", "Hubli", "Kundgol", "Kalghatgi"],
        "Belagavi":        ["Belagavi City", "Chikkodi", "Gokak", "Hukkeri"],
        "Mangaluru":       ["Bantwal", "Belthangady", "Puttur", "Sullia"],
    },
    "Tamil Nadu": {
        "Chennai":     ["Sholinganallur", "Ambattur", "Thiruvottiyur", "Alandur"],
        "Coimbatore":  ["Peelamedu", "Pollachi", "Annur", "Kinathukadavu"],
        "Madurai":     ["Anna Nagar", "Melur", "Thiruparankundram", "Usilampatti"],
        "Salem":       ["Edappadi", "Sankari", "Attur", "Mettur"],
        "Tirunelveli": ["Palayamkottai", "Ambasamudram", "Nanguneri", "Radhapuram"],
    },
    "West Bengal": {
        "Kolkata":     ["Salt Lake", "Jadavpur", "Behala", "Dum Dum"],
        "Howrah":      ["Shibpur", "Uluberia", "Amta", "Bagnan"],
        "Burdwan":     ["Durgapur", "Asansol", "Kalna", "Katwa"],
        "Darjeeling":  ["Siliguri", "Kurseong", "Kalimpong", "Mirik"],
        "Murshidabad": ["Berhampore", "Lalbagh", "Jangipur", "Kandi"],
    },
    "Gujarat": {
        "Ahmedabad":   ["Naranpura", "Bopal", "Chandkheda", "Nikol"],
        "Surat":       ["Vesu", "Adajan", "Varachha", "Olpad"],
        "Rajkot":      ["Aji Dam", "Gondal", "Jetpur", "Upleta"],
        "Vadodara":    ["Ajwa", "Waghodiya", "Padra", "Savli"],
        "Gandhinagar": ["Mansa", "Dehgam", "Kalol", "Gandhinagar Urban"],
    },
    "Andhra Pradesh": {
        "Visakhapatnam": ["Gajuwaka", "Bheemunipatnam", "Padmanabham", "Anakapalle"],
        "Guntur":        ["Amaravati", "Tenali", "Narasaraopet", "Sattenapalle"],
        "Kurnool":       ["Nandyal", "Adoni", "Yemmiganur", "Alur"],
        "Chittoor":      ["Renigunta", "Tirupati Urban", "Madanapalle", "Palamaner"],
    },
    "Telangana": {
        "Hyderabad": ["Patancheru", "LB Nagar", "Secunderabad", "Kukatpally"],
        "Warangal":  ["Kazipet", "Hanamkonda", "Narsampet", "Mahabubabad"],
        "Khammam":   ["Khammam Urban", "Kothagudem", "Yellandu", "Bhadrachalam"],
        "Nizamabad": ["Dichpally", "Bodhan", "Armur", "Banswada"],
    },
    "Odisha": {
        "Khurda":     ["Bhubaneswar", "Jatni", "Balianta", "Chilika"],
        "Cuttack":    ["Cuttack City", "Athagarh", "Banki", "Tigiria"],
        "Sundargarh": ["Rourkela", "Bonai", "Rajgangpur", "Hemgir"],
        "Puri":       ["Puri Urban", "Konark", "Pipili", "Astaranga"],
    },
    "Punjab": {
        "Ludhiana":  ["Sahnewal", "Raikot", "Samrala", "Khanna"],
        "Amritsar":  ["Golden Temple", "Ajnala", "Baba Bakala", "Lopoke"],
        "Patiala":   ["Urban Estate", "Rajpura", "Nabha", "Samana"],
        "Jalandhar": ["Nakodar", "Phillaur", "Shahkot", "Bhogpur"],
    },
    "Haryana": {
        "Gurugram":  ["DLF Phase 1", "Sohna", "Pataudi", "Farrukhnagar"],
        "Faridabad": ["Sector 21C", "Ballabhgarh", "Palwal", "Hodal"],
        "Hisar":     ["Hisar Urban", "Hansi", "Barwala", "Fatehabad"],
        "Ambala":    ["Ambala City", "Naraingarh", "Shahzadpur", "Mulana"],
    },
    "Delhi": {
        "South Delhi": ["Safdarjung", "Vasant Kunj", "Mehrauli", "Hauz Khas"],
        "North Delhi": ["Civil Lines", "Alipur", "Burari", "Timarpur"],
        "East Delhi":  ["Mayur Vihar", "Laxmi Nagar", "Shahdara", "Gandhi Nagar"],
        "West Delhi":  ["Dwarka Sector 21", "Palam", "Janakpuri", "Uttam Nagar"],
    },
    "Jharkhand": {
        "Ranchi":         ["Namkum", "Ormanjhi", "Kanke", "Ratu"],
        "Dhanbad":        ["Jharia", "Sindri", "Nirsa", "Baghmara"],
        "East Singhbhum": ["Jugsalai", "Boram", "Potka", "Baharagora"],
        "Hazaribagh":     ["Barhi", "Churchu", "Padma", "Chalkusa"],
    },
    "Assam": {
        "Kamrup Metro": ["Dispur", "Guwahati East", "Jalukbari", "Hengrabari"],
        "Dibrugarh":    ["Dibrugarh East", "Duliajan", "Lahowal", "Khowang"],
        "Cachar":       ["Silchar", "Sonai", "Udharbond", "Lakhipur"],
        "Nagaon":       ["Nagaon Town", "Raha", "Lumding", "Hojai"],
    },
    "Chhattisgarh": {
        "Raipur":   ["Avanti Vihar", "Abhanpur", "Arang", "Tilda"],
        "Bilaspur": ["Masturi", "Takhatpur", "Mungeli", "Lormi"],
        "Durg":     ["Bhilai", "Patan", "Berla", "Durg Urban"],
        "Bastar":   ["Jagdalpur", "Kondagaon", "Bijapur", "Narayanpur"],
    },
    "Himachal Pradesh": {
        "Shimla": ["Mashobra", "Chopal", "Rampur", "Rohru"],
        "Kullu":  ["Manali", "Banjar", "Ani", "Nirmand"],
        "Kangra": ["Dharamshala", "Nurpur", "Palampur", "Dehra"],
    },
    "Uttarakhand": {
        "Dehradun":    ["Raipur", "Vikasnagar", "Chakrata", "Tyuni"],
        "Haridwar":    ["Har ki Pauri", "Roorkee", "Manglaur", "Laksar"],
        "Rudraprayag": ["Ukhimath", "Augustmuni", "Jakholi", "Kedarnath"],
        "Nainital":    ["Haldwani", "Ramnagar", "Bhimtal", "Okhalkanda"],
    },
    "Kerala": {
        "Ernakulam":          ["Fort Kochi", "Aluva", "Muvattupuzha", "Kothamangalam"],
        "Thiruvananthapuram": ["Kazhakuttam", "Varkala", "Attingal", "Nedumangad"],
        "Kozhikode":          ["Beypore", "Vadakara", "Koyilandy", "Balussery"],
        "Thrissur":           ["Thrissur Urban", "Chalakudy", "Kodungallur", "Chavakkad"],
    },
    "Goa": {
        "North Goa": ["Panaji", "Mapusa", "Pernem", "Bicholim"],
        "South Goa": ["Margao", "Vasco", "Ponda", "Sanguem"],
    },
    "Jammu & Kashmir": {
        "Jammu":    ["Bhalwal", "Akhnoor", "Nagrota", "Marh"],
        "Srinagar": ["Lal Chowk", "Hazratbal", "Shalteng", "Pantha Chowk"],
        "Anantnag": ["Pahalgam", "Kokernag", "Dooru", "Bijbehara"],
        "Baramulla": ["Sopore", "Pattan", "Uri", "Rafiabad"],
    },
    "Tripura": {
        "West Tripura": ["Agartala", "Majlishpur", "Mandai", "Hezamara"],
        "Gomati":       ["Udaipur", "Amarpur", "Karbook", "Kakraban"],
    },
    "Meghalaya": {
        "East Khasi Hills": ["Shillong", "Mawkyrwat", "Pynursla", "Mairang"],
        "Ri Bhoi":          ["Nongpoh", "Umsning", "Bhoirymbong", "Jirang"],
    },
}

# ---------------------------------------------------------------------------
# STATE_CENTERS
# ---------------------------------------------------------------------------

STATE_CENTERS: Dict[str, Dict[str, float]] = {
    "Uttar Pradesh":     {"lat": 26.85,  "lon": 80.91,  "zoom": 6},
    "Maharashtra":       {"lat": 19.75,  "lon": 75.71,  "zoom": 6},
    "Rajasthan":         {"lat": 27.02,  "lon": 74.22,  "zoom": 6},
    "Madhya Pradesh":    {"lat": 22.97,  "lon": 78.65,  "zoom": 6},
    "Bihar":             {"lat": 25.09,  "lon": 85.31,  "zoom": 7},
    "Karnataka":         {"lat": 15.31,  "lon": 75.71,  "zoom": 6},
    "Tamil Nadu":        {"lat": 11.12,  "lon": 78.66,  "zoom": 6},
    "West Bengal":       {"lat": 22.98,  "lon": 87.85,  "zoom": 7},
    "Gujarat":           {"lat": 22.26,  "lon": 71.19,  "zoom": 6},
    "Andhra Pradesh":    {"lat": 15.91,  "lon": 79.74,  "zoom": 6},
    "Telangana":         {"lat": 17.12,  "lon": 79.02,  "zoom": 7},
    "Odisha":            {"lat": 20.94,  "lon": 84.80,  "zoom": 7},
    "Punjab":            {"lat": 31.15,  "lon": 75.34,  "zoom": 7},
    "Haryana":           {"lat": 29.06,  "lon": 76.08,  "zoom": 7},
    "Delhi":             {"lat": 28.66,  "lon": 77.21,  "zoom": 10},
    "Jharkhand":         {"lat": 23.61,  "lon": 85.27,  "zoom": 7},
    "Assam":             {"lat": 26.20,  "lon": 92.94,  "zoom": 7},
    "Chhattisgarh":      {"lat": 21.27,  "lon": 81.86,  "zoom": 7},
    "Himachal Pradesh":  {"lat": 31.10,  "lon": 77.17,  "zoom": 7},
    "Uttarakhand":       {"lat": 30.07,  "lon": 79.07,  "zoom": 7},
    "Kerala":            {"lat": 10.85,  "lon": 76.27,  "zoom": 7},
    "Goa":               {"lat": 15.30,  "lon": 74.12,  "zoom": 9},
    "Jammu & Kashmir":   {"lat": 33.73,  "lon": 76.92,  "zoom": 7},
    "Tripura":           {"lat": 23.94,  "lon": 91.99,  "zoom": 8},
    "Meghalaya":         {"lat": 25.47,  "lon": 91.37,  "zoom": 8},
}

# ---------------------------------------------------------------------------
# DISTRICT & BLOCK COORDINATES — real lat/lon for precise placement
# ---------------------------------------------------------------------------

DISTRICT_COORDINATES: Dict[str, Dict[str, Dict[str, float]]] = {
    "Uttar Pradesh": {
        "Lucknow":   {"lat": 26.8467, "lon": 80.9462},
        "Agra":      {"lat": 27.1767, "lon": 78.0081},
        "Varanasi":  {"lat": 25.3176, "lon": 82.9739},
        "Kanpur":    {"lat": 26.4499, "lon": 80.3319},
        "Prayagraj": {"lat": 25.4358, "lon": 81.8463},
        "Gorakhpur": {"lat": 26.7606, "lon": 83.3732},
    },
    "Maharashtra": {
        "Mumbai":     {"lat": 19.0760, "lon": 72.8777},
        "Pune":       {"lat": 18.5204, "lon": 73.8567},
        "Nagpur":     {"lat": 21.1458, "lon": 79.0882},
        "Nashik":     {"lat": 20.0060, "lon": 73.7908},
        "Aurangabad": {"lat": 19.8762, "lon": 75.3433},
        "Solapur":    {"lat": 17.6599, "lon": 75.9064},
    },
    "Rajasthan": {
        "Jaipur":  {"lat": 26.9124, "lon": 75.7873},
        "Jodhpur": {"lat": 26.2389, "lon": 73.0243},
        "Udaipur": {"lat": 24.5854, "lon": 73.7125},
        "Kota":    {"lat": 25.2138, "lon": 75.8648},
        "Ajmer":   {"lat": 26.4499, "lon": 74.6399},
        "Bikaner": {"lat": 28.0229, "lon": 73.3119},
    },
    "Madhya Pradesh": {
        "Bhopal":   {"lat": 23.2599, "lon": 77.4126},
        "Indore":   {"lat": 22.7196, "lon": 75.8577},
        "Jabalpur": {"lat": 23.1815, "lon": 79.9864},
        "Gwalior":  {"lat": 26.2183, "lon": 78.1828},
        "Rewa":     {"lat": 24.5325, "lon": 81.3023},
    },
    "Bihar": {
        "Patna":       {"lat": 25.5941, "lon": 85.1376},
        "Samastipur":  {"lat": 25.8624, "lon": 85.7810},
        "Muzaffarpur": {"lat": 26.1197, "lon": 85.3910},
        "Gaya":        {"lat": 24.7960, "lon": 84.9994},
        "Bhagalpur":   {"lat": 25.2425, "lon": 86.9842},
        "Darbhanga":   {"lat": 26.1542, "lon": 85.8918},
    },
    "Karnataka": {
        "Bangalore Urban": {"lat": 12.9716, "lon": 77.5946},
        "Mysore":          {"lat": 12.2958, "lon": 76.6394},
        "Hubli-Dharwad":   {"lat": 15.3647, "lon": 75.1240},
        "Belagavi":        {"lat": 15.8497, "lon": 74.4977},
        "Mangaluru":       {"lat": 12.9141, "lon": 74.8560},
    },
    "Tamil Nadu": {
        "Chennai":     {"lat": 13.0827, "lon": 80.2707},
        "Coimbatore":  {"lat": 11.0168, "lon": 76.9558},
        "Madurai":     {"lat":  9.9252, "lon": 78.1198},
        "Salem":       {"lat": 11.6643, "lon": 78.1460},
        "Tirunelveli": {"lat":  8.7139, "lon": 77.7567},
    },
    "West Bengal": {
        "Kolkata":     {"lat": 22.5726, "lon": 88.3639},
        "Howrah":      {"lat": 22.5840, "lon": 88.3423},
        "Burdwan":     {"lat": 23.2324, "lon": 87.8615},
        "Darjeeling":  {"lat": 27.0410, "lon": 88.2663},
        "Murshidabad": {"lat": 24.1830, "lon": 88.2710},
    },
    "Gujarat": {
        "Ahmedabad":   {"lat": 23.0225, "lon": 72.5714},
        "Surat":       {"lat": 21.1702, "lon": 72.8311},
        "Rajkot":      {"lat": 22.3039, "lon": 70.8022},
        "Vadodara":    {"lat": 22.3072, "lon": 73.1812},
        "Gandhinagar": {"lat": 23.2156, "lon": 72.6369},
    },
    "Andhra Pradesh": {
        "Visakhapatnam": {"lat": 17.6868, "lon": 83.2185},
        "Guntur":        {"lat": 16.3067, "lon": 80.4365},
        "Kurnool":       {"lat": 15.8281, "lon": 78.0373},
        "Chittoor":      {"lat": 13.2172, "lon": 79.1003},
    },
    "Telangana": {
        "Hyderabad": {"lat": 17.3850, "lon": 78.4867},
        "Warangal":  {"lat": 17.9784, "lon": 79.5941},
        "Khammam":   {"lat": 17.2473, "lon": 80.1514},
        "Nizamabad": {"lat": 18.6725, "lon": 78.0941},
    },
    "Odisha": {
        "Khurda":     {"lat": 20.1812, "lon": 85.6195},
        "Cuttack":    {"lat": 20.4625, "lon": 85.8830},
        "Sundargarh": {"lat": 22.1217, "lon": 84.0297},
        "Puri":       {"lat": 19.8135, "lon": 85.8312},
    },
    "Punjab": {
        "Ludhiana":  {"lat": 30.9010, "lon": 75.8573},
        "Amritsar":  {"lat": 31.6340, "lon": 74.8723},
        "Patiala":   {"lat": 30.3398, "lon": 76.3869},
        "Jalandhar": {"lat": 31.3260, "lon": 75.5762},
    },
    "Haryana": {
        "Gurugram":  {"lat": 28.4595, "lon": 77.0266},
        "Faridabad": {"lat": 28.4089, "lon": 77.3178},
        "Hisar":     {"lat": 29.1492, "lon": 75.7217},
        "Ambala":    {"lat": 30.3782, "lon": 76.7767},
    },
    "Delhi": {
        "South Delhi": {"lat": 28.5355, "lon": 77.2390},
        "North Delhi": {"lat": 28.7041, "lon": 77.2025},
        "East Delhi":  {"lat": 28.6358, "lon": 77.2965},
        "West Delhi":  {"lat": 28.6663, "lon": 77.0667},
    },
    "Jharkhand": {
        "Ranchi":          {"lat": 23.3441, "lon": 85.3096},
        "Dhanbad":         {"lat": 23.7957, "lon": 86.4304},
        "East Singhbhum":  {"lat": 22.8046, "lon": 86.2029},
        "Hazaribagh":      {"lat": 23.9925, "lon": 85.3637},
    },
    "Assam": {
        "Kamrup Metro": {"lat": 26.1445, "lon": 91.7362},
        "Dibrugarh":    {"lat": 27.4728, "lon": 94.9120},
        "Cachar":       {"lat": 24.8333, "lon": 92.7789},
        "Nagaon":       {"lat": 26.3460, "lon": 92.6837},
    },
    "Chhattisgarh": {
        "Raipur":   {"lat": 21.2514, "lon": 81.6296},
        "Bilaspur": {"lat": 22.0796, "lon": 82.1391},
        "Durg":     {"lat": 21.1898, "lon": 81.2849},
        "Bastar":   {"lat": 19.0748, "lon": 82.0144},
    },
    "Himachal Pradesh": {
        "Shimla": {"lat": 31.1048, "lon": 77.1734},
        "Kullu":  {"lat": 31.9580, "lon": 77.1095},
        "Kangra": {"lat": 32.0998, "lon": 76.2691},
    },
    "Uttarakhand": {
        "Dehradun":     {"lat": 30.3165, "lon": 78.0322},
        "Haridwar":     {"lat": 29.9457, "lon": 78.1642},
        "Rudraprayag":  {"lat": 30.2849, "lon": 78.9810},
        "Nainital":     {"lat": 29.3919, "lon": 79.4542},
    },
    "Kerala": {
        "Ernakulam":          {"lat":  9.9816, "lon": 76.2999},
        "Thiruvananthapuram": {"lat":  8.5241, "lon": 76.9366},
        "Kozhikode":          {"lat": 11.2588, "lon": 75.7804},
        "Thrissur":           {"lat": 10.5276, "lon": 76.2144},
    },
    "Goa": {
        "North Goa": {"lat": 15.4909, "lon": 73.8278},
        "South Goa": {"lat": 15.2993, "lon": 74.1240},
    },
    "Jammu & Kashmir": {
        "Jammu":     {"lat": 32.7266, "lon": 74.8570},
        "Srinagar":  {"lat": 34.0837, "lon": 74.7973},
        "Anantnag":  {"lat": 33.7311, "lon": 75.1487},
        "Baramulla": {"lat": 34.2014, "lon": 74.3436},
    },
    "Tripura": {
        "West Tripura": {"lat": 23.8315, "lon": 91.2868},
        "Gomati":       {"lat": 23.5380, "lon": 91.4843},
    },
    "Meghalaya": {
        "East Khasi Hills": {"lat": 25.5788, "lon": 91.8933},
        "Ri Bhoi":          {"lat": 25.9067, "lon": 91.8754},
    },
}

# Block-level real coordinates (from earlier OSM/Nominatim geocoding).
# Use these for precise positioning within Samastipur district.
BLOCK_COORDINATES: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {
    "Bihar": {
        "Samastipur": {
            "Kalyanpur":        {"lat": 25.9797, "lon": 85.7964},
            "Rosera":           {"lat": 25.7798, "lon": 86.0425},
            "Patori":           {"lat": 25.9300, "lon": 85.8600},
            "Dalsinghsarai":    {"lat": 25.6727, "lon": 85.8124},
            "Warisnagar":       {"lat": 25.9178, "lon": 85.8668},
            "Singhia":          {"lat": 25.8276, "lon": 86.1757},
        },
    },
}


def resolve_coords(state: str, district: str, block: str, rng: np.random.Generator) -> tuple:
    """
    Place a tender at the most precise known coordinate:
      1. Block centre (≈ ±0.5 km noise)        — true street-level fidelity
      2. District centre (≈ ±5 km noise)       — within district boundary
      3. State centre (≈ ±20 km noise)         — fallback only

    The earlier bug used STATE centre + ±165 km noise, which scattered
    same-district tenders across the entire state.
    """
    # 1. Block-level real coordinate
    if (state in BLOCK_COORDINATES
            and district in BLOCK_COORDINATES[state]
            and block in BLOCK_COORDINATES[state][district]):
        c = BLOCK_COORDINATES[state][district][block]
        return (c["lat"] + rng.uniform(-0.005, 0.005),
                c["lon"] + rng.uniform(-0.005, 0.005))

    # 2. District-level fallback (small noise so points stay within district)
    if state in DISTRICT_COORDINATES and district in DISTRICT_COORDINATES[state]:
        c = DISTRICT_COORDINATES[state][district]
        return (c["lat"] + rng.uniform(-0.05, 0.05),
                c["lon"] + rng.uniform(-0.05, 0.05))

    # 3. State centre fallback (still tighter than original 1.5° noise)
    c = STATE_CENTERS[state]
    return (c["lat"] + rng.uniform(-0.25, 0.25),
            c["lon"] + rng.uniform(-0.25, 0.25))


# ---------------------------------------------------------------------------
# TITLE_TEMPLATES
# ---------------------------------------------------------------------------

TITLE_TEMPLATES: Dict[str, List[str]] = {
    "Infrastructure": [
        "Construction of {sector} Road in {block}, {district}",
        "Bridge over River near {block}, {district} District",
        "Four-Laning of State Highway through {district}",
        "Rehabilitation of NH Bypass at {block}",
        "Flyover Construction at {block} Junction, {district}",
        "Rural Road Connectivity Package — {block} Cluster",
        "Construction of Bypass Road for {district} Urban Area",
        "Grade Separator & Overpass at {block}, {district}",
    ],
    "Health": [
        "CHC Construction at {block}, {district}",
        "District Hospital Upgrade — {district}",
        "Primary Health Centre Renovation at {block}",
        "Medical Equipment Procurement for {district} Hospitals",
        "AYUSH Wellness Centre at {block}",
        "Cold Chain Infrastructure for NHM — {district}",
        "Ambulance Fleet Augmentation — {state}",
    ],
    "Education": [
        "Construction of Government School Building at {block}",
        "Smart Classroom Installation — {district} Schools",
        "College Infrastructure Development at {district}",
        "Hostel Block Construction — Navodaya Vidyalaya {district}",
        "Library & Lab Facility at {block}, {district}",
        "Digitisation of School Records — {district}",
        "Construction of Multi-Purpose Hall at {block} School",
        "Drinking Water & Sanitation Facility in {district} Schools",
    ],
    "Agriculture": [
        "Farm Pond Construction under PMKSY — {block}",
        "Cold Storage Warehouse at {district} Mandi",
        "Soil Testing Laboratory Setup at {block}",
        "Micro-Irrigation Network — {district} Cluster",
        "PM-KUSUM Solar Pump Installation — {block}",
        "Custom Hiring Centre for Farm Equipment — {block}",
        "Post-Harvest Processing Unit at {district}",
    ],
    "MSME": [
        "Common Facility Centre for {sector} Cluster — {district}",
        "MSME Industrial Shed Construction at {block}",
        "Technology Upgradation of Handloom Units — {district}",
        "Tool Room Modernisation — {district} MSME Hub",
        "Effluent Treatment Plant for Industrial Cluster at {block}",
        "Digital Marketplace Infrastructure for MSMEs — {state}",
    ],
    "Energy": [
        "Solar Power Plant (5 MW) at {block}, {district}",
        "Rural Electrification under DDUGJY — {block} Villages",
        "Substation Augmentation at {district}",
        "Smart Meter Rollout — {district} DISCOM",
        "Wind Energy Feasibility & Infrastructure — {district}",
        "Rooftop Solar Programme for Govt Buildings — {district}",
        "Transmission Line Upgradation — {block} Region",
    ],
    "Water & Sanitation": [
        "Jal Jeevan Mission — Piped Water Supply to {block}",
        "Overhead Tank Construction at {block}, {district}",
        "Sewage Treatment Plant Upgrade — {district}",
        "Solid Waste Management System — {block} ULB",
        "Open Defecation Free Village Programme — {block}",
        "River Front Development — {district}",
        "Deep Tubewell Installation for Drinking Water — {block}",
        "Effluent Channel Lining Project — {district}",
    ],
    "Urban Development": [
        "AMRUT 2.0 — Storm Water Drain Network at {district}",
        "PMAY Urban Housing Complex — {block}",
        "Metro Rail Infrastructure Extension — {district}",
        "Smart Road & Street Lighting — {block} Ward",
        "Parks & Public Spaces Development — {district}",
        "Integrated Command Control Centre — {district} Smart City",
        "Solid Waste Management Plant — {block} Municipality",
    ],
    "Rural Development": [
        "PMGSY Road Package — {block} Gram Panchayat Links",
        "PMAY Gramin Housing — {block} Phase II",
        "MNREGA Water Conservation Works — {district}",
        "Rural Community Centre at {block}",
        "Skill Development Centre — {block}, {district}",
        "Anganwadi Centre Construction — {block} Cluster",
        "Digital Village Initiative — {block}",
    ],
    "Minority Affairs": [
        "Minority Residential School at {district}",
        "Waqf Property Development — {district}",
        "Skill Training Centre for Minorities — {block}",
        "Scholarship & Hostel Infrastructure — {district}",
        "MSDP Community Hall at {block}",
    ],
    "Social Welfare": [
        "SC/ST Residential School Construction — {district}",
        "Anganwadi Strengthening Programme — {block}",
        "Women Safety & Empowerment Centre — {district}",
        "Tribal Development Hostel at {block}",
        "Senior Citizen Home Construction — {block}, {district}",
        "Divyang Rehabilitation Centre — {district}",
    ],
    "Digital & IT": [
        "BharatNet Optical Fibre Network — {block} GPs",
        "Common Service Centre Hub at {block}",
        "e-Governance Platform for {district} Administration",
        "Data Centre Infrastructure — {state} NIC",
        "CCTV Surveillance Network — {block} ULB",
        "Digital Literacy Centre at {block}",
        "Telecom Tower Installation — {block} Remote Areas",
    ],
}

# ---------------------------------------------------------------------------
# SECTOR_WEIGHTS
# ---------------------------------------------------------------------------

SECTOR_WEIGHTS: np.ndarray = np.array([
    0.22,   # Infrastructure
    0.12,   # Health
    0.14,   # Education
    0.10,   # Agriculture
    0.06,   # MSME
    0.08,   # Energy
    0.11,   # Water & Sanitation
    0.08,   # Urban Development
    0.07,   # Rural Development
    0.02,   # Minority Affairs
    0.04,   # Social Welfare
    0.04,   # Digital & IT
], dtype=np.float64)

# Normalise to sum exactly to 1.0
SECTOR_WEIGHTS = SECTOR_WEIGHTS / SECTOR_WEIGHTS.sum()

# Ordered list of sectors matching the weight array
_SECTOR_LIST: List[str] = [
    "Infrastructure",
    "Health",
    "Education",
    "Agriculture",
    "MSME",
    "Energy",
    "Water & Sanitation",
    "Urban Development",
    "Rural Development",
    "Minority Affairs",
    "Social Welfare",
    "Digital & IT",
]

# Short abbreviations for tender IDs
_SECTOR_ABBREV: Dict[str, str] = {
    "Infrastructure":     "INF",
    "Health":             "HLT",
    "Education":          "EDU",
    "Agriculture":        "AGR",
    "MSME":               "MSM",
    "Energy":             "ENR",
    "Water & Sanitation": "WAS",
    "Urban Development":  "URB",
    "Rural Development":  "RUR",
    "Minority Affairs":   "MIN",
    "Social Welfare":     "SWL",
    "Digital & IT":       "DIG",
}

# ---------------------------------------------------------------------------
# HELPER — Build flat lookup tables once at module load
# ---------------------------------------------------------------------------

def _build_lookup_tables() -> tuple:
    """
    Returns:
        state_list   — list of state names (one entry per state)
        state_probs  — np.ndarray probability proportional to # districts
        district_map — dict {state: [district, ...]}
        block_map    — dict {(state, district): [block, ...]}
    """
    state_list: List[str] = []
    district_counts: List[int] = []
    district_map: Dict[str, List[str]] = {}
    block_map: Dict[tuple, List[str]] = {}

    for state, districts in STATES_DATA.items():
        state_list.append(state)
        district_counts.append(len(districts))
        district_map[state] = list(districts.keys())
        for district, blocks in districts.items():
            block_map[(state, district)] = blocks

    counts_arr = np.array(district_counts, dtype=np.float64)
    state_probs = counts_arr / counts_arr.sum()

    return state_list, state_probs, district_map, block_map


_STATE_LIST, _STATE_PROBS, _DISTRICT_MAP, _BLOCK_MAP = _build_lookup_tables()

# ---------------------------------------------------------------------------
# CORE GENERATION FUNCTION
# ---------------------------------------------------------------------------

def generate_enterprise_seed_data(n: int = 10_000) -> pd.DataFrame:
    """
    Generate n synthetic government tender records using a seeded RNG.

    Returns a pandas DataFrame with columns:
        tender_id, title, sector, department, state, district, block,
        allocated_amount, latitude, longitude, status
    """
    logger.info("Generating %d synthetic tender records ...", n)
    rng = np.random.default_rng(seed=42)

    # ---- Sector selection (vectorised) ------------------------------------
    sector_indices = rng.choice(len(_SECTOR_LIST), size=n, p=SECTOR_WEIGHTS)
    sectors: List[str] = [_SECTOR_LIST[i] for i in sector_indices]

    # ---- State selection (proportional to district count) -----------------
    state_indices = rng.choice(len(_STATE_LIST), size=n, p=_STATE_PROBS)
    states: List[str] = [_STATE_LIST[i] for i in state_indices]

    # ---- District & Block selection (per-record) --------------------------
    districts: List[str] = []
    blocks: List[str] = []
    for st in states:
        dist_choices = _DISTRICT_MAP[st]
        chosen_dist = dist_choices[int(rng.integers(0, len(dist_choices)))]
        block_choices = _BLOCK_MAP[(st, chosen_dist)]
        chosen_block = block_choices[int(rng.integers(0, len(block_choices)))]
        districts.append(chosen_dist)
        blocks.append(chosen_block)

    # ---- Department selection (per sector) --------------------------------
    departments: List[str] = []
    for sec in sectors:
        dept_list = SECTOR_DEPARTMENTS[sec]
        departments.append(dept_list[int(rng.integers(0, len(dept_list)))])

    # ---- Title generation -------------------------------------------------
    titles: List[str] = []
    for i in range(n):
        sec = sectors[i]
        templates = TITLE_TEMPLATES[sec]
        tmpl = templates[int(rng.integers(0, len(templates)))]
        title = tmpl.format(
            sector=sec,
            block=blocks[i],
            district=districts[i],
            state=states[i],
        )
        titles.append(title)

    # ---- Tender IDs -------------------------------------------------------
    tender_ids: List[str] = []
    for i in range(n):
        abbrev = _SECTOR_ABBREV[sectors[i]]
        tender_ids.append(f"GEM/2026/{abbrev}/{100000 + i}")

    # ---- Allocated amount — log-normal, capped at 5000 Cr ----------------
    log_amounts = rng.lognormal(mean=1.5, sigma=1.2, size=n)
    allocated_amounts = np.clip(log_amounts, 0.01, 5000.0)
    allocated_amounts = np.round(allocated_amounts, 2)

    # ---- Geolocation — block-level real coords (district fallback) -------
    lats  = np.empty(n, dtype=np.float64)
    lons  = np.empty(n, dtype=np.float64)
    lats2 = np.full(n, np.nan, dtype=np.float64)
    lons2 = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        lat_i, lon_i = resolve_coords(states[i], districts[i], blocks[i], rng)
        lats[i] = lat_i
        lons[i] = lon_i
        # Linear infrastructure (roads/bridges/pipelines) → also compute endpoint
        if is_linear_title(titles[i]):
            lat2, lon2 = linear_endpoints(lat_i, lon_i, tender_ids[i])
            lats2[i] = lat2
            lons2[i] = lon2

    lats = np.round(lats, 6)
    lons = np.round(lons, 6)

    # ---- Status selection ------------------------------------------------
    status_choices = ["Active", "Awarded", "Completed"]
    status_probs = np.array([0.55, 0.25, 0.20])
    status_indices = rng.choice(3, size=n, p=status_probs)
    statuses: List[str] = [status_choices[int(i)] for i in status_indices]

    # ---- Contractor + project lifecycle dates ---------------------------
    CONTRACTORS = [
        "L&T Construction", "Tata Projects Ltd", "Shapoorji Pallonji",
        "Hindustan Construction Co (HCC)", "Gammon India", "IRCON International",
        "Afcons Infrastructure", "NBCC India", "KEC International",
        "Punj Lloyd", "Dilip Buildcon", "GR Infraprojects", "PNC Infratech",
        "Megha Engineering", "Sadbhav Engineering", "Ashoka Buildcon",
        "ITD Cementation", "Reliance Infra", "J Kumar Infraprojects",
        "Local Contractor (TBD)",
    ]
    # Awarded/Completed: contractor known; Active: TBD
    contractors = np.where(
        np.array(statuses) == "Active",
        "",
        rng.choice(CONTRACTORS, size=n),
    )

    # start_date: random day in [-540, +60] days from today
    # end_date:   start + 12..36 months
    today = pd.Timestamp.today().normalize()
    start_offsets = rng.integers(-540, 60, size=n)
    duration_days = rng.integers(365, 365 * 3, size=n)
    start_dates = [(today + pd.Timedelta(days=int(o))).date().isoformat() for o in start_offsets]
    end_dates   = [(today + pd.Timedelta(days=int(o + d))).date().isoformat()
                   for o, d in zip(start_offsets, duration_days)]

    # Completed status → end_date already in past; Active → start_date in future
    for i, s in enumerate(statuses):
        if s == "Completed":
            # nudge end_date into past
            past = today - pd.Timedelta(days=int(rng.integers(30, 365)))
            end_dates[i] = past.date().isoformat()

    # ---- Assemble DataFrame ----------------------------------------------
    df = pd.DataFrame({
        "tender_id":        tender_ids,
        "title":             titles,
        "sector":            sectors,
        "department":        departments,
        "state":             states,
        "district":          districts,
        "block":             blocks,
        "allocated_amount":  allocated_amounts,
        "latitude":          lats,
        "longitude":         lons,
        "latitude2":         lats2,
        "longitude2":        lons2,
        "status":            statuses,
        "contractor_name":   contractors,
        "start_date":        start_dates,
        "end_date":          end_dates,
        "source":            "Seed Data",
        "source_url":        "",
    })

    logger.info("Generated DataFrame with shape %s", df.shape)
    return df


# ---------------------------------------------------------------------------
# MEMORY OPTIMISATION
# ---------------------------------------------------------------------------

def apply_memory_optimization(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce DataFrame memory footprint by downcasting numeric types and
    converting high-cardinality string columns to Categorical.
    """
    cat_cols = ["state", "district", "block", "sector", "department", "status"]
    for col in cat_cols:
        if col in df.columns:
            df[col] = pd.Categorical(df[col])

    if "category" in df.columns:
        df["category"] = pd.Categorical(df["category"])

    for col in ["allocated_amount", "latitude", "longitude", "latitude2", "longitude2"]:
        if col in df.columns:
            df[col] = df[col].astype(np.float32)

    logger.info(
        "Memory optimisation applied. Usage: %.2f MB",
        df.memory_usage(deep=True).sum() / (1024 ** 2),
    )
    return df


# ---------------------------------------------------------------------------
# LOAD / CACHE
# ---------------------------------------------------------------------------

def _load_from_sqlite() -> Optional[pd.DataFrame]:
    """
    Load scraped real data from tenders.db (written by scraper_v3.py).
    Returns None if DB doesn't exist or has fewer than 10 rows.
    """
    import sqlite3
    db_path = BASE_DIR / "tenders.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM tenders").fetchone()[0]
        if count < 10:
            conn.close()
            return None
        # Auto-migrate old DBs that pre-date latitude2/longitude2 columns
        for col, sql_type in (("latitude2", "REAL"), ("longitude2", "REAL"),
                              ("contractor_name", "TEXT"), ("start_date", "TEXT"),
                              ("end_date", "TEXT"), ("source_url", "TEXT")):
            try:
                conn.execute(f"ALTER TABLE tenders ADD COLUMN {col} {sql_type}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        df = pd.read_sql(
            "SELECT tender_id, title, sector, department, state, district, block, "
            "       allocated_amount, latitude, longitude, latitude2, longitude2, "
            "       status, source, source_url, contractor_name, start_date, end_date "
            "FROM tenders",
            conn,
        )
        conn.close()
        logger.info("Loaded %d real scraped records from tenders.db", len(df))

        # Backfill linear endpoints for rows scraped before geometry classifier existed
        need_classify = df["latitude2"].isna()
        if need_classify.any():
            backfilled = 0
            for idx in df[need_classify].index:
                title = str(df.at[idx, "title"]) if pd.notna(df.at[idx, "title"]) else ""
                if is_linear_title(title):
                    lat = float(df.at[idx, "latitude"]) if pd.notna(df.at[idx, "latitude"]) else None
                    lon = float(df.at[idx, "longitude"]) if pd.notna(df.at[idx, "longitude"]) else None
                    if lat is not None and lon is not None:
                        tid = str(df.at[idx, "tender_id"])
                        lat2, lon2 = linear_endpoints(lat, lon, tid)
                        df.at[idx, "latitude2"]  = lat2
                        df.at[idx, "longitude2"] = lon2
                        backfilled += 1
            if backfilled:
                logger.info("Backfilled %d linear endpoints from titles", backfilled)
        return df
    except Exception as e:
        logger.warning("Could not load tenders.db: %s", e)
        return None


def load_health_log() -> Optional[pd.DataFrame]:
    """
    Read scraping_health_log table from tenders.db.
    Returns most-recent attempt per source (deduplicated, latest first).
    """
    import sqlite3
    db_path = BASE_DIR / "tenders.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql(
            """SELECT source, domain, status, error_code, error_msg,
                      records_fetched, logged_at
               FROM scraping_health_log
               ORDER BY logged_at DESC""",
            conn,
        )
        conn.close()
        if df.empty:
            return df
        # Keep only the most recent attempt per (source, domain)
        df = df.drop_duplicates(subset=["source", "domain"], keep="first")
        return df.reset_index(drop=True)
    except Exception as e:
        logger.warning("Could not load health log: %s", e)
        return None


def load_enterprise_tender_stream() -> pd.DataFrame:
    """
    Load priority:
      1. tenders.db  — real scraped data from scraper_v3.py
      2. generated_tenders.csv — seed data (fallback while scraper hasn't run)

    Returns a memory-optimised pandas DataFrame.
    """
    # Priority 1: real scraped data
    df = _load_from_sqlite()
    if df is not None:
        df = apply_memory_optimization(df)
        return df

    # Priority 2: generated seed CSV
    csv_file = BASE_DIR / "data" / "generated_tenders.csv"
    if csv_file.exists():
        logger.info("Cache file found at %s — reading ...", csv_file)
        try:
            df = pd.read_csv(csv_file, low_memory=False)
            if len(df) > 100:
                logger.info("Loaded %d rows from cache.", len(df))
                df = apply_memory_optimization(df)
                return df
        except Exception as exc:
            logger.warning("Failed to read cache (%s) — regenerating.", exc)

    # Last resort: generate seed data
    logger.info("No real data yet — generating seed data for UI preview …")
    df = generate_enterprise_seed_data(10_000)
    csv_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_file, index=False)
    logger.info("Saved %d seed rows to %s", len(df), csv_file)
    df = apply_memory_optimization(df)
    return df


# ---------------------------------------------------------------------------
# HIERARCHY
# ---------------------------------------------------------------------------

def get_full_hierarchy(df: pd.DataFrame) -> Dict[str, Dict]:
    """
    Build a nested hierarchy dict:
        {sector -> {department -> {state -> {district -> [blocks]}}}}

    All keys at every level are sorted alphabetically.
    """
    hierarchy: Dict[str, Dict] = {}

    for sector in sorted(df["sector"].unique()):
        hierarchy[sector] = {}
        sector_df = df[df["sector"] == sector]

        for dept in sorted(sector_df["department"].unique()):
            hierarchy[sector][dept] = {}
            dept_df = sector_df[sector_df["department"] == dept]

            for state in sorted(dept_df["state"].unique()):
                hierarchy[sector][dept][state] = {}
                state_df = dept_df[dept_df["state"] == state]

                for district in sorted(state_df["district"].unique()):
                    district_df = state_df[state_df["district"] == district]
                    blocks = sorted(district_df["block"].unique().tolist())
                    hierarchy[sector][dept][state][district] = blocks

    return hierarchy


# ---------------------------------------------------------------------------
# SERVER-SIDE AGGREGATION
# ---------------------------------------------------------------------------

def server_side_aggregate(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """
    Aggregate tender data grouped by group_col.

    Returns DataFrame with columns:
        <group_col>, total_amount, count, lat, lon
    """
    agg_df = (
        df.groupby(group_col, observed=True)
        .agg(
            total_amount=("allocated_amount", "sum"),
            count=("tender_id", "count"),
            lat=("latitude", "mean"),
            lon=("longitude", "mean"),
        )
        .reset_index()
    )
    agg_df["total_amount"] = agg_df["total_amount"].round(2)
    agg_df["lat"] = agg_df["lat"].round(6)
    agg_df["lon"] = agg_df["lon"].round(6)
    return agg_df


# ---------------------------------------------------------------------------
# VIEW CONFIG
# ---------------------------------------------------------------------------

def get_view_config(
    df_filtered: pd.DataFrame,
    state: Optional[str] = None,
    district: Optional[str] = None,
) -> Dict[str, float]:
    """
    Compute map viewport configuration based on current filter context.

    Returns dict with keys: lat, lon, zoom.
    """
    # Block / district level — prefer canonical district coord for stable centre
    if district is not None and state is not None:
        if state in DISTRICT_COORDINATES and district in DISTRICT_COORDINATES[state]:
            c = DISTRICT_COORDINATES[state][district]
            lat, lon = c["lat"], c["lon"]
        elif len(df_filtered) > 0:
            lat = float(df_filtered["latitude"].mean())
            lon = float(df_filtered["longitude"].mean())
        elif state in STATE_CENTERS:
            lat = STATE_CENTERS[state]["lat"]
            lon = STATE_CENTERS[state]["lon"]
        else:
            lat, lon = 22.5, 82.5
        # Tighter zoom so the district fills the viewport
        return {"lat": round(lat, 4), "lon": round(lon, 4), "zoom": 11}

    # State level — use STATE_CENTERS lookup
    if state is not None:
        if state in STATE_CENTERS:
            center = STATE_CENTERS[state]
            return {
                "lat": center["lat"],
                "lon": center["lon"],
                "zoom": center["zoom"],
            }
        # Fallback to centroid of filtered data
        if len(df_filtered) > 0:
            lat = float(df_filtered["latitude"].mean())
            lon = float(df_filtered["longitude"].mean())
            return {"lat": round(lat, 4), "lon": round(lon, 4), "zoom": 7}

    # National view
    return {"lat": 22.5, "lon": 82.5, "zoom": 4}


# ---------------------------------------------------------------------------
# MODULE SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Running pipeline self-test ...")
    df = load_enterprise_tender_stream()
    logger.info("DataFrame info:")
    logger.info("  Shape      : %s", df.shape)
    logger.info("  Columns    : %s", df.columns.tolist())
    logger.info("  Memory     : %.2f MB", df.memory_usage(deep=True).sum() / (1024 ** 2))
    logger.info("  Sectors    : %s", df["sector"].value_counts().to_dict())
    logger.info("  Statuses   : %s", df["status"].value_counts().to_dict())

    agg = server_side_aggregate(df, "sector")
    logger.info("Aggregation by sector:\n%s", agg.to_string(index=False))

    cfg_national = get_view_config(df)
    cfg_state    = get_view_config(df[df["state"] == "Bihar"], state="Bihar")
    cfg_district = get_view_config(
        df[(df["state"] == "Bihar") & (df["district"] == "Samastipur")],
        state="Bihar",
        district="Samastipur",
    )
    logger.info("View config (national):   %s", cfg_national)
    logger.info("View config (Bihar):      %s", cfg_state)
    logger.info("View config (Samastipur): %s", cfg_district)

    hierarchy = get_full_hierarchy(df)
    logger.info("Hierarchy top-level sectors: %s", list(hierarchy.keys()))
    logger.info("Pipeline self-test complete.")
