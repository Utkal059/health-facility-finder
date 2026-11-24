-- Indexes for the filters and sorts GET /api/facilities supports.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Partial and typo-tolerant name search. Both `name ILIKE '%term%'` and the
-- word-similarity operator (`term <% name`) can use this one trigram index.
CREATE INDEX facilities_name_trgm_idx ON facilities USING gin (name gin_trgm_ops);

-- Location filters, with name as a tiebreaker for the default sort.
CREATE INDEX facilities_location_idx ON facilities (state_lgd_code, district_lgd_code, name);
CREATE INDEX facilities_district_idx ON facilities (district_lgd_code);
CREATE INDEX facilities_sub_district_idx ON facilities (sub_district_lgd_code)
    WHERE sub_district_lgd_code IS NOT NULL;
CREATE INDEX facilities_pincode_idx ON facilities (pincode) WHERE pincode IS NOT NULL;

CREATE INDEX facilities_type_idx ON facilities (facility_type_id);
CREATE INDEX facilities_ownership_idx ON facilities (ownership_code);
CREATE INDEX facilities_status_idx ON facilities (lower(status));
CREATE INDEX facilities_name_sort_idx ON facilities (name, facility_id);

CREATE INDEX facility_infrastructure_beds_idx
    ON facility_infrastructure (total_beds DESC NULLS LAST);
CREATE INDEX facility_infrastructure_icu_idx ON facility_infrastructure (has_icu_beds);

-- The primary keys cover facility -> speciality; these cover the reverse.
CREATE INDEX facility_specialities_speciality_idx ON facility_specialities (speciality_id);
CREATE INDEX facility_systems_system_idx ON facility_systems_of_medicine (system_id);
