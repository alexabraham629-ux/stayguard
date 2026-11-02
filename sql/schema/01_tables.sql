-- StayGuard schema (DuckDB). Synthetic data — portfolio project.
-- Explicit types, primary keys, foreign keys and CHECK constraints for every enumerated column.
-- Money is DECIMAL in local currency; convert with dim_city.fx_to_gbp before aggregating (see v_bookings_gbp).

CREATE TABLE meta_build (
    snapshot_date      DATE    NOT NULL,   -- "today" inside the data
    seed               BIGINT  NOT NULL,
    scale              DOUBLE  NOT NULL,
    generator_version  VARCHAR NOT NULL
);

-- Analysis assumptions from config/assumptions.yaml, so SQL reads them instead of hard-coding.
CREATE TABLE meta_assumption (
    name         VARCHAR PRIMARY KEY,
    value        DOUBLE  NOT NULL,
    description  VARCHAR NOT NULL
);

CREATE TABLE dim_intake (
    intake             VARCHAR PRIMARY KEY,          -- e.g. 'Sep-2026'
    intake_start_date  DATE    NOT NULL,             -- move-in reference date
    intake_month       VARCHAR NOT NULL CHECK (intake_month IN ('Sep', 'Jan')),
    academic_year      VARCHAR NOT NULL,             -- e.g. '2025-26'
    is_closed          BOOLEAN NOT NULL,             -- intake started on or before the snapshot
    sort_order         INTEGER NOT NULL UNIQUE
);

CREATE TABLE dim_city (
    city_id      INTEGER PRIMARY KEY,
    city         VARCHAR NOT NULL UNIQUE,
    country      VARCHAR NOT NULL CHECK (country IN ('UK', 'AU', 'IE')),
    currency     VARCHAR NOT NULL CHECK (currency IN ('GBP', 'AUD', 'EUR')),
    market_tier  INTEGER NOT NULL CHECK (market_tier BETWEEN 1 AND 3),
    fx_to_gbp    DOUBLE  NOT NULL CHECK (fx_to_gbp > 0)   -- fixed rate, ADR-009
);

CREATE TABLE dim_university (
    university_id  INTEGER PRIMARY KEY,
    name           VARCHAR NOT NULL UNIQUE,               -- fictional
    city_id        INTEGER NOT NULL REFERENCES dim_city (city_id),
    intl_share     DOUBLE  NOT NULL CHECK (intl_share BETWEEN 0 AND 1)
);

CREATE TABLE dim_property (
    property_id                INTEGER PRIMARY KEY,
    city_id                    INTEGER NOT NULL REFERENCES dim_city (city_id),
    operator_type              VARCHAR NOT NULL CHECK (operator_type IN ('PBSA chain', 'independent PBSA', 'HMO')),
    room_type                  VARCHAR NOT NULL CHECK (room_type IN ('ensuite', 'studio', 'shared')),
    weekly_rent_local          DECIMAL(10, 2) NOT NULL,
    has_no_visa_no_pay         BOOLEAN NOT NULL,
    cooling_off_days           INTEGER NOT NULL,
    distance_km_to_university  DOUBLE  NOT NULL,
    rating                     DOUBLE  NOT NULL CHECK (rating BETWEEN 1 AND 5)
);

CREATE TABLE dim_agent (
    agent_id            INTEGER PRIMARY KEY,
    agent_name          VARCHAR NOT NULL,                 -- Faker-generated
    team                VARCHAR NOT NULL,
    languages           VARCHAR NOT NULL,                 -- comma-separated
    hire_date           DATE    NOT NULL,
    max_daily_capacity  INTEGER NOT NULL CHECK (max_daily_capacity > 0)   -- calls per day
);

CREATE TABLE dim_student (
    student_id         BIGINT PRIMARY KEY,
    source_country     VARCHAR NOT NULL,
    level              VARCHAR NOT NULL CHECK (level IN ('UG', 'PG')),
    university_id      INTEGER NOT NULL REFERENCES dim_university (university_id),
    budget_weekly_gbp  DECIMAL(10, 2) NOT NULL,
    has_guarantor      BOOLEAN NOT NULL
);

CREATE TABLE fact_lead (
    lead_id                 BIGINT PRIMARY KEY,
    student_id              BIGINT    NOT NULL REFERENCES dim_student (student_id),
    created_at              TIMESTAMP NOT NULL,
    channel                 VARCHAR   NOT NULL CHECK (channel IN ('organic', 'paid_search', 'referral', 'ambassador', 'partner_consultancy', 'loan_partner')),
    intake                  VARCHAR   NOT NULL REFERENCES dim_intake (intake),
    city_id                 INTEGER   NOT NULL REFERENCES dim_city (city_id),
    first_response_minutes  INTEGER,                      -- NULL if not contacted (or missing: a planted issue)
    contacted_at            TIMESTAMP,                    -- funnel stage timestamps (ADR-014)
    shortlisted_at          TIMESTAMP,
    agent_id                INTEGER   NOT NULL REFERENCES dim_agent (agent_id),
    status                  VARCHAR   NOT NULL CHECK (status IN ('new', 'contacted', 'shortlisted', 'booked', 'lost')),
    lost_reason             VARCHAR
);

CREATE TABLE fact_booking (
    booking_id                 BIGINT PRIMARY KEY,
    lead_id                    BIGINT    NOT NULL REFERENCES fact_lead (lead_id),
    student_id                 BIGINT    NOT NULL REFERENCES dim_student (student_id),
    property_id                INTEGER   NOT NULL REFERENCES dim_property (property_id),
    agent_id                   INTEGER   NOT NULL REFERENCES dim_agent (agent_id),
    booked_at                  TIMESTAMP NOT NULL,
    intake                     VARCHAR   NOT NULL REFERENCES dim_intake (intake),
    tenancy_weeks              INTEGER   NOT NULL CHECK (tenancy_weeks > 0),
    weekly_rent_local          DECIMAL(10, 2) NOT NULL,
    currency                   VARCHAR   NOT NULL CHECK (currency IN ('GBP', 'AUD', 'EUR')),
    gbv_local                  DECIMAL(12, 2) NOT NULL,
    commission_rate            DECIMAL(5, 4)  NOT NULL,   -- ASSUMPTION, by operator type
    commission_local           DECIMAL(12, 2) NOT NULL,
    deposit_paid               BOOLEAN   NOT NULL,
    visa_status_at_booking     VARCHAR   NOT NULL CHECK (visa_status_at_booking IN ('not_applied', 'pending', 'granted', 'not_required')),
    days_booked_before_intake  INTEGER   NOT NULL,
    status                     VARCHAR   NOT NULL CHECK (status IN ('open', 'cancelled', 'moved_in'))   -- ADR-006
);

CREATE TABLE fact_cancellation (
    booking_id           BIGINT PRIMARY KEY REFERENCES fact_booking (booking_id),
    cancelled_at         TIMESTAMP NOT NULL,
    reason               VARCHAR   NOT NULL CHECK (reason IN ('visa_refused', 'no_place', 'cooling_off', 'found_cheaper', 'duplicate_booking', 'changed_plans', 'other')),
    refund_amount_local  DECIMAL(12, 2) NOT NULL,
    days_after_booking   INTEGER   NOT NULL
);

-- An interaction belongs to exactly one lead OR one booking (ADR-014).
CREATE TABLE fact_interaction (
    interaction_id  BIGINT PRIMARY KEY,
    lead_id         BIGINT REFERENCES fact_lead (lead_id),
    booking_id      BIGINT REFERENCES fact_booking (booking_id),
    agent_id        INTEGER   NOT NULL REFERENCES dim_agent (agent_id),
    ts              TIMESTAMP NOT NULL,
    type            VARCHAR   NOT NULL CHECK (type IN ('call', 'whatsapp', 'email')),
    outcome         VARCHAR   NOT NULL CHECK (outcome IN ('connected', 'no_answer', 'replied', 'no_reply')),
    CHECK ((lead_id IS NULL) <> (booking_id IS NULL))
);
