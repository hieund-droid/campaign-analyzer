"""
Phân loại quốc gia theo VÙNG (region) và TIER — dùng để lọc/nhóm trong "Bảng
điểm thị trường". Tên quốc gia lấy ĐÚNG theo cách BigQuery trả về (đã query
trực tiếp `SELECT DISTINCT country` để xác nhận chính tả, không đoán — có vài
tên khác chuẩn ISO, VD "Cote d'Ivoire" không dấu, "Türkiye" có dấu, "Vietnam"
không phải "Viet Nam").

⚠️ LƯU Ý VỀ TIER: đây là 1 cách phân loại phổ biến trong ngành UA/mobile ads
(dựa trên sức mua/eCPM trung bình), KHÔNG PHẢI chuẩn tuyệt đối — các công ty
khác nhau định nghĩa Tier hơi khác nhau. Coi đây là điểm khởi đầu hợp lý, có
thể chỉnh sửa trực tiếp trong 2 dict bên dưới nếu không khớp quy ước của Apero.
"""

# Vùng — dựa theo châu lục/khu vực địa lý-kinh tế thường dùng trong ads.
REGION_ASIA = "Châu Á"
REGION_EUROPE = "Châu Âu"
REGION_AMERICAS = "Châu Mỹ"
REGION_AFRICA = "Châu Phi"
REGION_MIDDLE_EAST = "Trung Đông"
REGION_OCEANIA = "Châu Đại Dương"
REGION_UNKNOWN = "Không xác định"

ALL_REGIONS = [
    REGION_ASIA, REGION_EUROPE, REGION_AMERICAS, REGION_AFRICA,
    REGION_MIDDLE_EAST, REGION_OCEANIA, REGION_UNKNOWN,
]

TIER_1 = "Tier 1"
TIER_2 = "Tier 2"
TIER_3 = "Tier 3"
ALL_TIERS = [TIER_1, TIER_2, TIER_3]

COUNTRY_REGION = {
    # ── Châu Á ──────────────────────────────────────────────────────
    "Afghanistan": REGION_ASIA, "Bangladesh": REGION_ASIA, "Bhutan": REGION_ASIA,
    "Brunei": REGION_ASIA, "Cambodia": REGION_ASIA, "China": REGION_ASIA,
    "Hong Kong": REGION_ASIA, "India": REGION_ASIA, "Indonesia": REGION_ASIA,
    "Japan": REGION_ASIA, "Kazakhstan": REGION_ASIA, "Kyrgyzstan": REGION_ASIA,
    "Laos": REGION_ASIA, "Macao": REGION_ASIA, "Malaysia": REGION_ASIA,
    "Maldives": REGION_ASIA, "Mongolia": REGION_ASIA, "Myanmar (Burma)": REGION_ASIA,
    "Nepal": REGION_ASIA, "Pakistan": REGION_ASIA, "Philippines": REGION_ASIA,
    "Singapore": REGION_ASIA, "South Korea": REGION_ASIA, "Sri Lanka": REGION_ASIA,
    "Taiwan": REGION_ASIA, "Tajikistan": REGION_ASIA, "Thailand": REGION_ASIA,
    "Timor-Leste": REGION_ASIA, "Turkmenistan": REGION_ASIA, "Uzbekistan": REGION_ASIA,
    "Vietnam": REGION_ASIA, "British Indian Ocean Territory": REGION_ASIA,

    # ── Trung Đông ──────────────────────────────────────────────────
    "Bahrain": REGION_MIDDLE_EAST, "Iran": REGION_MIDDLE_EAST, "Iraq": REGION_MIDDLE_EAST,
    "Israel": REGION_MIDDLE_EAST, "Jordan": REGION_MIDDLE_EAST, "Kuwait": REGION_MIDDLE_EAST,
    "Lebanon": REGION_MIDDLE_EAST, "Oman": REGION_MIDDLE_EAST, "Palestine": REGION_MIDDLE_EAST,
    "Qatar": REGION_MIDDLE_EAST, "Saudi Arabia": REGION_MIDDLE_EAST, "Syria": REGION_MIDDLE_EAST,
    "United Arab Emirates": REGION_MIDDLE_EAST, "Yemen": REGION_MIDDLE_EAST,
    "Türkiye": REGION_MIDDLE_EAST,

    # ── Châu Âu (gồm cả Caucasus: Armenia/Azerbaijan/Georgia) ───────
    "Albania": REGION_EUROPE, "Andorra": REGION_EUROPE, "Armenia": REGION_EUROPE,
    "Austria": REGION_EUROPE, "Azerbaijan": REGION_EUROPE, "Belarus": REGION_EUROPE,
    "Belgium": REGION_EUROPE, "Bosnia and Herzegovina": REGION_EUROPE, "Bulgaria": REGION_EUROPE,
    "Croatia": REGION_EUROPE, "Cyprus": REGION_EUROPE, "Czechia": REGION_EUROPE,
    "Denmark": REGION_EUROPE, "Estonia": REGION_EUROPE, "Faroe Islands": REGION_EUROPE,
    "Finland": REGION_EUROPE, "France": REGION_EUROPE, "Georgia": REGION_EUROPE,
    "Germany": REGION_EUROPE, "Gibraltar": REGION_EUROPE, "Greece": REGION_EUROPE,
    "Guernsey": REGION_EUROPE, "Hungary": REGION_EUROPE, "Iceland": REGION_EUROPE,
    "Ireland": REGION_EUROPE, "Isle of Man": REGION_EUROPE, "Italy": REGION_EUROPE,
    "Jersey": REGION_EUROPE, "Kosovo": REGION_EUROPE, "Latvia": REGION_EUROPE,
    "Liechtenstein": REGION_EUROPE, "Lithuania": REGION_EUROPE, "Luxembourg": REGION_EUROPE,
    "Malta": REGION_EUROPE, "Moldova": REGION_EUROPE, "Monaco": REGION_EUROPE,
    "Montenegro": REGION_EUROPE, "Netherlands": REGION_EUROPE, "North Macedonia": REGION_EUROPE,
    "Norway": REGION_EUROPE, "Poland": REGION_EUROPE, "Portugal": REGION_EUROPE,
    "Romania": REGION_EUROPE, "Russia": REGION_EUROPE, "San Marino": REGION_EUROPE,
    "Serbia": REGION_EUROPE, "Slovakia": REGION_EUROPE, "Slovenia": REGION_EUROPE,
    "Spain": REGION_EUROPE, "Svalbard and Jan Mayen": REGION_EUROPE, "Sweden": REGION_EUROPE,
    "Switzerland": REGION_EUROPE, "Ukraine": REGION_EUROPE, "United Kingdom": REGION_EUROPE,

    # ── Châu Mỹ (Bắc + Trung + Nam + Caribbean, gộp 1 nhóm theo yêu cầu) ──
    "Canada": REGION_AMERICAS, "United States": REGION_AMERICAS, "Mexico": REGION_AMERICAS,
    "Bermuda": REGION_AMERICAS, "Greenland": REGION_AMERICAS,
    "Anguilla": REGION_AMERICAS, "Antigua and Barbuda": REGION_AMERICAS, "Aruba": REGION_AMERICAS,
    "The Bahamas": REGION_AMERICAS, "Barbados": REGION_AMERICAS, "Belize": REGION_AMERICAS,
    "British Virgin Islands": REGION_AMERICAS, "Cayman Islands": REGION_AMERICAS,
    "Costa Rica": REGION_AMERICAS, "Cuba": REGION_AMERICAS, "Curacao": REGION_AMERICAS,
    "Dominica": REGION_AMERICAS, "Dominican Republic": REGION_AMERICAS, "El Salvador": REGION_AMERICAS,
    "Grenada": REGION_AMERICAS, "Guadeloupe": REGION_AMERICAS, "Guatemala": REGION_AMERICAS,
    "Haiti": REGION_AMERICAS, "Honduras": REGION_AMERICAS, "Jamaica": REGION_AMERICAS,
    "Martinique": REGION_AMERICAS, "Montserrat": REGION_AMERICAS, "Nicaragua": REGION_AMERICAS,
    "Panama": REGION_AMERICAS, "Puerto Rico": REGION_AMERICAS, "Saint Barthelemy": REGION_AMERICAS,
    "Saint Kitts and Nevis": REGION_AMERICAS, "Saint Lucia": REGION_AMERICAS,
    "Saint Martin": REGION_AMERICAS, "Saint Pierre and Miquelon": REGION_AMERICAS,
    "Saint Vincent and the Grenadines": REGION_AMERICAS, "Sint Maarten": REGION_AMERICAS,
    "Trinidad and Tobago": REGION_AMERICAS, "Turks and Caicos Islands": REGION_AMERICAS,
    "U.S. Virgin Islands": REGION_AMERICAS, "Caribbean Netherlands": REGION_AMERICAS,
    "Argentina": REGION_AMERICAS, "Bolivia": REGION_AMERICAS, "Brazil": REGION_AMERICAS,
    "Chile": REGION_AMERICAS, "Colombia": REGION_AMERICAS, "Ecuador": REGION_AMERICAS,
    "French Guiana": REGION_AMERICAS, "Guyana": REGION_AMERICAS, "Paraguay": REGION_AMERICAS,
    "Peru": REGION_AMERICAS, "Suriname": REGION_AMERICAS, "Uruguay": REGION_AMERICAS,
    "Venezuela": REGION_AMERICAS, "Falkland Islands (Malvinas)": REGION_AMERICAS,

    # ── Châu Phi ─────────────────────────────────────────────────────
    "Algeria": REGION_AFRICA, "Angola": REGION_AFRICA, "Benin": REGION_AFRICA,
    "Botswana": REGION_AFRICA, "Burkina Faso": REGION_AFRICA, "Burundi": REGION_AFRICA,
    "Cabo Verde": REGION_AFRICA, "Cameroon": REGION_AFRICA, "Central African Republic": REGION_AFRICA,
    "Chad": REGION_AFRICA, "Comoros": REGION_AFRICA, "Democratic Republic of the Congo": REGION_AFRICA,
    "Republic of the Congo": REGION_AFRICA, "Cote d'Ivoire": REGION_AFRICA, "Djibouti": REGION_AFRICA,
    "Egypt": REGION_AFRICA, "Equatorial Guinea": REGION_AFRICA, "Eritrea": REGION_AFRICA,
    "Eswatini": REGION_AFRICA, "Ethiopia": REGION_AFRICA, "Gabon": REGION_AFRICA,
    "Ghana": REGION_AFRICA, "Guinea": REGION_AFRICA, "Guinea-Bissau": REGION_AFRICA,
    "Kenya": REGION_AFRICA, "Lesotho": REGION_AFRICA, "Liberia": REGION_AFRICA,
    "Libya": REGION_AFRICA, "Madagascar": REGION_AFRICA, "Malawi": REGION_AFRICA,
    "Mali": REGION_AFRICA, "Mauritania": REGION_AFRICA, "Mauritius": REGION_AFRICA,
    "Mayotte": REGION_AFRICA, "Morocco": REGION_AFRICA, "Mozambique": REGION_AFRICA,
    "Namibia": REGION_AFRICA, "Niger": REGION_AFRICA, "Nigeria": REGION_AFRICA,
    "Réunion": REGION_AFRICA, "Rwanda": REGION_AFRICA, "Sao Tome and Principe": REGION_AFRICA,
    "Senegal": REGION_AFRICA, "Seychelles": REGION_AFRICA, "Sierra Leone": REGION_AFRICA,
    "Somalia": REGION_AFRICA, "South Africa": REGION_AFRICA, "South Sudan": REGION_AFRICA,
    "Sudan": REGION_AFRICA, "Tanzania": REGION_AFRICA, "Togo": REGION_AFRICA,
    "Tunisia": REGION_AFRICA, "Uganda": REGION_AFRICA, "Western Sahara": REGION_AFRICA,
    "Zambia": REGION_AFRICA, "Zimbabwe": REGION_AFRICA, "The Gambia": REGION_AFRICA,
    "Saint Helena, Ascension and Tristan da Cunha": REGION_AFRICA,

    # ── Châu Đại Dương ───────────────────────────────────────────────
    "Australia": REGION_OCEANIA, "New Zealand": REGION_OCEANIA, "Fiji": REGION_OCEANIA,
    "Papua New Guinea": REGION_OCEANIA, "Solomon Islands": REGION_OCEANIA, "Vanuatu": REGION_OCEANIA,
    "Samoa": REGION_OCEANIA, "Tonga": REGION_OCEANIA, "Kiribati": REGION_OCEANIA,
    "Micronesia": REGION_OCEANIA, "Marshall Islands": REGION_OCEANIA, "Nauru": REGION_OCEANIA,
    "Palau": REGION_OCEANIA, "Tuvalu": REGION_OCEANIA, "New Caledonia": REGION_OCEANIA,
    "French Polynesia": REGION_OCEANIA, "Guam": REGION_OCEANIA, "American Samoa": REGION_OCEANIA,
    "Cook Islands": REGION_OCEANIA, "Niue": REGION_OCEANIA, "Norfolk Island": REGION_OCEANIA,
    "Tokelau": REGION_OCEANIA, "Wallis and Futuna": REGION_OCEANIA,
    "Northern Mariana Islands": REGION_OCEANIA, "Pitcairn Islands": REGION_OCEANIA,
    "United States Minor Outlying Islands": REGION_OCEANIA,
}

# Tier 1 & 2 liệt kê tường minh (danh sách phổ biến trong ads/UA); mọi quốc gia
# KHÔNG có trong 2 danh sách này mặc định là Tier 3 (xem get_tier() bên dưới).
TIER_1_COUNTRIES = {
    "United States", "Canada", "United Kingdom", "Australia", "New Zealand",
    "Germany", "France", "Japan", "South Korea", "Norway", "Sweden", "Denmark",
    "Finland", "Switzerland", "Netherlands", "Ireland", "Singapore", "Hong Kong",
    "Austria", "Belgium", "Luxembourg",
}

TIER_2_COUNTRIES = {
    "Italy", "Spain", "Portugal", "Poland", "Czechia", "Slovakia", "Slovenia",
    "Croatia", "Hungary", "Romania", "Bulgaria", "Greece", "Estonia", "Latvia",
    "Lithuania", "Malta", "Cyprus", "Iceland", "Taiwan", "Israel",
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman",
    "Brazil", "Mexico", "Chile", "Argentina", "Uruguay", "China", "Russia",
    "Malaysia", "Türkiye", "South Africa",
}


def get_region(country: str) -> str:
    return COUNTRY_REGION.get(country, REGION_UNKNOWN)


def get_tier(country: str) -> str:
    if country in TIER_1_COUNTRIES:
        return TIER_1
    if country in TIER_2_COUNTRIES:
        return TIER_2
    return TIER_3
