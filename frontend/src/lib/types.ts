// Shapes returned by the API. Field names follow the HFR search response.

export type YesNo = "Yes" | "No";

export interface FacilitySummary {
  facilityId: string;
  facilityName: string;
  facilityStatus: string;
  ownership: string | null;
  ownershipCode: string | null;
  facilityType: string | null;
  facilityTypeCode: string | null;
  systemOfMedicine: string | null;
  systemOfMedicineCode: string | null;
  stateName: string;
  stateLGDCode: string;
  districtName: string;
  districtLGDCode: string;
  subDistrictName: string | null;
  subDistrictLGDCode: string | null;
  villageCityTownName: string | null;
  villageCityTownLGDCode: string | null;
  address: string | null;
  pincode: string | null;
  latitude: string | null;
  longitude: string | null;
  hasIcuBeds: YesNo;
  abdmSoftware: YesNo;
  totalBeds: number | null;
}

export interface SearchResponse {
  facilities: FacilitySummary[];
  totalFacilities: number;
  numberOfPages: number;
  message: string;
}

export interface FacilityDetail extends FacilitySummary {
  typeOfService: string | null;
  phone: string | null;
  website: string | null;
  photoUrl: string | null;
  icuBeds: number | null;
  ventilators: number | null;
  systemsOfMedicine: string[];
  specialities: string[];
  firstSeenAt: string;
  lastSeenAt: string;
}

export interface Place {
  code: string;
  name: string;
  facilityCount: number;
}

export interface MasterItem {
  code: string | null;
  name: string;
  facilityCount: number;
}

export type MasterType = "ownership" | "facility-types" | "systems-of-medicine" | "specialities";

export type Masters = Record<MasterType, MasterItem[]>;

export interface CountRow {
  code: string | null;
  name: string;
  facilities: number;
}

export interface BedsRow {
  code: string;
  name: string;
  stateCode: string;
  stateName: string;
  facilities: number;
  totalBeds: number;
  icuBeds: number;
}

export interface Stats {
  totalFacilities: number;
  totalBeds: number;
  icuBeds: number;
  facilitiesWithIcu: number;
  byState: CountRow[];
  byFacilityType: CountRow[];
  byOwnership: CountRow[];
  byStatus: CountRow[];
  bedsByDistrict: BedsRow[];
}
