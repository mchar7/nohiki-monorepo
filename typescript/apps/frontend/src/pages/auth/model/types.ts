export interface AuthListingItem {
  title: string;
  company_name: string;
  location_raw: string | null;
  work_arrangement: string | null;
  required_skills: string[];
  posted_at: string; // ISO 8601
  language: string | null;
}

export interface AuthListingsResponse {
  listings: AuthListingItem[];
  country: string; // Alpha-3 country code
}
