"""Static description of the simulated world: cities, rents, student mix, channels, teams.

These are background calibration constants that make the data look realistic. The business
assumptions and the planted ground-truth effects the analysis must re-discover live in
config/assumptions.yaml (ADR-015). All names (universities, agents) are fictional.
"""

from __future__ import annotations

SOURCE_COUNTRIES: tuple[str, ...] = (
    "India",
    "China",
    "Nigeria",
    "Pakistan",
    "Nepal",
    "UK",
    "Vietnam",
    "Saudi Arabia",
    "USA",
    "Other",
)

# city -> (country, currency, market_tier, share of all leads,
#          weekly ensuite rent band in local currency)
CITIES: dict[str, tuple[str, str, int, float, tuple[int, int]]] = {
    "London": ("UK", "GBP", 1, 0.20, (280, 380)),
    "Manchester": ("UK", "GBP", 2, 0.09, (170, 230)),
    "Birmingham": ("UK", "GBP", 2, 0.08, (160, 220)),
    "Nottingham": ("UK", "GBP", 3, 0.06, (150, 200)),
    "Leeds": ("UK", "GBP", 2, 0.07, (160, 215)),
    "Glasgow": ("UK", "GBP", 2, 0.06, (165, 220)),
    "Coventry": ("UK", "GBP", 3, 0.05, (155, 205)),
    "Sheffield": ("UK", "GBP", 3, 0.05, (140, 190)),
    "Sydney": ("AU", "AUD", 1, 0.12, (420, 560)),
    "Melbourne": ("AU", "AUD", 1, 0.11, (380, 520)),
    "Brisbane": ("AU", "AUD", 2, 0.05, (330, 450)),
    "Dublin": ("IE", "EUR", 1, 0.06, (280, 380)),
}

UNIVERSITIES: dict[str, tuple[str, ...]] = {
    "London": ("Northbridge University", "Thameside University", "Kingsgate College London"),
    "Manchester": ("Irwell University", "Pennine Institute of Technology"),
    "Birmingham": ("Midland Crown University", "Rea Valley University"),
    "Nottingham": ("Sherwood Vale University", "Trentbridge University"),
    "Leeds": ("Aire Valley University", "Kirkgate University"),
    "Glasgow": ("Clydebank University", "Kelvinside Institute of Technology"),
    "Coventry": ("Three Spires University",),
    "Sheffield": ("Don Valley University", "Peakgate University"),
    "Sydney": ("Harbourside University", "Coogee Bay University"),
    "Melbourne": ("Yarra Bend University", "Southbank Institute of Technology"),
    "Brisbane": ("Riverbend University",),
    "Dublin": ("Liffey University", "Phoenix Park Institute"),
}

# Source-country mix of leads, per market country, aligned with SOURCE_COUNTRIES.
SOURCE_MIX_BY_MARKET: dict[str, tuple[float, ...]] = {
    "UK": (0.22, 0.17, 0.09, 0.06, 0.03, 0.25, 0.03, 0.03, 0.03, 0.09),
    "AU": (0.24, 0.28, 0.02, 0.04, 0.10, 0.02, 0.08, 0.02, 0.04, 0.16),
    "IE": (0.18, 0.10, 0.04, 0.03, 0.02, 0.05, 0.02, 0.02, 0.12, 0.42),
}

PG_SHARE: dict[str, float] = {
    "India": 0.65,
    "China": 0.55,
    "Nigeria": 0.70,
    "Pakistan": 0.65,
    "Nepal": 0.50,
    "UK": 0.15,
    "Vietnam": 0.50,
    "Saudi Arabia": 0.60,
    "USA": 0.45,
    "Other": 0.30,
}

# Probability a student needs a study visa for the market; missing source country -> 1.0.
VISA_REQUIRED_PROB: dict[str, dict[str, float]] = {
    "UK": {"UK": 0.0, "Other": 0.5},
    "AU": {"Other": 0.4},
    "IE": {"UK": 0.0, "Other": 0.15},
}

BUDGET_FACTOR: dict[str, float] = {
    "India": 0.92,
    "China": 1.12,
    "Nigeria": 0.88,
    "Pakistan": 0.88,
    "Nepal": 0.82,
    "UK": 0.88,
    "Vietnam": 0.92,
    "Saudi Arabia": 1.25,
    "USA": 1.18,
    "Other": 1.00,
}
BUDGET_SIGMA = 0.22
GUARANTOR_PROB: dict[str, float] = {"UK": 0.80, "Other": 0.50}  # everyone else 0.30
DEFAULT_GUARANTOR_PROB = 0.30

COUNTRY_GROUP: dict[str, str] = {
    "India": "south_asia_africa",
    "Pakistan": "south_asia_africa",
    "Nepal": "south_asia_africa",
    "Nigeria": "south_asia_africa",
    "China": "east_asia",
    "Vietnam": "east_asia",
}
DEFAULT_COUNTRY_GROUP = "other_markets"

CHANNELS: tuple[str, ...] = (
    "organic",
    "paid_search",
    "referral",
    "ambassador",
    "partner_consultancy",
    "loan_partner",
)
CHANNEL_MIX_BY_GROUP: dict[str, tuple[float, ...]] = {
    "south_asia_africa": (0.22, 0.20, 0.10, 0.08, 0.24, 0.16),
    "east_asia": (0.30, 0.25, 0.12, 0.08, 0.20, 0.05),
    "other_markets": (0.40, 0.30, 0.15, 0.10, 0.04, 0.01),
}

# team -> (cities served, number of agents, Faker locales for agent names)
TEAMS: dict[str, tuple[tuple[str, ...], int, tuple[str, ...]]] = {
    "London": (("London",), 7, ("en_GB", "en_IN")),
    "UK North": (("Manchester", "Leeds", "Sheffield", "Glasgow"), 7, ("en_GB",)),
    "UK Midlands": (("Birmingham", "Nottingham", "Coventry"), 5, ("en_GB", "en_IN")),
    "ANZ": (("Sydney", "Melbourne", "Brisbane"), 7, ("en_AU",)),
    "Ireland": (("Dublin",), 3, ("en_IE",)),
}
OVERLOAD_CANDIDATE_TEAMS: tuple[str, ...] = ("London", "UK North")
# Words that must never appear in generated names (branding rule: no real marketplace brand).
RESERVED_NAME_WORDS: tuple[str, ...] = ("Amber",)
AGENT_LANGUAGES: tuple[str, ...] = (
    "Hindi",
    "Mandarin",
    "Urdu",
    "Yoruba",
    "Nepali",
    "Vietnamese",
    "Arabic",
    "Cantonese",
)
AGENT_CAPACITY_RANGE = (25, 40)  # calls per day

# Properties
PROPERTIES_BASE_PER_CITY = 16
PROPERTIES_PER_LEAD_SHARE = 70
OPERATOR_MIX: dict[str, float] = {"PBSA chain": 0.45, "independent PBSA": 0.35, "HMO": 0.20}
ROOM_MIX: dict[str, dict[str, float]] = {
    "PBSA chain": {"ensuite": 0.5, "studio": 0.4, "shared": 0.1},
    "independent PBSA": {"ensuite": 0.5, "studio": 0.35, "shared": 0.15},
    "HMO": {"ensuite": 0.3, "studio": 0.0, "shared": 0.7},
}
ROOM_RENT_FACTOR: dict[str, float] = {"studio": 1.25, "ensuite": 1.0, "shared": 0.75}
OPERATOR_RENT_FACTOR: dict[str, float] = {"PBSA chain": 1.05, "independent PBSA": 1.0, "HMO": 0.8}
NO_VISA_NO_PAY_PROB: dict[str, float] = {"PBSA chain": 0.9, "independent PBSA": 0.6, "HMO": 0.2}
COOLING_OFF_OPTIONS: tuple[int, ...] = (0, 7, 14)
COOLING_OFF_PROBS: dict[str, tuple[float, ...]] = {
    "PBSA chain": (0.1, 0.7, 0.2),
    "independent PBSA": (0.3, 0.6, 0.1),
    "HMO": (0.7, 0.3, 0.0),
}

# Lead funnel
NEVER_CONTACTED_SHARE = 0.06
RESPONSE_MEDIAN_MINUTES = 70.0
RESPONSE_SIGMA = 1.1
RESPONSE_MAX_MINUTES = 7 * 24 * 60
SHORTLIST_BASE_LOGIT = 0.52
BOOK_BASE_LOGIT = 0.32
FUNNEL_LOGIT_NOISE = 0.3
DAYS_TO_SHORTLIST_MEAN = 3.0
DAYS_TO_BOOK_MEAN = 5.0
DAYS_TO_LOSS_MEAN = 18.0
LOST_REASONS: dict[str, tuple[tuple[str, ...], tuple[float, ...]]] = {
    "new": (("not_contacted",), (1.0,)),
    "contacted": (
        ("unresponsive", "budget", "not_eligible", "chose_competitor"),
        (0.40, 0.25, 0.15, 0.20),
    ),
    "shortlisted": (
        ("chose_competitor", "budget", "no_availability", "plans_changed"),
        (0.35, 0.25, 0.20, 0.20),
    ),
}

# Bookings
TENANCY_WEEKS: dict[tuple[str, str], tuple[tuple[int, ...], tuple[float, ...]]] = {
    ("Sep", "UG"): ((44, 51), (0.6, 0.4)),
    ("Sep", "PG"): ((44, 51), (0.2, 0.8)),
    ("Jan", "UG"): ((26, 30, 33, 51), (0.3, 0.3, 0.25, 0.15)),
    ("Jan", "PG"): ((26, 30, 33, 51), (0.3, 0.3, 0.25, 0.15)),
}
RENT_NOISE_SIGMA = 0.03
DEPOSIT_BASE_PROB = 0.78
DEPOSIT_LOGIT_EFFECTS: dict[str, float] = {"paid_search": -0.6, "has_guarantor": 0.3, "PG": 0.2}
# P(not_applied, pending, granted) for visa-required students, by lead-time bucket (<30 ... 180+)
VISA_STATUS_BY_BUCKET: tuple[tuple[float, float, float], ...] = (
    (0.02, 0.18, 0.80),
    (0.10, 0.40, 0.50),
    (0.30, 0.45, 0.25),
    (0.60, 0.30, 0.10),
)

# Cancellation: competing reasons, each with its own intensity
CANCEL_REASONS: tuple[str, ...] = (
    "visa_refused",
    "no_place",
    "cooling_off",
    "found_cheaper",
    "duplicate_booking",
    "changed_plans",
    "other",
)
CANCEL_BASE_INTENSITY: dict[str, float] = {
    "no_place": 0.030,
    "cooling_off": 0.025,
    "found_cheaper": 0.050,
    "duplicate_booking": 0.030,
    "changed_plans": 0.040,
    "other": 0.015,
}
NO_PLACE_LEVEL_MULT: dict[str, float] = {"UG": 1.4, "PG": 0.8}
OVER_BUDGET_SLOPE = 1.5  # found_cheaper intensity × (1 + slope × min(rent/budget − 1, 1))
CANCEL_NOISE_SIGMA = 0.3
# Timing of a cancellation as a share of the booking-to-move-in window: Beta(a, b)
CANCEL_TIMING_BETA: dict[str, tuple[float, float]] = {
    "visa_refused": (4.0, 2.0),
    "no_place": (5.0, 2.0),
    "found_cheaper": (1.2, 3.5),
    "duplicate_booking": (1.0, 6.0),
    "changed_plans": (1.5, 1.5),
    "other": (1.0, 1.0),
}
# Share of the deposit refunded, by reason (visa_refused depends on No Visa, No Pay)
REFUND_SHARE: dict[str, float] = {"cooling_off": 1.0, "no_place": 1.0}
VISA_REFUND_SHARE_WITH_POLICY = 1.0
VISA_REFUND_SHARE_WITHOUT_POLICY = 0.5
OTHER_REFUND_OPTIONS: tuple[tuple[float, ...], tuple[float, ...]] = ((0.0, 0.5), (0.6, 0.4))

# Interactions
LEAD_EXTRA_TOUCHES_MEAN = 1.2
BOOKING_TOUCHES_MEAN = 1.6
POSITIVE_OUTCOME_PROB = 0.62
# Students who will cancel engage less. Usable only "as of" a scoring date (leakage trap, ADR-016).
POSITIVE_OUTCOME_PROB_WILL_CANCEL = 0.38
TOUCH_TYPES: tuple[str, ...] = ("call", "whatsapp", "email")
TOUCH_TYPE_MIX_BY_GROUP: dict[str, tuple[float, ...]] = {
    "south_asia_africa": (0.30, 0.55, 0.15),
    "east_asia": (0.25, 0.25, 0.50),
    "other_markets": (0.45, 0.20, 0.35),
}
