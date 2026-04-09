"""Raw scraped job posting text for business-domain roles."""

# ruff: noqa: E501

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import STRIP_EEO
from nohiki_test_utils.sample_data._types import RawJobPosting

FINANCIAL_ANALYST_HYBRID_POSTING = RawJobPosting(
    raw="""
Financial Analyst — Harbor Capital Group

About Harbor Capital Group

Harbor Capital Group is a diversified financial services firm managing $4.2B in assets across private equity, real estate, and credit strategies. Our finance and FP&A team provides analytical infrastructure that supports investment decisions, fund operations, and portfolio reporting for institutional limited partners. We are a 120-person firm with a disciplined culture of precision, accountability, and continuous improvement.

The Role

We are seeking a Financial Analyst to join our Financial Planning and Analysis team in New York. You will support the annual planning cycle, drive monthly variance analysis, and prepare investor reporting packages that require both analytical rigor and clear executive communication. This is a hybrid role with three days in our Midtown office and two days remote.

Responsibilities

- Build and maintain dynamic forecasting models for revenue, costs, and fund-level financial performance
- Lead monthly close support: consolidate actuals from multiple business units and explain variances vs. plan
- Partner with department heads and investment teams to develop and pressure-test annual budget assumptions
- Prepare quarterly board presentation materials including waterfall analyses and key financial metrics
- Design and maintain executive dashboards in Excel and Tableau for CFO and Managing Directors
- Support ad hoc analysis for strategic decisions including new fund formation, acquisitions, and capital allocation
- Automate recurring reporting workflows using Python or SQL to reduce manual data preparation time
- Collaborate with accounting and operations teams on intercompany allocations and regulatory reporting requirements

Requirements

- Bachelor's degree in Finance, Accounting, Economics, or related quantitative field
- 3-7 years of FP&A, investment banking, or financial analysis experience
- Advanced Excel modeling skills (dynamic arrays, Power Query, complex nested formulas)
- Strong SQL proficiency for querying financial data warehouses and operational databases
- Experience building board-level presentation materials and executive reporting packages
- CFA Level I or progress toward CFA charter preferred
- Python experience for data automation a significant plus
- Strong written and verbal communication skills; ability to translate complex financial data into clear narratives

Compensation and Benefits

- Annual salary: $90,000 — $120,000 based on experience
- Year-end discretionary bonus (typically 15-25% for this level)
- Comprehensive health, dental, and vision insurance
- 401(k) with 4% employer match
- Three weeks PTO plus 10 company holidays
- Hybrid schedule: 3 days in Midtown NYC office, 2 days remote
- CFA exam fee reimbursement and study leave
- Professional development budget for courses and certifications

Location: New York, NY — Hybrid (3 days in office required)

Harbor Capital Group is an equal opportunity employer committed to a diverse and inclusive workplace.
""",
    enrichment_transforms=(STRIP_EEO,),
)

MARKETING_MANAGER_REMOTE_POSTING = RawJobPosting(
    raw="""
Marketing Manager — Aurora Brand Collective

About Aurora Brand Collective

Aurora Brand Collective is a growth-stage marketing and brand management company building a portfolio of software and consumer product brands. We operate as an internal agency for six product lines and serve marketing leadership for two external brand clients. Our team of 35 marketers, analysts, and creatives works fully remote across the United States, with quarterly in-person team events. We are valued at $75M following a recent Series B round.

The Role

We are hiring a Marketing Manager to own performance and growth marketing across two of our B2B software brands. This is a fully remote, senior individual contributor role with cross-functional ownership over paid media, content programs, lifecycle campaigns, and pipeline analytics. You will report directly to the VP of Marketing and have significant autonomy over strategy and budget allocation.

Responsibilities

- Develop and execute quarterly integrated campaign plans across paid media, email, content, and event channels
- Own paid media performance (Google, LinkedIn, Meta) including budget pacing, creative testing, and bid strategy optimization
- Design and analyze A/B tests to improve landing page conversion, ad CTR, and email open/click rates
- Manage lifecycle and nurture programs in HubSpot, coordinating with sales on lead scoring thresholds and handoff criteria
- Produce weekly and monthly performance reports with variance analysis and actionable recommendations for leadership
- Collaborate with product marketing on positioning, ICP refinement, and competitive analysis
- Commission and edit long-form content (case studies, white papers, comparison pages) with external writers
- Monitor and report on branded and non-branded SEO performance using Semrush and Google Search Console

Requirements

- 5-10 years of B2B marketing experience with direct ownership of performance marketing programs
- Proven track record managing $500K+ annual paid media budget with demonstrable ROAS improvement
- Strong analytical skills with hands-on experience in HubSpot, Google Analytics 4, and campaign reporting
- Experience with A/B testing methodologies and statistical interpretation of marketing experiments
- Excellent written communication skills for internal strategy documents and external brand copy
- Self-directed and comfortable working asynchronously in a distributed team environment
- Familiarity with SEO strategy and content marketing programs a plus

Compensation and Benefits

- Annual salary: $100,000 — $130,000 based on experience
- Performance bonus tied to pipeline targets (up to 15% of base)
- Equity options (0.1-0.15% at current valuation)
- Health, dental, and vision insurance (employer covers 90% of premiums)
- 401(k) with 3% employer match
- Unlimited PTO with a 3-week recommended minimum
- $2,500 annual professional development budget
- Home office stipend: $1,500 one-time + $75/month internet allowance
- Quarterly team offsites (travel and accommodation covered)

Location: Remote — United States

Aurora Brand Collective is an equal opportunity employer. We are committed to building a team that reflects the diversity of our customer base.
""",
    enrichment_transforms=(STRIP_EEO,),
)

HR_DIRECTOR_HYBRID_POSTING = RawJobPosting(
    raw="""
Director of Human Resources — Atlanta Works Manufacturing

About Atlanta Works Manufacturing

Atlanta Works Manufacturing is a 1,400-employee industrial manufacturer producing precision components for automotive, aerospace, and defense OEM customers. With three production facilities in the Atlanta metro area and a corporate office in Midtown, we operate with rigorous quality, safety, and compliance standards. Our HR team of 14 manages the full people lifecycle for hourly production, skilled trades, and salaried professional employees.

The Role

We are seeking a Director of Human Resources to lead our talent strategy, labor compliance, workforce planning, and employee relations functions across all three Atlanta facilities. This is a senior leadership role reporting to the Chief Operating Officer, with dotted-line accountability to the CEO on culture and executive talent matters. You will manage a team of two HR Business Partners, an HR Generalist, and a Benefits and Payroll Manager.

Responsibilities

- Develop and execute a workforce plan aligned with production capacity requirements and multi-year growth projections
- Lead talent acquisition strategy for both hourly production roles and salaried engineering and management positions
- Manage and improve performance management programs including goal-setting frameworks, review cycles, and corrective action processes
- Ensure compliance with federal and state labor law requirements including OSHA, FLSA, FMLA, ADA, and EEO regulations
- Lead NLRA compliance and provide guidance on union avoidance strategies and grievance responses
- Oversee employee relations investigations, disciplinary processes, and conflict resolution protocols
- Partner with COO and facility managers on organizational design, restructuring, and workforce right-sizing initiatives
- Lead change management programs associated with ERP migration and new shift scheduling implementation
- Drive DEI initiatives including diverse sourcing pipelines, pay equity reviews, and inclusive management training

Requirements

- Bachelor's degree in Human Resources, Business Administration, or related field; Master's or MBA preferred
- 8-15 years of progressive HR experience with at least 4 years in a director or senior leadership role
- Manufacturing, industrial, or similarly regulated-industry HR experience required
- Thorough knowledge of federal and Georgia state employment law and labor relations
- SHRM-SCP or SPHR certification strongly preferred
- Experience managing HR functions across multiple sites or facilities
- Demonstrated ability to build collaborative relationships with operations leaders and frontline managers
- Strong coaching and conflict resolution skills; comfort managing sensitive employee situations

Compensation and Benefits

- Annual salary: $130,000 — $160,000 based on experience
- Annual performance bonus up to 15%
- Comprehensive health, dental, vision, and life insurance
- 401(k) with 5% employer match (immediate vesting)
- 20 days PTO plus 10 company holidays
- Hybrid schedule: primary presence at Midtown Atlanta corporate office (3 days/week) with regular facility visits
- Executive development program participation
- Relocation assistance for out-of-state candidates

Location: Atlanta, GA — Hybrid (Midtown office + multi-facility)

Atlanta Works Manufacturing is an equal opportunity employer and affirmative action employer. We celebrate workforce diversity.
""",
    enrichment_transforms=(STRIP_EEO,),
)

__all__ = [
    "FINANCIAL_ANALYST_HYBRID_POSTING",
    "HR_DIRECTOR_HYBRID_POSTING",
    "MARKETING_MANAGER_REMOTE_POSTING",
]
