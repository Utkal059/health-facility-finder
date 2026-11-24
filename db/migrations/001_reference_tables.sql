-- Master data that facilities point at.
--
-- LGD codes are plain integers in the Local Government Directory (Punjab is 3,
-- Amritsar is 27), so they are stored as integers. They only get zero-padded
-- when a facility ID is built from them (IN + 03 + 8 digits).

CREATE TABLE states (
    lgd_code smallint PRIMARY KEY CHECK (lgd_code BETWEEN 1 AND 99),
    name     text     NOT NULL UNIQUE CHECK (btrim(name) <> '')
);

CREATE TABLE districts (
    lgd_code       integer  PRIMARY KEY CHECK (lgd_code > 0),
    state_lgd_code smallint NOT NULL REFERENCES states (lgd_code),
    name           text     NOT NULL CHECK (btrim(name) <> ''),
    -- Lets facilities reference (district, state) as a pair, so a facility
    -- can never sit in a district that belongs to a different state.
    UNIQUE (lgd_code, state_lgd_code)
);
CREATE INDEX districts_state_idx ON districts (state_lgd_code, name);

CREATE TABLE sub_districts (
    lgd_code          integer PRIMARY KEY CHECK (lgd_code > 0),
    district_lgd_code integer NOT NULL REFERENCES districts (lgd_code),
    name              text    NOT NULL CHECK (btrim(name) <> ''),
    UNIQUE (lgd_code, district_lgd_code)
);
CREATE INDEX sub_districts_district_idx ON sub_districts (district_lgd_code, name);

CREATE TABLE ownership_types (
    code text PRIMARY KEY,
    name text NOT NULL UNIQUE
);

-- NHPR's search page hard-codes exactly these three ownership codes.
INSERT INTO ownership_types (code, name) VALUES
    ('G',  'Government'),
    ('P',  'Private'),
    ('PP', 'Public Private Partnership');

-- Facility records carry these by name. When NHPR's own master list gives an
-- id for an entry we keep it in `code`; otherwise `code` stays NULL.
CREATE TABLE facility_types (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text UNIQUE,
    name text NOT NULL CHECK (btrim(name) <> '')
);
CREATE UNIQUE INDEX facility_types_name_key ON facility_types (lower(name));

CREATE TABLE systems_of_medicine (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text UNIQUE,
    name text NOT NULL CHECK (btrim(name) <> '')
);
CREATE UNIQUE INDEX systems_of_medicine_name_key ON systems_of_medicine (lower(name));

CREATE TABLE specialities (
    id   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text UNIQUE,
    name text NOT NULL CHECK (btrim(name) <> '')
);
CREATE UNIQUE INDEX specialities_name_key ON specialities (lower(name));
