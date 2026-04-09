"""Raw scraped job posting text for skilled-trades roles."""

# ruff: noqa: E501

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import STRIP_EEO
from nohiki_test_utils.sample_data._types import RawJobPosting

ELECTRICIAN_ONSITE_POSTING = RawJobPosting(
    raw="""
Licensed Electrician — Suncrest Facilities Group

About Suncrest Facilities Group

Suncrest Facilities Group provides integrated facilities management services for industrial parks, commercial office campuses, and healthcare facilities across central Texas. Our 320-person operations team manages over 8 million square feet of built environment, delivering preventive maintenance, emergency response, and capital project support for more than 140 client sites. We are expanding our electrical team in Austin following several major contract wins in the semiconductor and biotech corridor.

The Role

We are hiring a Licensed Electrician to join our Austin facilities team. You will perform installation, diagnostics, and scheduled maintenance for industrial control systems, distribution panels, emergency power systems, and low-voltage infrastructure across multiple client sites. This is a full-time, on-site role with a consistent day-shift schedule and a structured on-call rotation for after-hours emergencies.

Responsibilities

- Install, inspect, and repair electrical systems including switchgear, distribution panels, branch circuits, and motor controls in industrial and commercial environments
- Perform preventive maintenance on UPS systems, generators, automatic transfer switches, and backup power infrastructure
- Diagnose and troubleshoot faults in three-phase power systems, variable frequency drives, and PLC-controlled equipment
- Read and interpret electrical blueprints, single-line diagrams, and equipment schematics
- Complete digital work orders and inspection documentation using Computerized Maintenance Management System (CMMS)
- Coordinate with project supervisors, safety managers, and client facilities representatives during planned outages
- Participate in emergency response rotation and respond to after-hours electrical incidents as scheduled
- Maintain compliance with NEC, NFPA 70E, and site-specific safety standards

Requirements

- Texas Journeyman Electrician license (required) or Master Electrician license (preferred)
- 3-12 years of commercial or industrial electrical experience
- Working knowledge of the National Electrical Code and NFPA 70E arc flash safety standards
- Experience with panel installations, conduit bending, and low-voltage systems
- Ability to operate aerial lift equipment and work safely at heights (training provided if needed)
- Valid Texas driver's license and clean driving record
- Strong troubleshooting skills and ability to work independently on multi-site assignments
- OSHA 10 or 30 certification a plus

Compensation and Benefits

- Hourly pay: $28.00 — $38.00 based on license level and experience ($55,000 — $75,000 annualized)
- Overtime opportunities available (average 5-10 hours/week)
- Comprehensive health, dental, and vision insurance (employee: $35/month contribution)
- 401(k) with 3% employer match after 90 days
- Company vehicle and fuel card for site travel
- Paid tool allowance ($500/year) and PPE provided
- NFPA 70E and NEC training reimbursement
- 10 days PTO in year one, accruing to 15 days after two years
- Paid holidays (8 per year)

Location: Austin, TX — On-site (multi-site service territory)

Suncrest Facilities Group is an equal opportunity employer. We are committed to safety, quality, and the professional development of every team member.
""",
    enrichment_transforms=(STRIP_EEO,),
)

HVAC_TECHNICIAN_POSTING = RawJobPosting(
    raw="""
HVAC Service Technician — Desert Air Services

About Desert Air Services

Desert Air Services is a family-owned HVAC contractor serving residential and light commercial customers across the Phoenix metropolitan area. Since 2001, we have built a reputation for honest, reliable service and same-day response. Our team of 45 technicians handles everything from seasonal tune-ups and filter replacements to full system installations and emergency breakdowns. We use ServiceTitan for dispatch and digital invoicing, and invest in ongoing NATE certification training for our entire field team.

The Role

We are looking for an HVAC Service Technician — ideal for someone who is 1-3 years into their career and ready to grow with a team that genuinely invests in its people. You will handle service calls for residential maintenance, diagnostic repairs, and light commercial equipment. Dispatch operates on a structured day-shift schedule with rotating on-call for weekend emergencies.

Responsibilities

- Perform routine maintenance services: refrigerant checks, coil cleaning, filter inspection, electrical connection testing, and airflow balancing
- Diagnose HVAC system failures including compressor issues, refrigerant leaks, control board faults, and ductwork problems
- Install replacement equipment including condensing units, air handlers, and thermostats for residential customers
- Complete digital service reports and customer invoices in ServiceTitan at each job site
- Educate customers on maintenance plans, energy-saving recommendations, and system lifecycle expectations
- Coordinate with the parts and warehouse team for same-day parts procurement when needed
- Participate in weekend on-call rotation (one weekend per month at this level)

Requirements

- EPA 608 Universal Certification (required)
- 1-4 years of HVAC field service experience
- Ability to work safely in Phoenix summer outdoor conditions (110°F+)
- Valid Arizona driver's license with clean MVR
- Strong customer communication skills and professional appearance
- NATE certification preferred but not required (we sponsor certification exams)
- Experience with ServiceTitan or similar field service software a plus
- Comfort working on ladders, rooftops, and crawl spaces

Compensation and Benefits

- Hourly pay: $20.00 — $28.00 based on experience and certification ($40,000 — $55,000 annualized)
- Spiff bonuses for maintenance agreements and accessory sales
- Full health insurance coverage (employee premiums covered 80% by company)
- Company-provided service van, fuel card, and uniform allowance
- iPhone and iPad with ServiceTitan app
- NATE exam fees covered and paid study time
- 401(k) available after 6 months (no employer match currently — under review for 2026)
- 5 days PTO in year one, increasing to 10 after one year
- Paid training days for manufacturer certification programs

Location: Phoenix, AZ — On-site (residential and commercial service territory)

Desert Air Services is an equal opportunity employer and a proud veteran-friendly employer.
""",
    enrichment_transforms=(STRIP_EEO,),
)

__all__ = [
    "ELECTRICIAN_ONSITE_POSTING",
    "HVAC_TECHNICIAN_POSTING",
]
