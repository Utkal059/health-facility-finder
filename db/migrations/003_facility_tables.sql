-- The facilities themselves, their infrastructure and their many-to-many
-- links. Everything in here is loaded by the scraper from NHPR responses.

CREATE TABLE facilities (
    facility_id                char(12) PRIMARY KEY CHECK (facility_id ~ '^IN[0-9]{10}$'),
    name                       text     NOT NULL CHECK (btrim(name) <> ''),
    status                     text     NOT NULL CHECK (btrim(status) <> ''),
    ownership_code             text     REFERENCES ownership_types (code),
    facility_type_id           integer  REFERENCES facility_types (id),
    state_lgd_code             smallint NOT NULL REFERENCES states (lgd_code),
    district_lgd_code          integer  NOT NULL,
    sub_district_lgd_code      integer,
    village_city_town_name     text,
    village_city_town_lgd_code integer,
    address                    text,
    pincode                    char(6)  CHECK (pincode ~ '^[1-9][0-9]{5}$'),
    -- A generous box around India, Andaman & Nicobar and Ladakh included.
    latitude                   numeric(8, 6) CHECK (latitude BETWEEN 6 AND 37.5),
    longitude                  numeric(9, 6) CHECK (longitude BETWEEN 68 AND 97.5),
    abdm_software              boolean,
    type_of_service            text,
    phone                      text CHECK (phone ~ '^\+91[1-9][0-9]{9}$'),
    website                    text,
    photo_url                  text,
    source_response_id         bigint REFERENCES raw_responses (id) ON DELETE SET NULL,
    first_seen_at              timestamptz NOT NULL,
    last_seen_at               timestamptz NOT NULL,

    FOREIGN KEY (district_lgd_code, state_lgd_code)
        REFERENCES districts (lgd_code, state_lgd_code),
    FOREIGN KEY (sub_district_lgd_code, district_lgd_code)
        REFERENCES sub_districts (lgd_code, district_lgd_code),
    CHECK ((latitude IS NULL) = (longitude IS NULL)),
    CHECK (last_seen_at >= first_seen_at)
);

-- 1:1 with facilities, and only present when NHPR published something.
CREATE TABLE facility_infrastructure (
    facility_id  char(12) PRIMARY KEY REFERENCES facilities (facility_id) ON DELETE CASCADE,
    has_icu_beds boolean,
    total_beds   integer CHECK (total_beds >= 0),
    icu_beds     integer CHECK (icu_beds >= 0),
    ventilators  integer CHECK (ventilators >= 0),
    CHECK (icu_beds <= total_beds)
);

CREATE TABLE facility_specialities (
    facility_id   char(12) NOT NULL REFERENCES facilities (facility_id) ON DELETE CASCADE,
    speciality_id integer  NOT NULL REFERENCES specialities (id),
    PRIMARY KEY (facility_id, speciality_id)
);

-- NHPR lists several systems of medicine for many facilities
-- ("Modern Medicine(Allopathy),Dentistry"), so this is many-to-many too.
CREATE TABLE facility_systems_of_medicine (
    facility_id char(12) NOT NULL REFERENCES facilities (facility_id) ON DELETE CASCADE,
    system_id   integer  NOT NULL REFERENCES systems_of_medicine (id),
    PRIMARY KEY (facility_id, system_id)
);

-- Each search result that mentioned a facility. A facility that turns up in
-- two district searches has two sightings but still one facilities row.
CREATE TABLE facility_sightings (
    facility_id char(12) NOT NULL REFERENCES facilities (facility_id) ON DELETE CASCADE,
    response_id bigint   NOT NULL REFERENCES raw_responses (id) ON DELETE CASCADE,
    PRIMARY KEY (facility_id, response_id)
);
