"""Resume test data as Python dictionaries for document generation."""

from __future__ import annotations

BACKEND_ENGINEER_RESUME = {
    "personal_info": {
        "full_name": "Alex Chen",
        "email": "alex.chen@email.com",
        "phone": "+1 (415) 555-0123",
        "location": "San Francisco, CA",
        "linkedin": "linkedin.com/in/alexchen",
        "github": "github.com/alexchen",
        "website": "alexchen.dev",
    },
    "summary": (
        "Senior Python Engineer with 6+ years of experience building scalable backend "
        "systems and microservices. Expert in distributed systems, event-driven "
        "architectures, and cloud-native technologies. Proven track record of leading "
        "technical initiatives, mentoring engineers, and delivering high-impact features "
        "that serve millions of users. Passionate about code quality, system reliability, "
        "and continuous improvement."
    ),
    "experience": [
        {
            "company": "TechFlow Systems",
            "position": "Senior Backend Engineer",
            "location": "San Francisco, CA (Remote)",
            "start_date": "2021-03",
            "end_date": None,
            "current": True,
            "highlights": [
                (
                    "Architected and implemented event-driven microservices using Python, "
                    "FastAPI, and Kafka, processing 50M+ events daily with 99.99% uptime"
                ),
                (
                    "Led migration from monolithic architecture to microservices, reducing "
                    "deployment time by 75% and improving system scalability"
                ),
                (
                    "Built real-time data processing pipelines using Redis Streams and "
                    "PostgreSQL, improving data freshness from hours to seconds"
                ),
                (
                    "Mentored 4 junior engineers, conducted code reviews, and established "
                    "engineering best practices across the team"
                ),
                (
                    "Implemented comprehensive observability using Prometheus, Grafana, and "
                    "OpenTelemetry, reducing mean time to resolution by 60%"
                ),
            ],
        },
        {
            "company": "DataCore Analytics",
            "position": "Backend Engineer",
            "location": "Seattle, WA",
            "start_date": "2019-01",
            "end_date": "2021-02",
            "current": False,
            "highlights": [
                (
                    "Developed RESTful APIs using Django and Django REST Framework serving "
                    "1M+ daily requests with sub-100ms latency"
                ),
                ("Optimized database queries and implemented caching strategies, reducing API response times by 40%"),
                ("Built automated testing framework achieving 90%+ code coverage and reducing production bugs by 50%"),
                ("Collaborated with data science team to productionize ML models using Docker and Kubernetes"),
            ],
        },
        {
            "company": "StartupHub Inc",
            "position": "Software Engineer",
            "location": "Austin, TX",
            "start_date": "2018-06",
            "end_date": "2018-12",
            "current": False,
            "highlights": [
                ("Developed full-stack features using Python/Flask backend and React frontend for SaaS platform"),
                ("Implemented user authentication and authorization using JWT and OAuth2"),
                ("Built CI/CD pipelines using GitHub Actions and deployed to AWS using Terraform"),
            ],
        },
    ],
    "education": [
        {
            "institution": "University of California, Berkeley",
            "degree": "Bachelor of Science",
            "field": "Computer Science",
            "location": "Berkeley, CA",
            "graduation_date": "2018-05",
            "gpa": "3.8",
            "honors": ["Dean's List", "Cum Laude"],
        },
    ],
    "skills": {
        "languages": ["Python", "SQL", "JavaScript", "Go", "Bash"],
        "frameworks": [
            "FastAPI",
            "Django",
            "Flask",
            "SQLAlchemy",
            "Pydantic",
            "Pytest",
        ],
        "databases": ["PostgreSQL", "Redis", "MongoDB", "Elasticsearch"],
        "infrastructure": [
            "Docker",
            "Kubernetes",
            "Terraform",
            "AWS",
            "GCP",
            "Kafka",
            "RabbitMQ",
        ],
        "tools": [
            "Git",
            "GitHub Actions",
            "Jenkins",
            "Prometheus",
            "Grafana",
            "Datadog",
            "Sentry",
        ],
    },
    "projects": [
        {
            "name": "Open Source Contributions",
            "description": (
                "Active contributor to FastAPI, SQLAlchemy, and other Python projects. "
                "Contributed bug fixes, documentation improvements, and new features."
            ),
            "technologies": ["Python", "FastAPI", "SQLAlchemy"],
            "url": "github.com/alexchen",
        },
        {
            "name": "Personal Blog Platform",
            "description": (
                "Built a high-performance blogging platform using FastAPI, PostgreSQL, "
                "and Redis. Implemented full-text search, caching, and real-time "
                "notifications."
            ),
            "technologies": ["Python", "FastAPI", "PostgreSQL", "Redis", "Docker"],
            "url": "alexchen.dev",
        },
    ],
    "certifications": [
        {
            "name": "AWS Certified Solutions Architect - Associate",
            "issuer": "Amazon Web Services",
            "date": "2022-06",
            "credential_id": "AWS-SAA-123456",
        },
        {
            "name": "Certified Kubernetes Application Developer (CKAD)",
            "issuer": "Cloud Native Computing Foundation",
            "date": "2021-09",
            "credential_id": "CKAD-789012",
        },
    ],
}
