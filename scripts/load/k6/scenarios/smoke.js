import { check, fail, group } from "k6";
import http from "k6/http";
import { Counter } from "k6/metrics";

const capacity429s = new Counter("capacity_429s");
const branchNames = [
  "B0_unauth",
  "B1_browse",
  "B2_fts_personalized",
  "B3_fts_cold",
  "B4_fts_warm",
  "B5_match_score",
  "B6_deep_page",
  "B7_control",
];

export const options = {
  discardResponseBodies: false,
  scenarios: {
    smoke: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 1,
      maxDuration: "2m",
    },
  },
  thresholds: {
    checks: [{ threshold: "rate==1", abortOnFail: true }],
    capacity_429s: [{ threshold: "count==0", abortOnFail: true }],
    dropped_iterations: [{ threshold: "count==0", abortOnFail: true }],
    http_req_failed: [{ threshold: "rate==0", abortOnFail: true }],
  },
};

function requireEnvironment(name) {
  const value = __ENV[name];
  if (!value) {
    fail(`${name} is required`);
  }
  return value;
}

export function setup() {
  return {
    accessToken: requireEnvironment("ACCESS_TOKEN"),
    baseUrl: requireEnvironment("BASE_URL").replace(/\/$/, ""),
    cookieName: __ENV.AUTH_COOKIE_NAME || "nohiki_at",
    listingId: requireEnvironment("LISTING_ID"),
    listingsPath: __ENV.LISTINGS_PATH || "/api/v1/listings",
    searchTerm: requireEnvironment("SEARCH_TERM"),
  };
}

function request(data, branch, suffix, expectedStatus = 200) {
  const headers = {};
  if (branch !== "B0_unauth") {
    headers.Cookie = `${data.cookieName}=${data.accessToken}`;
  }
  const response = http.get(`${data.baseUrl}${data.listingsPath}${suffix}`, {
    headers,
    responseCallback: http.expectedStatuses(expectedStatus),
    tags: { branch, plane: "local-kind", scenario: "T1_smoke" },
  });
  capacity429s.add(response.status === 429 ? 1 : 0, { branch });
  check(response, { [`${branch} returns ${expectedStatus}`]: (result) => result.status === expectedStatus });
  return response;
}

export default function (data) {
  group("eight branch contract", () => {
    request(data, branchNames[0], "", 401);
    request(data, branchNames[1], "?page=1&page_size=20");
    request(
      data,
      branchNames[2],
      `?q=${encodeURIComponent(data.searchTerm)}&show_dismissed=false&sort=posted_at&page=1&page_size=20`,
    );
    const cold = request(
      data,
      branchNames[3],
      `?q=${encodeURIComponent(data.searchTerm)}&show_dismissed=true&sort=posted_at&page=1&page_size=20`,
    );
    const warm = request(
      data,
      branchNames[4],
      `?q=${encodeURIComponent(data.searchTerm)}&show_dismissed=true&sort=posted_at&page=1&page_size=20`,
    );
    check(warm, {
      "warm body equals paired cold body": () => warm.body === cold.body,
    });
    request(data, branchNames[5], "?sort=match_score&page=1&page_size=20");
    request(data, branchNames[6], "?page=25&page_size=20");
    request(data, branchNames[7], `/${encodeURIComponent(data.listingId)}`);
  });
}
