"""Raw scraped job posting text for software and technology roles."""

# ruff: noqa: E501

from __future__ import annotations

from nohiki_test_utils.sample_data._enrichment import (
    STRIP_EEO,
    strip_html_tags,
)
from nohiki_test_utils.sample_data._types import RawJobPosting

SENIOR_PYTHON_REMOTE_POSTING = RawJobPosting(
    raw="""
Senior Python Engineer - Backend Infrastructure

About Cascade Infrastructure Labs

Cascade Infrastructure Labs is a leading provider of cloud-native infrastructure solutions, serving over 500 enterprise customers worldwide. Our platform processes billions of events daily, powering mission-critical applications for Fortune 500 companies. We're a remote-first company with a strong engineering culture focused on technical excellence, collaboration, and continuous learning.

The Role

We're seeking a Senior Python Engineer to join our Backend Infrastructure team. You'll be responsible for designing and building highly scalable microservices that power our event processing platform. This role offers the opportunity to work on challenging distributed systems problems, mentor junior engineers, and shape the technical direction of our core infrastructure.

You'll work closely with our platform team to build resilient, high-performance services using modern Python frameworks and cloud-native technologies. Your contributions will directly impact millions of users and help us scale to the next level of growth.

Key Responsibilities

- Design, develop, and maintain scalable Python microservices using FastAPI and async frameworks
- Build and optimize event-driven architectures using Kafka and Redis
- Implement robust monitoring, logging, and observability solutions
- Collaborate with cross-functional teams to deliver high-quality features
- Mentor junior engineers and contribute to technical documentation
- Participate in on-call rotation and incident response
- Drive technical decisions and architectural improvements

Requirements

- 5+ years of professional Python development experience
- Strong expertise in FastAPI, Django, or similar web frameworks
- Deep understanding of distributed systems and microservices architecture
- Production experience with PostgreSQL, Redis, and message queues (Kafka, RabbitMQ)
- Proficiency with Docker, Kubernetes, and cloud platforms (AWS, GCP, or Azure)
- Experience with async/await patterns and concurrent programming
- Strong understanding of RESTful API design and best practices
- Excellent problem-solving skills and attention to detail
- Strong communication skills and ability to work in a remote team environment

Nice to Have

- Experience with gRPC and Protocol Buffers
- Knowledge of observability tools (Prometheus, Grafana, Jaeger)
- Contributions to open-source Python projects
- Experience with CI/CD pipelines and infrastructure as code
- Familiarity with machine learning or data processing pipelines

Benefits

- Competitive salary range: $150,000 - $180,000 based on experience
- Comprehensive health, dental, and vision insurance
- 401(k) with company match
- Unlimited PTO and flexible work schedule
- Home office stipend and equipment budget
- Professional development budget for conferences and courses
- Remote-first culture with annual company retreats
- Stock options in a fast-growing company

Location: Remote (United States)

Cascade Infrastructure Labs is an equal opportunity employer. We celebrate diversity and are committed to creating an inclusive environment for all employees.
""",
    enrichment_transforms=(STRIP_EEO,),
)

JUNIOR_FRONTEND_HYBRID_POSTING = RawJobPosting(
    raw="""
Junior Frontend Developer - React & TypeScript

About Pixel Harbor Studio

Pixel Harbor Studio is a San Francisco-based design technology company building the next generation of component libraries and design tools. Our products are used by thousands of designers and developers at companies like Airbnb, Stripe, and Shopify. We're a tight-knit team of 40 people passionate about creating beautiful, accessible user interfaces.

The Role

We're looking for a Junior Frontend Developer to join our component library team. This is an excellent opportunity for someone early in their career who wants to work on open-source design systems, learn from experienced engineers, and contribute to tools used by thousands of developers worldwide.

You'll work on our flagship React component library, building accessible UI components, improving documentation, and helping maintain our design token system. This hybrid role offers 3 days in our San Francisco office and 2 days remote, giving you the best of both worlds.

What You'll Do

- Build and maintain React components using TypeScript and modern CSS
- Write comprehensive unit tests and integration tests
- Improve component documentation and interactive examples
- Collaborate with designers to implement design specifications
- Participate in code reviews and pair programming sessions
- Contribute to our design token system and theming infrastructure
- Help maintain our Storybook documentation site

Requirements

- 1-3 years of professional frontend development experience
- Strong proficiency in React and TypeScript
- Solid understanding of HTML, CSS, and JavaScript fundamentals
- Experience with modern CSS (Flexbox, Grid, CSS-in-JS)
- Familiarity with Git and version control workflows
- Understanding of web accessibility standards (WCAG)
- Strong attention to detail and design sensibility
- Excellent communication and collaboration skills

Nice to Have

- Experience with Tailwind CSS or other utility-first frameworks
- Knowledge of design systems and component libraries
- Familiarity with testing libraries (Jest, React Testing Library, Playwright)
- Experience with build tools (Vite, Webpack, Rollup)
- Contributions to open-source projects
- Understanding of design tokens and theming

What We Offer

- Salary range: $80,000 - $100,000 based on experience
- Comprehensive health, dental, and vision coverage
- 401(k) retirement plan
- Flexible hybrid schedule (3 days office, 2 days remote)
- Commuter benefits and lunch provided on office days
- Learning and development budget
- Modern office in SOMA with standing desks and ergonomic equipment
- Regular team events and activities
- Equity compensation

Location: San Francisco, CA (Hybrid - 3 days in office)

Pixel Harbor Studio is an equal opportunity employer. We are committed to building an inclusive team and welcome applications from candidates of all backgrounds.
""",
    enrichment_transforms=(STRIP_EEO,),
)

STAFF_PLATFORM_HYBRID_POSTING = RawJobPosting(
    raw="""
<strong>Staff Software Engineer - Platform Infrastructure</strong>

About Nimbus Data Systems

<p>Nimbus Data Systems is transforming how enterprises build and deploy cloud applications. Our platform serves over 1,000 customers and processes 50&#43; billion API requests monthly. We&#39;re a Series C company backed by leading venture capital firms, with a team of 200&#43; employees across engineering, product, and go-to-market functions.</p>

The Role

<p>We&#39;re seeking a Staff Software Engineer to lead technical initiatives on our Platform Infrastructure team. This is a high-impact role where you&#39;ll architect and build the foundational systems that power our entire product suite. You&#39;ll work on challenging problems at scale, mentor senior engineers, and drive technical strategy across multiple teams.</p>

<p>As a Staff Engineer, you&#39;ll have significant autonomy and influence over our technical direction. You&#39;ll collaborate with engineering leadership to make architectural decisions, establish best practices, and ensure our platform can scale to support 10x growth.</p>

What You&#39;ll Own

<ul>
<li>Design and implement large-scale distributed systems &amp; infrastructure</li>
<li>Lead cross-team technical initiatives and architectural improvements</li>
<li>Build highly available, low-latency services processing millions of requests per second</li>
<li>Establish engineering standards, patterns, and best practices</li>
<li>Mentor senior and mid-level engineers across multiple teams</li>
<li>Drive technical roadmap and make build-vs-buy decisions</li>
<li>Participate in on-call rotation and lead incident response efforts</li>
<li>Collaborate with product&nbsp;and engineering leadership on strategic planning</li>
</ul>

Requirements

- 8+ years of software engineering experience with 2+ years at Staff level or equivalent
- Expert-level proficiency in Python, Go, or Java
- Deep expertise in distributed systems, microservices, and cloud-native architectures
- Production experience operating services at significant scale (millions of QPS)
- Strong understanding of Kubernetes, service mesh, and container orchestration
- Experience with observability, monitoring, and distributed tracing
- Proven track record of leading large technical projects and mentoring engineers
- Excellent system design and architectural skills
- Strong communication skills and ability to influence technical decisions
- Experience with infrastructure as code and GitOps workflows

Technical Stack

- Languages: Python, Go, Rust
- Infrastructure: Kubernetes, Istio, Terraform, ArgoCD
- Data: PostgreSQL, Redis, Kafka, ClickHouse
- Observability: Prometheus, Grafana, Jaeger, OpenTelemetry
- Cloud: AWS (primary), GCP

What We Offer

- Competitive compensation: $200,000 - $250,000 base salary
- Significant equity package (RSUs)
- Comprehensive benefits including health, dental, vision, and life insurance
- 401(k) with generous company match
- Flexible hybrid schedule (3 days in office, 2 days remote)
- Unlimited PTO with minimum vacation policy
- Parental leave and family support programs
- Professional development budget and conference attendance
- Modern office in downtown San Francisco with catered meals
- Top-tier equipment and home office setup
- Annual company offsites and team building events

Location: San Francisco, CA (Hybrid - 3 days in office required)

Nimbus Data Systems is proud to be an equal opportunity employer committed to diversity and inclusion.
""",
    enrichment_transforms=(
        strip_html_tags(),
        STRIP_EEO,
    ),
)

DATA_SCIENTIST_REMOTE_POSTING = RawJobPosting(
    raw="""
Data Scientist - Machine Learning & AI

About SignalPath AI

SignalPath AI is a leading data science and AI company helping Fortune 500 companies leverage machine learning to solve complex business problems. Our team of 150+ data scientists, ML engineers, and researchers works on diverse projects spanning healthcare, finance, retail, and technology sectors. We're known for our rigorous approach to ML engineering and our commitment to responsible AI practices.

The Role

We're looking for a Data Scientist to join our Machine Learning team. You'll work on cutting-edge ML projects, from building recommendation systems to developing predictive models for healthcare outcomes. This role offers the opportunity to work with diverse datasets, apply state-of-the-art ML techniques, and see your models deployed in production environments serving millions of users.

You'll collaborate with cross-functional teams including ML engineers, product managers, and domain experts to deliver end-to-end ML solutions. This is a fully remote position with opportunities to work on high-impact projects across multiple industries.

Key Responsibilities

- Design, develop, and deploy machine learning models for various business applications
- Conduct exploratory data analysis and feature engineering on large-scale datasets
- Build and optimize recommendation systems, classification models, and time series forecasting
- Collaborate with ML engineers to productionize models and ensure scalability
- Communicate findings and insights to technical and non-technical stakeholders
- Stay current with latest ML research and apply relevant techniques to business problems
- Mentor junior data scientists and contribute to team knowledge sharing

Requirements

- 4+ years of experience in data science or machine learning roles
- Strong proficiency in Python and ML libraries (scikit-learn, TensorFlow, PyTorch)
- Deep understanding of statistical modeling, hypothesis testing, and experimental design
- Experience with deep learning architectures (CNNs, RNNs, Transformers)
- Proficiency in SQL and experience with large-scale data processing (Spark, Dask)
- Strong understanding of ML ops practices and model deployment
- Experience with cloud platforms (AWS SageMaker, GCP Vertex AI, or Azure ML)
- Excellent communication skills and ability to explain complex concepts clearly
- Master's or PhD in Computer Science, Statistics, Mathematics, or related field preferred

Technical Skills

- Programming: Python, R, SQL
- ML Frameworks: TensorFlow, PyTorch, scikit-learn, XGBoost, LightGBM
- Data Processing: Pandas, NumPy, Spark, Dask
- Visualization: Matplotlib, Seaborn, Plotly
- MLOps: MLflow, Weights & Biases, Kubeflow
- Cloud: AWS, GCP, Azure

Nice to Have

- Experience with NLP and large language models (BERT, GPT, etc.)
- Knowledge of causal inference and experimentation frameworks
- Experience with graph neural networks or reinforcement learning
- Publications in top-tier ML conferences (NeurIPS, ICML, ICLR)
- Contributions to open-source ML projects
- Experience with responsible AI and model interpretability

What We Offer

- Competitive salary: $130,000 - $160,000 based on experience
- Performance-based bonuses and profit sharing
- Comprehensive health, dental, and vision insurance
- 401(k) with company match
- Fully remote work with flexible hours
- Home office stipend and equipment budget
- Professional development budget for courses, conferences, and certifications
- Access to GPU compute resources and cloud credits
- Collaborative culture with regular virtual team events
- Opportunities to work on diverse, challenging projects

Location: Remote (United States)

SignalPath AI is an equal opportunity employer committed to building a diverse and inclusive workplace where everyone can thrive.
""",
    enrichment_transforms=(STRIP_EEO,),
)

DEVOPS_ENGINEER_HYBRID_POSTING = RawJobPosting(
    raw="""
DevOps Engineer - Infrastructure & Automation

About Western Grid Technologies

Western Grid Technologies provides enterprise software solutions for logistics and supply chain management. Our platform powers operations for major retailers and manufacturers, processing millions of transactions daily. We're a 300-person company with a strong engineering culture focused on reliability, automation, and continuous improvement.

The Role

We're seeking a DevOps Engineer to join our Infrastructure team in Seattle. You'll be responsible for building and maintaining our cloud infrastructure, implementing automation solutions, and ensuring the reliability and performance of our production systems. This hybrid role offers flexibility with 3 days in office and 2 days remote.

You'll work on exciting challenges including infrastructure as code, CI/CD pipeline optimization, Kubernetes cluster management, and observability improvements. This role is perfect for someone who loves automation, enjoys solving complex infrastructure problems, and wants to make a significant impact on system reliability.

What You'll Do

- Design, build, and maintain cloud infrastructure on AWS using Terraform
- Manage and optimize Kubernetes clusters for production workloads
- Implement and improve CI/CD pipelines using GitHub Actions and ArgoCD
- Build automation tools and scripts to improve operational efficiency
- Implement monitoring, alerting, and observability solutions
- Participate in on-call rotation and incident response
- Collaborate with development teams on deployment strategies and infrastructure requirements
- Ensure security best practices and compliance requirements are met

Requirements

- 5+ years of experience in DevOps, SRE, or infrastructure engineering roles
- Strong expertise in AWS services (EC2, ECS, RDS, S3, CloudFormation)
- Production experience with Kubernetes and container orchestration
- Proficiency in infrastructure as code tools (Terraform, CloudFormation, Pulumi)
- Strong scripting skills in Python, Bash, or Go
- Experience with CI/CD tools (GitHub Actions, Jenkins, GitLab CI)
- Deep understanding of networking, security, and system administration
- Experience with monitoring and observability tools (Prometheus, Grafana, ELK stack)
- Strong troubleshooting and problem-solving skills
- Excellent communication and collaboration abilities

Technical Stack

- Cloud: AWS (primary infrastructure)
- Containers: Docker, Kubernetes, Helm
- IaC: Terraform, AWS CloudFormation
- CI/CD: GitHub Actions, ArgoCD
- Monitoring: Prometheus, Grafana, Datadog
- Logging: ELK Stack, CloudWatch
- Configuration Management: Ansible

Nice to Have

- AWS certifications (Solutions Architect, DevOps Engineer)
- Experience with service mesh technologies (Istio, Linkerd)
- Knowledge of GitOps practices and tools
- Experience with database administration and optimization
- Familiarity with security scanning and compliance tools
- Experience with multi-cloud or hybrid cloud environments

Benefits

- Competitive salary: $140,000 - $170,000 based on experience
- Annual performance bonuses
- Comprehensive health, dental, and vision coverage
- 401(k) with 6% company match
- Flexible hybrid schedule (3 days office, 2 days remote)
- Generous PTO policy (20 days + holidays)
- Professional development and certification reimbursement
- Commuter benefits and parking
- Modern office in downtown Seattle with amenities
- Regular team events and activities
- Stock options

Location: Seattle, WA (Hybrid - 3 days in office)

Western Grid Technologies is an equal opportunity employer committed to diversity and inclusion in the workplace.
""",
    enrichment_transforms=(STRIP_EEO,),
)

MID_SOFTWARE_ONSITE_POSTING = RawJobPosting(
    raw="""
Software Engineer - Backend Services

About Metro Enterprise Platforms

Metro Enterprise Platforms builds mission-critical operational software for financial services and retail clients across North America. Our products process millions of transactions daily and are subject to strict SLA, compliance, and audit requirements. We are a 450-person company with engineering teams organized around product domains, each owning a full vertical from data model to API layer. We invest heavily in code quality, documentation, and structured on-boarding so that engineers can be productive quickly and confidently.

The Role

We are seeking a Software Engineer to join our Core Platform Services team in New York. You will design and implement backend services, build internal tooling used by multiple customer-facing teams, and maintain the reliability of APIs that financial and retail clients depend on every day. This is a fully on-site role with a structured Monday-Friday schedule and an on-call rotation once per quarter.

Responsibilities

- Deliver new features and improvements to Java-based microservices that process account, order, and transaction data for enterprise clients
- Maintain and evolve RESTful API contracts that are shared across three product verticals
- Write and maintain integration tests that run against real database and queue infrastructure in CI
- Participate in design reviews, sprint planning, and retrospectives with a cross-functional team of 6-8 engineers
- Diagnose and resolve production incidents using structured runbooks and observability tooling
- Contribute to data model design and schema evolution in PostgreSQL, ensuring backward-compatible migrations
- Review pull requests from teammates and junior engineers, providing clear and actionable feedback

Requirements

- 3-6 years of professional backend software engineering experience
- Strong proficiency in Java and the Spring Boot ecosystem (REST, JPA, Spring Security)
- Solid understanding of relational database design, SQL query optimization, and schema migrations
- Experience designing and consuming RESTful APIs in distributed microservice architectures
- Familiarity with message queue patterns (ActiveMQ, Kafka, or RabbitMQ)
- Understanding of software testing at the unit, integration, and contract levels
- Comfortable with Git-based workflows, code review, and CI/CD pipelines
- Strong written and verbal communication skills; ability to document work clearly for compliance purposes

Nice to Have

- Experience with Spring Cloud, service discovery, and distributed config management
- Familiarity with OAuth2 / OpenID Connect for secure API access in financial environments
- Background in fintech, payments, or regulated industry software development
- AWS or Azure cloud experience (we are currently migrating on-premise systems to the cloud)
- SOLID design principles and familiarity with domain-driven design patterns

Compensation and Benefits

- Base salary: $115,000 - $145,000 depending on experience
- Annual performance bonus (target 10% of base)
- Comprehensive health, dental, and vision insurance with low employee premiums
- 401(k) with 4% employer match (immediate vesting)
- 15 days PTO plus 10 company holidays
- Commuter benefits (MetroCard reimbursement up to $150/month)
- Tuition reimbursement up to $5,000/year for job-related coursework
- On-site gym access and wellness stipend
- Structured mentorship program for career advancement

Location: New York, NY — On-site (5 days/week)

Metro Enterprise Platforms is an equal opportunity employer. We are committed to fair and equitable hiring practices across all backgrounds, experiences, and identities.
""",
    enrichment_transforms=(STRIP_EEO,),
)

__all__ = [
    "DATA_SCIENTIST_REMOTE_POSTING",
    "DEVOPS_ENGINEER_HYBRID_POSTING",
    "JUNIOR_FRONTEND_HYBRID_POSTING",
    "MID_SOFTWARE_ONSITE_POSTING",
    "SENIOR_PYTHON_REMOTE_POSTING",
    "STAFF_PLATFORM_HYBRID_POSTING",
]
