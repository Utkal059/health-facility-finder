"""Response shapes, mainly so the OpenAPI docs describe them properly.

Field names follow the HFR search API (Appendix A/B of the brief), which is
why they are camelCase.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

YesNo = Literal["Yes", "No"]


class FacilitySummary(BaseModel):
    facilityId: str = Field(examples=["IN0310000334"])
    facilityName: str
    facilityStatus: str = Field(examples=["Approved"])
    ownership: str | None = Field(examples=["Private"])
    ownershipCode: str | None = Field(examples=["P"])
    facilityType: str | None = Field(examples=["Hospital"])
    facilityTypeCode: str | None
    systemOfMedicine: str | None = Field(examples=["Modern Medicine(Allopathy)"])
    systemOfMedicineCode: str | None
    stateName: str
    stateLGDCode: str = Field(examples=["3"])
    districtName: str
    districtLGDCode: str = Field(examples=["27"])
    subDistrictName: str | None
    subDistrictLGDCode: str | None
    address: str | None
    pincode: str | None = Field(examples=["143001"])
    latitude: str | None = Field(description="Decimal degrees, as a string like HFR returns it")
    longitude: str | None
    hasIcuBeds: YesNo = Field(description='"No" also covers "not published", as on NHPR')
    abdmSoftware: YesNo
    totalBeds: int | None


class SearchResponse(BaseModel):
    facilities: list[FacilitySummary]
    totalFacilities: int
    numberOfPages: int
    message: str = "Request processed successfully"


class FacilityDetail(FacilitySummary):
    villageCityTownName: str | None
    villageCityTownLGDCode: str | None
    typeOfService: str | None
    phone: str | None = Field(examples=["+911832345678"])
    website: str | None
    photoUrl: str | None
    icuBeds: int | None
    ventilators: int | None
    systemsOfMedicine: list[str]
    specialities: list[str]
    firstSeenAt: str
    lastSeenAt: str


class StateItem(BaseModel):
    code: str
    name: str
    facilityCount: int


class StatesResponse(BaseModel):
    states: list[StateItem]


class DistrictsResponse(BaseModel):
    state: StateItem
    districts: list[StateItem]


class MasterItem(BaseModel):
    code: str | None
    name: str
    facilityCount: int


class MasterListResponse(BaseModel):
    type: str
    items: list[MasterItem]


class CountRow(BaseModel):
    code: str | None = None
    name: str
    facilities: int


class BedsRow(BaseModel):
    code: str
    name: str
    stateCode: str
    stateName: str
    facilities: int
    totalBeds: int
    icuBeds: int


class StatsResponse(BaseModel):
    totalFacilities: int
    totalBeds: int
    icuBeds: int
    facilitiesWithIcu: int
    byState: list[CountRow]
    byFacilityType: list[CountRow]
    byOwnership: list[CountRow]
    byStatus: list[CountRow]
    bedsByDistrict: list[BedsRow]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


class ErrorBody(BaseModel):
    code: str = Field(examples=["invalid_parameters"])
    message: str
    details: object | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
