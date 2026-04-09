"""Raw scraped job posting text for leadership roles."""

# ruff: noqa: E501

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import STRIP_EEO
from nohiki_test_utils.sample_data._types import RawJobPosting

DIRECTOR_ENGINEERING_POSTING = RawJobPosting(
    raw="""
Director of Engineering — Lighthouse Platform Group

About Lighthouse Platform Group

Lighthouse Platform Group builds enterprise workflow and integration infrastructure used by over 800 mid-market and enterprise customers. Our engineering organization comprises 120 engineers across platform, data, developer experience, and product engineering teams. We are a Series D company at $280M ARR, operating in a growth phase that demands engineering leadership capable of scaling people, processes, and architecture simultaneously.

The Role

We are hiring a Director of Engineering to own the Platform, Data Infrastructure, and Developer Experience engineering organizations — approximately 45 engineers and 4 engineering managers reporting into this role. You will set technical strategy, manage engineering managers, and partner closely with Product, Design, and Go-to-Market leadership to align delivery with business outcomes. This is a highly visible leadership role reporting directly to the VP of Engineering.

Responsibilities

- Lead three engineering teams (Platform Infrastructure, Data Engineering, Developer Experience) with direct management of 4 Engineering Managers
- Define and execute multi-year technical strategy for platform reliability, developer productivity, and data infrastructure
- Establish and uphold engineering standards for architecture, security, deployment, and incident management
- Partner with product leadership to develop quarterly roadmaps that balance technical investment with customer-facing feature delivery
- Drive cross-team architectural initiatives including service mesh migration, data platform modernization, and internal developer tooling
- Build and sustain a high-performance engineering culture with strong retention, clear growth ladders, and inclusive hiring practices
- Lead engineering incident response processes, post-mortems, and reliability improvement programs
- Represent engineering priorities in executive forums and communicate technical constraints clearly to non-technical stakeholders

Requirements

- 10+ years of software engineering experience, with 4+ years in engineering management roles (including experience managing managers)
- Demonstrated track record of leading platform, infrastructure, or developer experience organizations
- Strong grasp of distributed systems, cloud-native architectures, and modern data infrastructure
- Experience operating systems at scale: multi-tenant SaaS, high-availability services, large-volume data pipelines
- Proven ability to build organizational culture, mentor engineering managers, and improve team health and retention
- Excellent communication and stakeholder management skills; comfortable influencing at VP and C-suite level
- Experience with technical roadmap planning, OKR frameworks, and cross-functional delivery
- Bachelor's or Master's in Computer Science or equivalent engineering experience

Technical Context

Our stack includes Python, Go, PostgreSQL, Kafka, Kubernetes (GKE), Terraform, and a mix of internal and open-source tooling. Experience with one or more of these is valued but not required — we hire leaders who can learn and adapt.

Compensation and Benefits

- Base salary: $250,000 — $300,000 depending on experience
- Annual performance bonus up to 20% of base
- RSU equity grant with 4-year vesting and 1-year cliff
- Comprehensive health, dental, and vision insurance (100% employer-paid for employee)
- 401(k) with 6% employer match (immediate vesting)
- Unlimited PTO with a recommended 3-week minimum
- Hybrid schedule: 3 days in-office (NYC) with flexible remote for 2 days
- Generous L&D budget including conference attendance and executive coaching
- Parental leave: 16 weeks primary caregiver, 8 weeks secondary caregiver

Location: New York, NY — Hybrid (3 days in-office required)

Lighthouse Platform Group is committed to building a diverse and equitable engineering organization. We encourage applications from candidates of all backgrounds and experiences.
""",
    enrichment_transforms=(STRIP_EEO,),
)

VP_PRODUCT_REMOTE_POSTING = RawJobPosting(
    raw="""
VP of Product — Northstar Ventures

About Northstar Ventures

Northstar Ventures builds a portfolio of B2B workflow automation products serving operations, finance, and HR teams at mid-market companies. Our flagship product, FlowCore, is used by 1,200 customers and generates $40M ARR. We are a fully remote-first company with 75 employees across 12 countries, backed by $120M in funding from leading enterprise software investors. We are entering a critical phase of product portfolio expansion and need strong product leadership to guide our evolution.

The Role

We are seeking a VP of Product to lead all product management functions across the FlowCore portfolio and three emerging product lines currently in development. You will own product strategy, discovery practices, roadmap governance, and go-to-market coordination with our Sales and Marketing organizations. This is an executive role reporting to the CEO with a seat on the leadership team.

Responsibilities

- Define and maintain a coherent multi-year product strategy that aligns with our $200M ARR and IPO-readiness goals
- Lead a team of 8 product managers across four product areas, including one Group PM and two Sr. PMs
- Own the product planning cadence: quarterly OKRs, roadmap reviews, build-vs-buy decisions, and resource allocation
- Drive customer discovery and research programs that continuously inform product direction and prioritization
- Develop and maintain pricing strategy in collaboration with Finance and Sales leadership
- Partner with Engineering on delivery practices, capacity planning, and technical debt tradeoffs
- Represent product direction externally: analyst briefings, customer advisory boards, and partnership conversations
- Build a high-performing, customer-obsessed product organization with strong hiring, onboarding, and career development practices

Requirements

- 12+ years of product management experience, including 3+ years as a VP or head of product function
- Proven track record of building and scaling B2B SaaS products from growth to maturity
- Deep experience with product-led growth, pricing strategy, and go-to-market alignment
- Strong customer empathy and hands-on familiarity with enterprise buyer and user personas
- Experience leading product managers and building product organizations at 50+ person companies
- Excellent storytelling and executive communication skills; board presentation experience preferred
- Familiarity with data-driven product development (experimentation, funnel analytics, retention modeling)
- Remote leadership experience and ability to build culture across distributed, async teams

Compensation and Benefits

- Base salary: $280,000 — $350,000 depending on experience
- Annual performance bonus up to 25% of base
- Significant equity stake (options with preferential terms for VP-level hires)
- Comprehensive health, dental, and vision insurance
- 401(k) with 5% employer match
- Fully remote with flexible hours
- Annual team offsite and quarterly leadership summits
- $5,000 annual L&D budget plus executive coaching
- Home office setup stipend ($3,000 one-time) and monthly internet/phone allowance
- Generous parental leave: 20 weeks for all caregivers

Location: Remote — United States (or Canada with employer of record)

Northstar Ventures is an equal opportunity employer. We actively recruit candidates from underrepresented backgrounds in product leadership.
""",
    enrichment_transforms=(STRIP_EEO,),
)

__all__ = [
    "DIRECTOR_ENGINEERING_POSTING",
    "VP_PRODUCT_REMOTE_POSTING",
]
