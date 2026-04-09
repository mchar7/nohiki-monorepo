"""Raw scraped job posting text for healthcare roles."""

# ruff: noqa: E501

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import (
    STRIP_EEO,
    fix_unicode_artifacts,
)
from nohiki_test_utils.sample_data._types import RawJobPosting

NURSE_ICU_ONSITE_POSTING = RawJobPosting(
    raw="""
Registered Nurse, ICU — Meridian Health Systems

About Meridian Health Systems

Meridian Health Systems is a 14-hospital integrated health network serving the greater Houston metropolitan area. With over 6,000 nurses across our network, we are recognized for clinical excellence, nursing-led governance, and a culture that puts patients and caregivers first. Our ICU program has achieved Magnet designation for five consecutive years and maintains a 1:2 nurse-to-patient ratio in critical care.

The Role

We are seeking experienced ICU Registered Nurses to join our high-acuity Medical-Surgical Intensive Care Unit. You will deliver evidence-based critical care to post-surgical, trauma, and complex medical patients, collaborating with intensivists, respiratory therapists, pharmacists, and care coordinators to optimize outcomes. This is a full-time role with day, evening, and night shift options available.

Responsibilities

- Perform comprehensive patient assessments at admission and throughout each shift, documenting in Epic EHR with accuracy and timeliness
- Administer intravenous medications, titrate vasoactive drips, and manage pain and sedation protocols per physician orders
- Monitor ventilated patients, interpret waveforms, and notify intensivists of status changes requiring intervention
- Participate in daily interdisciplinary rounds, contributing nursing observations to care planning discussions
- Maintain invasive lines and catheters using evidence-based infection prevention practices
- Educate patients and families on care plans, discharge expectations, and self-management strategies
- Precept new nurses and nursing students rotating through the unit

Requirements

- Current Texas RN license (or compact license) in good standing
- 2+ years of ICU, CTICU, or CVICU experience
- BLS and ACLS certification (required before start date)
- Proficiency with Epic EHR; experience with Philips IntelliVue or similar monitoring systems preferred
- CCRN certification preferred but not required
- Strong critical-thinking skills and comfort in rapidly evolving patient situations
- Excellent interpersonal and communication skills for diverse patient populations

Compensation and Benefits

- Hourly rate: $33.00 — $43.00 (based on experience)
- $65,000 — $85,000 annualized for full-time (40 hours/week)
- Shift differentials: $3.50/hr evenings, $5.00/hr nights, $4.00/hr weekends
- Comprehensive health, dental, and vision insurance with employer-funded HSA
- Tuition reimbursement up to $5,250/year and CCRN certification sponsorship
- 403(b) retirement plan with 5% employer match
- 160 hours PTO in year one, increasing annually
- Relocation assistance available for qualified candidates

Location: Houston, TX — On-site only (ICU environment)

Meridian Health Systems is an equal opportunity employer. We are committed to building a workforce that reflects the diverse communities we serve.
""",
    enrichment_transforms=(STRIP_EEO,),
)

PHYSICAL_THERAPIST_POSTING = RawJobPosting(
    raw="""
Physical Therapist — Blue Mountain Rehabilitation

About Blue Mountain Rehabilitation

Blue Mountain Rehabilitation is an award-winning outpatient and home health rehabilitation provider serving Colorado's Front Range for over 20 years. Our multidisciplinary team of physical therapists, occupational therapists, and speech-language pathologists delivers outcome-driven care for orthopedic, neurological, and post-surgical patients. We are proud of our 97% patient satisfaction rating and evidence-based clinical standards that support swift, meaningful recovery.

The Role

We are hiring a licensed Physical Therapist to join our outpatient orthopedic and neurological rehabilitation team in Denver. You will evaluate patients referred by physicians and specialists, design individualized treatment programs, and track functional progress toward measurable milestones. This is a full-time, salaried position with excellent work-life balance and a patient panel of 10-14 patients per day.

Responsibilities

- Conduct thorough initial evaluations including range of motion, strength, balance, and gait assessments
- Develop evidence-based treatment plans aligned with patient goals and physician protocols
- Deliver manual therapy, therapeutic exercise, modalities, and neuromuscular re-education
- Document evaluation findings, progress notes, and discharge summaries in compliance with insurance and regulatory requirements
- Educate patients and caregivers on home exercise programs and injury prevention strategies
- Collaborate with orthopedic surgeons, neurologists, and primary care providers through structured referral loops
- Participate in weekly case conferencing and quality improvement initiatives
- Precept DPT students on clinical rotation placements

Requirements

- Doctor of Physical Therapy (DPT) degree from an accredited program
- Current Colorado PT license (or eligibility — we support licensure transfer)
- 2+ years of experience in outpatient orthopedic or neurological rehabilitation
- Proficiency in manual therapy techniques (joint mobilization, soft tissue mobilization)
- Strong documentation habits and familiarity with EMR systems
- OCS or CSCS certification a plus
- Excellent patient communication and culturally competent care delivery

Compensation and Benefits

- Annual salary: $70,000 — $90,000 based on experience
- Performance bonuses based on patient outcomes and satisfaction scores
- Full health, dental, and vision coverage
- Student loan repayment assistance up to $5,000/year
- CEU stipend ($1,500 annually) and paid conference days
- 401(k) with 4% employer match
- Flexible scheduling with no weekend requirement
- Mentorship program for new graduates

Location: Denver, CO — On-site (clinic-based with optional home health)

Blue Mountain Rehabilitation is an equal opportunity employer and values clinician well-being as much as patient outcomes.
""",
    enrichment_transforms=(STRIP_EEO,),
)

PHARMACIST_HYBRID_POSTING = RawJobPosting(
    raw="""
Clinical Pharmacist \u2014 Northside Care Network

About Northside Care Network

Northside Care Network is a Chicago-area integrated care system serving over 200,000 patients annually across five hospitals and 30+ outpatient clinics. Our pharmacy division is nationally recognized for medication safety leadership and clinical program innovation. We\u2019re expanding our clinical pharmacy residency program, publish regularly in peer-reviewed journals, and invest heavily in tools that support evidence-based pharmacotherapy.

The Role

We\u2019re recruiting a Clinical Pharmacist to join our Oncology\u00a0and Chronic Care pharmacy team. This is a hybrid role\u2014combining on-site participation in inpatient rounds and clinics with remote chart review, provider consults, and formulary work. You\u2019ll work at the intersection of clinical care and pharmacy operations \u2014 reviewing complex medication regimens, advising on therapy optimization, and contributing to initiatives that measurably reduce adverse drug events.

Responsibilities

- Conduct pharmacotherapy reviews for oncology, cardiology, and chronic disease patient panels
- Participate in interdisciplinary rounds at least three days per week, providing real-time medication consultation to physicians and advanced practice providers
- Evaluate drug therapy for efficacy, toxicity, interactions, and cost-effectiveness using evidence-based guidelines
- Develop and maintain clinical protocols and formulary policies in collaboration with the P&T Committee
- Lead medication reconciliation reviews for high-risk admissions and transitions of care
- Mentor PharmD interns and PGY1 residents on clinical rotations
- Monitor quality metrics and report outcomes to pharmacy leadership quarterly
- Perform remote chart reviews and provider outreach on assigned chronic care panels

Requirements

- Doctor of Pharmacy (PharmD) from an ACPE-accredited program
- Current Illinois pharmacist license in good standing
- 5+ years of clinical pharmacy experience in hospital or integrated care settings
- PGY1 pharmacy residency (required); PGY2 in oncology or ambulatory care strongly preferred
- Proficiency with Cerner Millennium (pharmacy and clinical modules)
- Board Certified Pharmacotherapy Specialist (BCPS) or BCOP certification preferred
- Strong clinical judgment, interdisciplinary communication skills, and comfort with high-complexity patients
- Experience in formulary management and P&T Committee support

Compensation and Benefits

- Annual salary: $120,000 — $140,000 based on experience and board certification
- Annual performance bonus up to 8%
- Comprehensive health, dental, and vision insurance
- 403(b) with 6% employer match
- Tuition reimbursement and BCPS/BCOP exam sponsorship
- CME stipend ($2,500/year) and 5 paid CME days annually
- Hybrid schedule: 3 days on-site, 2 days remote (flexible based on clinical needs)
- Structured leadership development pathway for senior and manager roles

Location: Chicago, IL — Hybrid (3 days on-site, 2 days remote)

Northside Care Network is an equal opportunity employer committed to patient safety and pharmacist well-being.
""",
    enrichment_transforms=(
        fix_unicode_artifacts(),
        STRIP_EEO,
    ),
)

__all__ = [
    "NURSE_ICU_ONSITE_POSTING",
    "PHARMACIST_HYBRID_POSTING",
    "PHYSICAL_THERAPIST_POSTING",
]
