-- NHPR's search results give a facility's sub-district as an LGD code with no
-- name, and its search page never loads a sub-district list. Keep the code
-- (the subDistrict filter only needs that) and leave the name empty.

ALTER TABLE sub_districts ALTER COLUMN name DROP NOT NULL;
