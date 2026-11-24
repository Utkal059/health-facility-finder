"""How search filters turn into SQL. No database needed."""

import pytest

from api.search import EmptySearchError, SearchFilters, build_search_query


def test_an_empty_search_is_refused():
    with pytest.raises(EmptySearchError):
        build_search_query(SearchFilters())


def test_whitespace_only_values_count_as_empty():
    with pytest.raises(EmptySearchError):
        build_search_query(SearchFilters(name="   ", state=""))


def test_facility_id_overrides_every_other_filter():
    query = build_search_query(
        SearchFilters(facility_id="in0310000334", state="3", name="civil", icu=True, sort="beds")
    )
    where = query.count_sql.split("WHERE", 1)[1]
    assert where.strip() == "f.facility_id = %(facility_id)s"
    assert query.params["facility_id"] == "IN0310000334"
    assert "name" not in query.params and "state" not in query.params


class TestLocationFilters:
    def test_numeric_state_is_an_lgd_code(self):
        query = build_search_query(SearchFilters(state="03"))
        assert "f.state_lgd_code = %(state)s" in query.count_sql
        assert query.params["state"] == 3

    def test_state_name_is_looked_up(self):
        query = build_search_query(SearchFilters(state="Punjab"))
        assert "FROM states WHERE lower(name) = lower(%(state)s)" in query.count_sql
        assert query.params["state"] == "Punjab"

    def test_filters_combine_with_and(self):
        query = build_search_query(SearchFilters(state="3", district="27", pincode="143001"))
        where = query.count_sql.split("WHERE", 1)[1]
        assert where.count("AND") == 2
        assert query.params.items() >= {"state": 3, "district": 27, "pincode": "143001"}.items()


class TestNameSearch:
    def test_uses_partial_and_typo_tolerant_matching(self):
        query = build_search_query(SearchFilters(name="civl hosp"))
        assert "f.name ILIKE %(name_like)s" in query.count_sql
        assert "%(name)s <%% f.name" in query.count_sql  # %% because psycopg formats the SQL
        assert query.params["name_like"] == "%civl hosp%"

    def test_like_wildcards_typed_by_the_user_are_escaped(self):
        query = build_search_query(SearchFilters(name="100%_sure"))
        assert query.params["name_like"] == "%100\\%\\_sure%"

    def test_values_never_end_up_in_the_sql_text(self):
        query = build_search_query(SearchFilters(name="O'Brien'); DROP TABLE facilities;--"))
        assert "DROP TABLE" not in query.page_sql and "O'Brien" not in query.count_sql

    def test_best_match_first_unless_a_sort_is_chosen(self):
        by_relevance = build_search_query(SearchFilters(name="apollo"))
        assert "ORDER BY word_similarity(%(name)s, f.name) DESC" in by_relevance.page_sql
        by_name = build_search_query(SearchFilters(name="apollo", sort="name"))
        assert "ORDER BY f.name, f.facility_id" in by_name.page_sql


class TestOtherFilters:
    @pytest.mark.parametrize(
        ("filters", "fragment"),
        [
            (SearchFilters(ownership="P"), "FROM ownership_types"),
            (SearchFilters(facility_type="Hospital"), "FROM facility_types"),
            (SearchFilters(system_of_medicine="Ayurveda"), "JOIN systems_of_medicine sm"),
            (SearchFilters(speciality="Cardiology"), "JOIN specialities sp"),
            (SearchFilters(status="approved"), "lower(f.status) = lower(%(status)s)"),
            (SearchFilters(sub_district="5"), "f.sub_district_lgd_code = %(sub_district)s"),
        ],
    )
    def test_each_filter_adds_its_condition(self, filters, fragment):
        assert fragment in build_search_query(filters).count_sql

    def test_icu_yes_and_no(self):
        assert "fi.has_icu_beds IS TRUE" in build_search_query(SearchFilters(icu=True)).count_sql
        assert "fi.has_icu_beds IS NOT TRUE" in build_search_query(
            SearchFilters(icu=False)).count_sql


class TestSortingAndPaging:
    @pytest.mark.parametrize(
        ("sort", "order_by"),
        [
            ("name", "ORDER BY f.name, f.facility_id"),
            ("district", "ORDER BY d.name, f.name, f.facility_id"),
            ("beds", "ORDER BY fi.total_beds DESC NULLS LAST, f.name, f.facility_id"),
        ],
    )
    def test_sort_options(self, sort, order_by):
        assert order_by in build_search_query(SearchFilters(state="3", sort=sort)).page_sql

    def test_page_and_page_size_become_limit_and_offset(self):
        query = build_search_query(SearchFilters(state="3", page=3, page_size=20))
        assert (query.params["limit"], query.params["offset"]) == (20, 40)

    def test_count_query_has_no_ordering_or_paging(self):
        query = build_search_query(SearchFilters(state="3", sort="beds"))
        assert "ORDER BY" not in query.count_sql and "LIMIT" not in query.count_sql
