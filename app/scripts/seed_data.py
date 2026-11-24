"""Static demo content for the seed script. Dates are expressed relative to "today"."""

from typing import Any

from app.features.news.models import NewsCategory as C

PROFILE: dict[str, Any] = {
    "headline": "Frontend Engineer → ML Engineer",
    "summary": (
        "Frontend engineer with 5+ years of experience building fast, accessible React and "
        "Next.js products used by millions. Now moving into machine learning engineering: "
        "shipped ranking experiments end to end and enjoy turning models into products people "
        "actually use."
    ),
    "location": "Chennai, India",
    "phone": "+91 98400 12345",
    "links": {
        "github": "https://github.com/mathan-dev",
        "linkedin": "https://www.linkedin.com/in/mathan-dev",
        "portfolio": "https://mathan.dev",
        "website": None,
    },
    "target_roles": ["ML Engineer", "Frontend Engineer", "Full-stack Engineer"],
    "preferences": {
        "locations": ["Bengaluru", "Chennai", "Remote"],
        "work_modes": ["remote", "hybrid"],
        "salary_min": 2_400_000,
        "salary_max": 3_600_000,
        "currency": "INR",
    },
}

EXPERIENCE: list[dict[str, Any]] = [
    {
        "company": "Freshworks",
        "title": "Senior Frontend Engineer",
        "location": "Chennai",
        "start_date": "2023-04-01",
        "end_date": None,
        "current": True,
        "description": "Customer-support workspace used by 60k+ businesses.",
        "highlights": [
            "Led the migration of the agent inbox to Next.js, cutting LCP by 38%",
            "Built a typed design-system package adopted by 9 product teams",
            "Shipped an ML-ranked reply-suggestion panel with the data science team (+12% usage)",
        ],
    },
    {
        "company": "Zoho",
        "title": "Software Engineer",
        "location": "Chennai",
        "start_date": "2020-07-01",
        "end_date": "2023-03-31",
        "current": False,
        "description": "Zoho CRM web client.",
        "highlights": [
            "Rebuilt the report builder in React with virtualised tables for 100k-row datasets",
            "Introduced Playwright end-to-end tests, reducing release regressions by half",
            "Mentored 4 interns on JavaScript fundamentals and code review",
        ],
    },
]

EDUCATION: list[dict[str, Any]] = [
    {
        "school": "Anna University",
        "degree": "B.E.",
        "field": "Computer Science and Engineering",
        "start_date": "2016-08-01",
        "end_date": "2020-05-31",
        "grade": "8.4 CGPA",
        "description": "Final-year project: sentiment analysis of Tamil tweets with LSTMs.",
    },
    {
        "school": "DeepLearning.AI (Coursera)",
        "degree": "Machine Learning Specialization",
        "field": None,
        "start_date": "2024-01-08",
        "end_date": "2024-06-30",
        "grade": None,
        "description": "Supervised learning, neural networks, recommender systems.",
    },
]

SKILLS = [
    ("TypeScript", "advanced", "language"),
    ("JavaScript", "advanced", "language"),
    ("Python", "intermediate", "language"),
    ("SQL", "intermediate", "language"),
    ("React", "advanced", "framework"),
    ("Next.js", "advanced", "framework"),
    ("FastAPI", "intermediate", "framework"),
    ("PyTorch", "intermediate", "ml"),
    ("scikit-learn", "intermediate", "ml"),
    ("pandas", "intermediate", "ml"),
    ("Docker", "intermediate", "tool"),
    ("Git", "advanced", "tool"),
    ("PostgreSQL", "intermediate", "tool"),
    ("AWS", "beginner", "tool"),
]

# (company, role, location, status, applied_days_ago | None, extra)
JOBS: list[tuple[str, str, str, str, int | None, dict[str, Any]]] = [
    (
        "Postman",
        "Frontend Engineer II",
        "Bengaluru",
        "saved",
        None,
        {"tags": ["react", "devtools"], "url": "https://www.postman.com/company/careers/"},
    ),
    (
        "Hugging Face",
        "ML Engineer, Inference",
        "Remote",
        "saved",
        None,
        {"tags": ["ml", "remote"], "url": "https://apply.workable.com/huggingface/"},
    ),
    (
        "Atlassian",
        "Senior Frontend Engineer",
        "Bengaluru (hybrid)",
        "saved",
        None,
        {"tags": ["react"], "salary_min": 3_000_000, "salary_max": 4_200_000},
    ),
    (
        "Swiggy",
        "ML Engineer, Search Ranking",
        "Bengaluru",
        "applied",
        3,
        {"tags": ["ml", "ranking"], "contact": "Priya (recruiter)"},
    ),
    ("Zerodha", "Frontend Engineer", "Bengaluru", "applied", 6, {"tags": ["react", "fintech"]}),
    ("Sarvam AI", "Applied ML Engineer", "Bengaluru", "applied", 9, {"tags": ["ml", "llm"]}),
    ("PhonePe", "Senior Frontend Engineer", "Bengaluru", "applied", 12, {"tags": ["react"]}),
    ("Groww", "Full-stack Engineer", "Bengaluru", "applied", 15, {"tags": ["nextjs", "python"]}),
    (
        "Vercel",
        "Frontend Engineer",
        "Remote",
        "interview",
        14,
        {
            "tags": ["nextjs", "remote"],
            "contact": "Alex (hiring manager)",
            "notes": "Round 2: system design for a dashboard + Next.js caching deep dive.",
            "url": "https://vercel.com/careers",
        },
    ),
    (
        "Flipkart",
        "ML Engineer",
        "Bengaluru",
        "interview",
        18,
        {"tags": ["ml"], "notes": "Technical round: ML fundamentals + one coding problem."},
    ),
    (
        "CRED",
        "Frontend Engineer",
        "Bengaluru",
        "interview",
        21,
        {"tags": ["react"], "notes": "Waiting for feedback after the onsite."},
    ),
    (
        "Razorpay",
        "Frontend Engineer",
        "Bengaluru",
        "offer",
        30,
        {
            "tags": ["react", "fintech"],
            "salary_min": 2_800_000,
            "salary_max": 3_200_000,
            "notes": "Offer received, decision due next week.",
        },
    ),
    ("Amazon", "SDE II (Frontend)", "Hyderabad", "rejected", 40, {"tags": ["react"]}),
    ("Google", "Software Engineer, ML", "Bengaluru", "rejected", 45, {"tags": ["ml"]}),
    ("Meesho", "ML Engineer", "Bengaluru", "rejected", 35, {"tags": ["ml"]}),
]

ROADMAPS: list[dict[str, Any]] = [
    {
        "key": "sysdesign",
        "title": "System Design",
        "goal": "Hold my own in senior system design interviews.",
        "status": "paused",
        "target_days": 150,
        "milestones": [
            (
                "Fundamentals: latency, throughput, CAP",
                "in_progress",
                -10,
                [("System Design Primer", "https://github.com/donnemartin/system-design-primer")],
            ),
            (
                "Scalability patterns: caching, queues, sharding",
                "todo",
                40,
                [("Designing Data-Intensive Applications", "https://dataintensive.net/")],
            ),
            (
                "Case studies: feed, chat, URL shortener",
                "todo",
                90,
                [("ByteByteGo", "https://bytebytego.com/")],
            ),
        ],
    },
    {
        "key": "dsa",
        "title": "DSA Practice",
        "goal": "Solve 150 interview problems with confidence.",
        "status": "active",
        "target_days": 75,
        "milestones": [
            (
                "Arrays & hashing",
                "done",
                -20,
                [("NeetCode roadmap", "https://neetcode.io/roadmap")],
            ),
            (
                "Two pointers & sliding window",
                "in_progress",
                7,
                [
                    (
                        "LeetCode Top Interview 150",
                        "https://leetcode.com/studyplan/top-interview-150/",
                    )
                ],
            ),
            (
                "Trees & graphs",
                "todo",
                35,
                [("CP-Algorithms graphs", "https://cp-algorithms.com/")],
            ),
            (
                "Dynamic programming",
                "todo",
                70,
                [("DP patterns", "https://leetcode.com/discuss/study-guide/458695/")],
            ),
        ],
    },
    {
        "key": "ml",
        "title": "ML Engineer",
        "goal": "Land an ML engineer role by shipping 3 end-to-end ML projects.",
        "status": "active",
        "target_days": 120,
        "milestones": [
            (
                "Python & math foundations",
                "done",
                -60,
                [
                    (
                        "Khan Academy linear algebra",
                        "https://www.khanacademy.org/math/linear-algebra",
                    ),
                    ("NumPy learn", "https://numpy.org/learn/"),
                ],
            ),
            (
                "Classical ML with scikit-learn",
                "done",
                -20,
                [
                    ("scikit-learn user guide", "https://scikit-learn.org/stable/user_guide.html"),
                    (
                        "ML Specialization",
                        "https://www.coursera.org/specializations/machine-learning-introduction",
                    ),
                ],
            ),
            (
                "Deep learning with PyTorch",
                "in_progress",
                25,
                [
                    ("PyTorch tutorials", "https://pytorch.org/tutorials/"),
                    ("fast.ai Practical Deep Learning", "https://course.fast.ai/"),
                ],
            ),
            (
                "MLOps & deployment",
                "todo",
                100,
                [
                    ("Made With ML", "https://madewithml.com/"),
                    ("Full Stack Deep Learning", "https://fullstackdeeplearning.com/"),
                ],
            ),
        ],
    },
]

# (title, roadmap key, milestone index, priority, due offset days | None, completed days ago | None)
TASKS: list[tuple[str, str | None, int | None, str, int | None, int | None]] = [
    # overdue
    ("Finish backprop derivation notes", "ml", 2, "high", -2, None),
    ("Solve 3 sliding-window problems", "dsa", 1, "medium", -1, None),
    # due today
    ("Implement a CNN on CIFAR-10", "ml", 2, "high", 0, None),
    ("Prep Vercel interview: rendering & caching", None, None, "high", 0, None),
    ("LeetCode: Longest Substring Without Repeating Characters", "dsa", 1, "medium", 0, None),
    ("Watch PyTorch autograd lecture", "ml", 2, "medium", 0, 0),
    # upcoming
    ("Follow up with Swiggy recruiter", None, None, "medium", 1, None),
    ("Read 'Attention Is All You Need'", "ml", 2, "medium", 2, None),
    ("Binary tree traversal problem set", "dsa", 2, "medium", 3, None),
    ("Fine-tune a small transformer with Hugging Face", "ml", 2, "medium", 5, None),
    ("DDIA chapter 5: replication", "sysdesign", 1, "low", 7, None),
    ("Dockerize the sentiment model API", "ml", 3, "low", 12, None),
    # no date
    ("Update portfolio with ML projects", None, None, "low", None, None),
    ("Write a blog post on React Server Components", None, None, "low", None, None),
    # done
    ("Linear algebra refresher", "ml", 0, "medium", -52, 50),
    ("Gradient descent from scratch in NumPy", "ml", 0, "high", -41, 40),
    ("Train a random forest on Titanic", "ml", 1, "medium", -26, 25),
    ("Kaggle: house prices regression", "ml", 1, "medium", -19, 18),
    ("Two Sum & Group Anagrams", "dsa", 0, "low", -8, 8),
    ("Top K frequent elements", "dsa", 0, "medium", -4, 4),
    ("Logistic regression notes", "ml", 1, "low", -3, 3),
]

# (category, source, domain, title, summary)
NEWS: list[tuple[C, str, str, str, str]] = [
    (
        C.AI,
        "Google AI Blog",
        "blog.google",
        "Gemini 2.5 Flash gets faster function calling",
        "Lower latency tool use and better structured outputs land in the Gemini API.",
    ),
    (
        C.AI,
        "Hugging Face",
        "huggingface.co",
        "Smaller, faster: distilling LLMs for on-device use",
        "A practical guide to knowledge distillation with Transformers and quantisation.",
    ),
    (
        C.AI,
        "The Batch",
        "deeplearning.ai",
        "Agents that write and run their own tests",
        "Research roundup: evaluation-driven agents and what they mean for software teams.",
    ),
    (
        C.AI,
        "PyTorch Blog",
        "pytorch.org",
        "torch.compile in practice: 2x faster training loops",
        "Benchmarks and gotchas from compiling real-world vision and language models.",
    ),
    (
        C.AI,
        "OpenAI",
        "openai.com",
        "Evaluating retrieval-augmented generation at scale",
        "How to build offline and online evals for RAG pipelines.",
    ),
    (
        C.AI,
        "Hugging Face",
        "huggingface.co",
        "Open-weight models top the new reasoning leaderboard",
        "Community models close the gap with proprietary systems on math and code.",
    ),
    (
        C.AI,
        "Google AI Blog",
        "blog.google",
        "Responsible AI: new tooling for model cards",
        "Generate and maintain model documentation directly from training pipelines.",
    ),
    (
        C.AI,
        "The Batch",
        "deeplearning.ai",
        "Why small language models are having a moment",
        "Cost, latency and privacy push teams towards compact, specialised models.",
    ),
    (
        C.WEB,
        "web.dev",
        "web.dev",
        "Interaction to Next Paint: a field guide",
        "Diagnose and fix slow interactions with real-user data and the new DevTools panel.",
    ),
    (
        C.WEB,
        "Vercel",
        "vercel.com",
        "Partial prerendering is now stable",
        "Static shells with streamed dynamic holes, without changing your data fetching.",
    ),
    (
        C.WEB,
        "Smashing Magazine",
        "smashingmagazine.com",
        "Designing accessible data tables",
        "Patterns for sortable, responsive and screen-reader friendly tables.",
    ),
    (
        C.WEB,
        "React Blog",
        "react.dev",
        "React Compiler: what changes for your components",
        "Automatic memoisation in production and how to adopt it incrementally.",
    ),
    (
        C.WEB,
        "CSS-Tricks",
        "css-tricks.com",
        "Container queries in real layouts",
        "Moving component styles away from viewport breakpoints.",
    ),
    (
        C.WEB,
        "web.dev",
        "web.dev",
        "View Transitions across documents",
        "Smooth multi-page navigations with a few lines of CSS.",
    ),
    (
        C.WEB,
        "Chrome Developers",
        "developer.chrome.com",
        "Baseline 2026: features you can ship",
        "A round-up of web platform features now available in all major browsers.",
    ),
    (
        C.WEB,
        "Smashing Magazine",
        "smashingmagazine.com",
        "TypeScript patterns for large apps",
        "Branded types, discriminated unions and safer API layers.",
    ),
    (
        C.CLOUD,
        "AWS News Blog",
        "aws.amazon.com",
        "Lambda adds faster cold starts for Python",
        "SnapStart support for Python functions reduces p99 start-up times.",
    ),
    (
        C.CLOUD,
        "Cloudflare Blog",
        "blog.cloudflare.com",
        "Running AI inference at the edge",
        "Lessons from serving open models across 300 cities.",
    ),
    (
        C.CLOUD,
        "Google Cloud Blog",
        "cloud.google.com",
        "Cloud Run GPUs are generally available",
        "Scale-to-zero GPU inference for containerised models.",
    ),
    (
        C.CLOUD,
        "Kubernetes Blog",
        "kubernetes.io",
        "Kubernetes 1.35: sidecars and smarter scheduling",
        "Native sidecar containers graduate and the scheduler gets topology hints.",
    ),
    (
        C.CLOUD,
        "AWS News Blog",
        "aws.amazon.com",
        "Aurora PostgreSQL adds pgvector speedups",
        "HNSW index builds are up to 3x faster for embedding workloads.",
    ),
    (
        C.CLOUD,
        "Cloudflare Blog",
        "blog.cloudflare.com",
        "How we cut egress costs with R2",
        "A migration story from a media-heavy startup.",
    ),
    (
        C.CLOUD,
        "Azure Updates",
        "azure.microsoft.com",
        "Container Apps gets dynamic sessions",
        "Sandboxed code execution for AI agents, billed per second.",
    ),
    (
        C.CLOUD,
        "Google Cloud Blog",
        "cloud.google.com",
        "FinOps for AI workloads",
        "Practical guardrails for GPU spend in experimentation-heavy teams.",
    ),
    (
        C.DATA,
        "KDnuggets",
        "kdnuggets.com",
        "Feature stores explained for beginners",
        "When you need one, and when a well-modelled warehouse table is enough.",
    ),
    (
        C.DATA,
        "Towards Data Science",
        "towardsdatascience.com",
        "Polars vs pandas in 2026",
        "Benchmarks on real ETL jobs and a migration checklist.",
    ),
    (
        C.DATA,
        "dbt Blog",
        "getdbt.com",
        "Semantic layers move into the warehouse",
        "Metric definitions that BI tools and LLMs can both query.",
    ),
    (
        C.DATA,
        "KDnuggets",
        "kdnuggets.com",
        "10 SQL window functions every analyst should know",
        "Ranking, running totals and gaps-and-islands with examples.",
    ),
    (
        C.DATA,
        "Databricks Blog",
        "databricks.com",
        "Lakehouse tables with Apache Iceberg",
        "Interoperable table formats and what they mean for your stack.",
    ),
    (
        C.DATA,
        "PostgreSQL News",
        "postgresql.org",
        "PostgreSQL 18 released",
        "Async I/O, virtual generated columns and faster upgrades.",
    ),
    (
        C.DATA,
        "Towards Data Science",
        "towardsdatascience.com",
        "A/B testing pitfalls in ML products",
        "Novelty effects, metric dilution and how to avoid them.",
    ),
    (
        C.DATA,
        "dbt Blog",
        "getdbt.com",
        "Testing data pipelines like software",
        "Unit tests for SQL models and contracts between teams.",
    ),
    (
        C.SECURITY,
        "Krebs on Security",
        "krebsonsecurity.com",
        "Passkeys adoption doubles in a year",
        "Large consumer platforms report fewer account takeovers after rollout.",
    ),
    (
        C.SECURITY,
        "The Hacker News",
        "thehackernews.com",
        "npm supply-chain attack targets CI tokens",
        "Malicious post-install scripts exfiltrated secrets from build pipelines.",
    ),
    (
        C.SECURITY,
        "OWASP",
        "owasp.org",
        "OWASP Top 10 for LLM applications updated",
        "Prompt injection and excessive agency remain the top risks.",
    ),
    (
        C.SECURITY,
        "Google Security Blog",
        "security.googleblog.com",
        "Memory-safe languages at scale",
        "How Rust adoption reduced memory-safety bugs in Android.",
    ),
    (
        C.SECURITY,
        "The Hacker News",
        "thehackernews.com",
        "Critical flaw patched in popular VPN gateways",
        "Administrators urged to update immediately as exploitation begins.",
    ),
    (
        C.SECURITY,
        "Krebs on Security",
        "krebsonsecurity.com",
        "Inside a phishing-as-a-service kit",
        "How criminals bypass SMS one-time codes and why passkeys stop them.",
    ),
    (
        C.SECURITY,
        "Cloudflare Blog",
        "blog.cloudflare.com",
        "Post-quantum TLS is now the default",
        "Hybrid key agreement protects traffic against harvest-now-decrypt-later attacks.",
    ),
    (
        C.SECURITY,
        "OWASP",
        "owasp.org",
        "Secure headers cheat sheet refreshed",
        "Recommended defaults for CSP, COOP and Permissions-Policy.",
    ),
]
